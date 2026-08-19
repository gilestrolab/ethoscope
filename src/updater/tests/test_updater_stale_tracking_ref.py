"""
Tests for DeviceUpdater.get_local_and_origin_commits against a stale tracking ref.

These use real temporary git repositories because the bug being guarded against is a
genuine git behaviour rather than a logic slip: when `remote.origin.fetch` is missing
from a device's config, `git fetch` still exits 0 but writes nothing under
refs/remotes/. The tracking ref then stays frozen at whatever it last was -- typically
the commit HEAD is on -- so the device compares itself against a stale mirror of itself
and reports "up to date" no matter how far behind it has fallen.

Observed in production on 2026-08-19: five ethoscopes showed a green "Up to Date" badge
next to commits up to four months old, each with origin_commit exactly equal to
local_commit.
"""

import os
import sys

import pytest
from git import Repo

# The updater package is a standalone script directory (no installable package), so make it
# importable directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import updater  # noqa: E402


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
    repo.index.commit(message)


def _drop_fetch_refspec(repo):
    """Reproduce the broken device config: a remote with no fetch refspec."""
    cw = repo.config_writer()
    cw.remove_option('remote "origin"', "fetch")
    cw.release()


def _narrow_fetch_refspec(repo):
    """
    Reproduce the production config: a refspec that exists but does not cover 'dev'.

    This is what a single-branch clone leaves behind once the device has been moved to
    another branch. `git fetch` then succeeds and refreshes nothing relevant, so
    refs/remotes/origin/dev keeps whatever value it was left with -- in production, the
    device's own HEAD.
    """
    cw = repo.config_writer()
    cw.set_value(
        'remote "origin"', "fetch", "+refs/heads/master:refs/remotes/origin/master"
    )
    cw.release()


def _fetch_refspec(repo):
    """
    Read remote.origin.fetch, or None when it is absent.

    GitPython's `get_value(..., default=None)` still raises, since it treats a None
    default as "no default given" -- hence the explicit try/except.
    """
    try:
        return repo.config_reader().get_value('remote "origin"', "fetch")
    except Exception:
        return None


@pytest.fixture
def repos(tmp_path):
    """An upstream repo on 'dev', a device clone of it, and one new upstream commit."""
    upstream_dir = tmp_path / "upstream"
    upstream = Repo.init(upstream_dir, initial_branch="dev")
    _configure(upstream)
    _commit(upstream, "file.txt", "v1", "initial commit on dev")
    # A second branch, so a narrowed refspec has something real to fetch.
    upstream.create_head("master")

    device_dir = tmp_path / "device"
    device = upstream.clone(device_dir)
    _configure(device)

    # The device is now at v1; upstream moves on to v2.
    _commit(upstream, "src/ethoscope/tracker.py", "v2", "a change the device wants")

    return upstream, device


def test_reports_outdated_when_behind(repos):
    """Baseline: a healthy clone that is one commit behind is reported as behind."""
    _upstream, device = repos

    dev_updater = updater.DeviceUpdater(device.working_tree_dir)
    local_commit, origin_commit = dev_updater.get_local_and_origin_commits()

    assert local_commit != origin_commit


def test_reports_outdated_despite_frozen_tracking_ref(repos):
    """
    The production failure, exactly: origin_commit collapsed onto local_commit.

    ETHOSCOPE_224, _310, _311, _358 and _363 each reported up_to_date=True with
    origin_commit == local_commit, on commits between one and four months old.
    """
    upstream, device = repos
    _narrow_fetch_refspec(device)

    # refs/remotes/origin/dev is left pointing at the device's own HEAD, which is what
    # a fetch that cannot refresh it leaves behind.
    device.create_head("refs/remotes/origin/dev", device.head.commit)

    dev_updater = updater.DeviceUpdater(device.working_tree_dir)
    local_commit, origin_commit = dev_updater.get_local_and_origin_commits()

    assert str(origin_commit) != str(local_commit), (
        "origin commit collapsed onto the local commit: the device is comparing "
        "itself against a stale mirror of itself and will report 'up to date' forever"
    )
    assert str(origin_commit) == str(upstream.head.commit)


def test_reports_outdated_despite_missing_fetch_refspec(repos):
    """
    The regression: with no fetch refspec, the tracking ref cannot refresh itself.

    Before the fix, origin_commit came straight off refs/remotes/origin/dev, which
    `git fetch` had silently left pointing at the device's own HEAD -- so the two
    commits compared equal and the device claimed to be up to date.
    """
    _upstream, device = repos
    _drop_fetch_refspec(device)

    dev_updater = updater.DeviceUpdater(device.working_tree_dir)
    local_commit, origin_commit = dev_updater.get_local_and_origin_commits()

    assert origin_commit != local_commit, (
        "origin commit collapsed onto the local commit: the device is comparing "
        "itself against a stale mirror of itself"
    )
    assert str(origin_commit) == str(_upstream.head.commit)


def test_missing_fetch_refspec_is_repaired(repos):
    """Constructing a DeviceUpdater should heal the config, not just work around it."""
    _upstream, device = repos
    _drop_fetch_refspec(device)

    assert _fetch_refspec(device) is None

    updater.DeviceUpdater(device.working_tree_dir)

    assert "+refs/heads/*:refs/remotes/origin/*" in _fetch_refspec(device)


def test_tracking_ref_is_refreshed_by_the_check(repos):
    """After the check, refs/remotes/origin/dev must point at the upstream tip."""
    upstream, device = repos
    _drop_fetch_refspec(device)

    dev_updater = updater.DeviceUpdater(device.working_tree_dir)
    dev_updater.get_local_and_origin_commits()

    assert str(device.remotes.origin.refs["dev"].commit) == str(upstream.head.commit)


def test_up_to_date_clone_still_compares_equal(repos):
    """A device that really is current must not be reported as behind."""
    _upstream, device = repos
    device.remotes.origin.pull()

    dev_updater = updater.DeviceUpdater(device.working_tree_dir)
    local_commit, origin_commit = dev_updater.get_local_and_origin_commits()

    assert str(local_commit) == str(origin_commit)


def test_ensure_fetch_refspec_reports_whether_it_changed_anything(repos):
    """The helper distinguishes 'already correct' from 'had to repair'."""
    _upstream, device = repos

    assert updater.ensure_fetch_refspec(device) is True

    _drop_fetch_refspec(device)
    assert updater.ensure_fetch_refspec(device) is False
    assert updater.ensure_fetch_refspec(device) is True
