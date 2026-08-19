"""
Tests for judging a device's update status from the node rather than asking the device.

The failure this replaces is self-concealing. A device whose fetch refspec is broken
compares its HEAD against a tracking ref that never refreshes, concludes it is up to
date, and is therefore never offered the update that would repair the refspec. The
table shows green, nobody acts, and the device stays months behind forever --
ETHOSCOPE_358, _361, _363 and _380 sat like that from April and May 2026.

The device's *reported HEAD* is reliable; only its conclusion is not. The node's bare
repository is what the device pulls from (`git://node.local/ethoscope.git`), so the node
holds everything needed to answer the question itself.
"""

import os
import sys

import pytest
from git import Repo

# The updater package is a standalone script directory (no installable package), so make it
# importable directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import updater  # noqa: E402

DEVICE_PATHS = ["src/ethoscope", "services", "src/updater", "accessories"]


def _configure(repo):
    cw = repo.config_writer()
    cw.set_value("user", "email", "test@example.com")
    cw.set_value("user", "name", "Test")
    cw.release()


def _commit(repo, filename, content, message):
    path = os.path.join(repo.working_tree_dir, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)
    repo.index.add([filename])
    return repo.index.commit(message)


@pytest.fixture
def bare(tmp_path):
    """
    A bare repo standing in for /srv/git/ethoscope.git, plus the shas of three commits.

    Returns (BareRepoUpdater, old, middle, tip) where `middle` differs from `tip` only
    in a path no device cares about.
    """
    upstream_dir = tmp_path / "upstream"
    upstream = Repo.init(upstream_dir, initial_branch="dev")
    _configure(upstream)

    old = _commit(upstream, "src/ethoscope/tracker.py", "v1", "old device code")
    middle = _commit(upstream, "src/ethoscope/tracker.py", "v2", "new device code")
    tip = _commit(upstream, "docs/readme.md", "docs only", "a change no device needs")

    bare_dir = tmp_path / "ethoscope.git"
    Repo.clone_from(upstream_dir, bare_dir, bare=True)

    return (
        updater.BareRepoUpdater(str(bare_dir)),
        old.hexsha,
        middle.hexsha,
        tip.hexsha,
    )


def test_device_on_the_tip_is_current(bare):
    repo, _old, _middle, tip = bare

    up_to_date, found_tip = repo.is_current(tip, "dev", DEVICE_PATHS)

    assert up_to_date is True
    assert found_tip.hexsha == tip


def test_device_months_behind_is_not_current(bare):
    """The production case: the node contradicts the device's own green verdict."""
    repo, old, _middle, tip = bare

    up_to_date, found_tip = repo.is_current(old, "dev", DEVICE_PATHS)

    assert up_to_date is False
    assert found_tip.hexsha == tip


def test_changes_outside_monitored_paths_do_not_count(bare):
    """A device behind only on docs does not need disturbing."""
    repo, _old, middle, tip = bare

    up_to_date, found_tip = repo.is_current(middle, "dev", DEVICE_PATHS)

    assert up_to_date is True
    assert found_tip.hexsha == tip


def test_without_monitored_paths_any_difference_counts(bare):
    repo, _old, middle, _tip = bare

    up_to_date, _found_tip = repo.is_current(middle, "dev")

    assert up_to_date is False


def test_unknown_branch_is_undecidable(bare):
    """Do not overrule the device on a branch this node does not carry."""
    repo, old, _middle, _tip = bare

    up_to_date, found_tip = repo.is_current(old, "some-feature-branch", DEVICE_PATHS)

    assert up_to_date is None
    assert found_tip is None


def test_unknown_commit_is_undecidable_but_still_reports_the_tip(bare):
    """A device on a commit this node has never seen keeps its own verdict."""
    repo, _old, _middle, tip = bare

    up_to_date, found_tip = repo.is_current("0" * 40, "dev", DEVICE_PATHS)

    assert up_to_date is None
    assert found_tip.hexsha == tip


def test_branch_tip_returns_none_for_a_missing_branch(bare):
    repo, _old, _middle, _tip = bare

    assert repo.branch_tip("no-such-branch") is None


def test_node_overrules_a_device_that_claims_to_be_current(bare, monkeypatch):
    """
    End to end through the /devices post-processing.

    This is the ETHOSCOPE_358 case: the device reports up_to_date=True with
    origin_commit equal to its own local_commit, because its tracking ref never
    refreshes. The node must contradict it.
    """
    import update_server

    repo, old, _middle, tip = bare
    monkeypatch.setattr(update_server, "bare_repo_updater", repo)
    monkeypatch.setattr(update_server, "is_node", True)

    devices_map = {
        "358": {
            "name": "ETHOSCOPE_358",
            "active_branch": "dev",
            "up_to_date": True,
            "local_commit": {"id": old, "date": "2026-05-29 14:46:11"},
            "origin_commit": {"id": old, "date": "2026-05-29 14:46:11"},
            "version": {"id": old, "date": "2026-05-29 14:46:11"},
        }
    }

    update_server.judge_devices_locally(devices_map)

    assert devices_map["358"]["up_to_date"] is False
    assert devices_map["358"]["origin_commit"]["id"] == tip


def test_node_confirms_a_device_that_really_is_current(bare, monkeypatch):
    import update_server

    repo, _old, _middle, tip = bare
    monkeypatch.setattr(update_server, "bare_repo_updater", repo)

    devices_map = {
        "025": {
            "active_branch": "dev",
            "up_to_date": True,
            "local_commit": {"id": tip, "date": "2026-08-19 15:27:01"},
            "version": {"id": tip, "date": "2026-08-19 15:27:01"},
        }
    }

    update_server.judge_devices_locally(devices_map)

    assert devices_map["025"]["up_to_date"] is True


def test_device_without_check_update_is_judged_on_its_running_version(
    bare, monkeypatch
):
    """
    check_update may fail outright; /data still reports the running commit.

    That is a lower bound on how current the device is, and enough to say the code it
    is executing is stale -- which is the thing worth acting on.
    """
    import update_server

    repo, old, _middle, _tip = bare
    monkeypatch.setattr(update_server, "bare_repo_updater", repo)

    devices_map = {
        "391": {
            "active_branch": "dev",
            "version": {"id": old, "date": "2026-07-22 07:14:34"},
        }
    }

    update_server.judge_devices_locally(devices_map)

    assert devices_map["391"]["up_to_date"] is False


def test_unreachable_device_is_left_alone(bare, monkeypatch):
    """Nothing to judge from, so no verdict is invented."""
    import update_server

    repo, _old, _middle, _tip = bare
    monkeypatch.setattr(update_server, "bare_repo_updater", repo)

    devices_map = {"380": {"name": "ETHOSCOPE_380", "status": "Unreachable"}}

    update_server.judge_devices_locally(devices_map)

    assert "up_to_date" not in devices_map["380"]


def test_no_bare_repo_is_a_no_op(monkeypatch):
    """A device running this code has no bare repo and must not crash on it."""
    import update_server

    monkeypatch.setattr(update_server, "bare_repo_updater", None)

    devices_map = {"025": {"active_branch": "dev", "up_to_date": True}}
    update_server.judge_devices_locally(devices_map)

    assert devices_map["025"]["up_to_date"] is True
