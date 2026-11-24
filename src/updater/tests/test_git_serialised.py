"""
Tests for serialising the update server's use of git.

A GitPython Repo reads objects through one long-lived `git cat-file --batch` pipe and is
not thread-safe, while cheroot serves requests on several threads. The updater page asks
for /bare/update and /devices at the same moment; on 2026-11-19 the two interleaved on
the bare repository's pipe and left it out of step, and from then on every /devices call
failed with "binascii.Error: Odd-length string" until the service was restarted. Without
the lock, two threads reading branch tips through one Repo also simply hang.
"""

import os
import sys
import threading

import pytest
from git import Repo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import update_server  # noqa: E402

import updater  # noqa: E402


def _commit(repo, filename, content, message):
    path = os.path.join(repo.working_tree_dir, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)
    repo.index.add([filename])
    return repo.index.commit(message)


@pytest.fixture
def node(tmp_path, monkeypatch):
    """
    The update server of a node whose bare repo tracks a local upstream, with devices
    sitting on an old commit of 'dev'. Returns the sha of the tip of 'dev'.
    """
    upstream = Repo.init(tmp_path / "upstream", initial_branch="dev")
    with upstream.config_writer() as cw:
        cw.set_value("user", "email", "test@example.com")
        cw.set_value("user", "name", "Test")
    old = _commit(upstream, "src/ethoscope/tracker.py", "v1", "old device code")
    for n in range(2, 6):
        tip = _commit(upstream, "src/ethoscope/tracker.py", f"v{n}", f"device code {n}")
    upstream.git.branch("muenster-branch")

    bare_dir = tmp_path / "ethoscope.git"
    Repo.clone_from(tmp_path / "upstream", bare_dir, bare=True)

    def device_map():
        return {
            f"d{i}": {
                "id": f"d{i}",
                "active_branch": "dev",
                "local_commit": {"id": old.hexsha},
            }
            for i in range(8)
        }

    monkeypatch.setattr(update_server, "is_node", True)
    monkeypatch.setattr(update_server, "generate_new_device_map", device_map)
    monkeypatch.setattr(
        update_server, "bare_repo_updater", updater.BareRepoUpdater(str(bare_dir))
    )
    return tip.hexsha


def run_together(*jobs, deadline=60):
    """
    Run each (function, repeats) on its own thread at once; collect what they return.

    Returns:
        tuple: (results, hung) where hung counts threads still running at the deadline.
    """
    results, lock = [], threading.Lock()

    def loop(fn, repeats):
        for _ in range(repeats):
            out = fn()
            with lock:
                results.append(out)

    # Daemon threads, so that a hang fails the test instead of blocking its exit
    threads = [threading.Thread(target=loop, args=job, daemon=True) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=deadline)
    return results, sum(t.is_alive() for t in threads)


def test_the_page_load_requests_can_run_at_once(node):
    tip = node
    scans, bare_updates = (update_server.scan_subnet, 15), (
        lambda: update_server.bare("update"),
        3,
    )

    results, hung = run_together(scans, scans, scans, bare_updates, bare_updates)

    assert hung == 0
    assert not [r for r in results if "error" in r]
    device_maps = [r for r in results if "d0" in r]
    assert len(device_maps) == 45
    for devices in device_maps:
        for device in devices.values():
            assert device["origin_commit"]["id"] == tip
            assert device["up_to_date"] is False


@pytest.mark.parametrize(
    "fn",
    [
        "device",
        "change_branch",
        "bare",
        "judge_devices_locally",
        "handle_node_update",
        "handle_node_branch_change",
    ],
)
def test_every_route_that_touches_git_takes_the_lock(fn):
    assert getattr(update_server, fn).__wrapped__  # set by git_serialised
