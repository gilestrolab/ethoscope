"""
Tests for DeviceUpdater.change_branch.

These use real temporary git repositories (an "upstream" the device clones from) to
exercise actual git behaviour, since the bug being guarded against is that switching to a
branch the device had not yet fetched fails with "pathspec did not match". The fix fetches
before checking out, so brand-new remote branches become switchable and existing branches
land on the remote tip.
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
    with open(path, "w") as fh:
        fh.write(content)
    repo.index.add([filename])
    repo.index.commit(message)


@pytest.fixture
def repos(tmp_path):
    """Create an upstream repo on 'master' and a device clone of it."""
    upstream_dir = tmp_path / "upstream"
    upstream = Repo.init(upstream_dir, initial_branch="master")
    _configure(upstream)
    _commit(upstream, "file.txt", "v1", "initial commit on master")

    device_dir = tmp_path / "device"
    device = upstream.clone(device_dir)
    _configure(device)

    return upstream, device, device_dir


class TestChangeBranch:
    def test_switch_to_branch_created_after_clone(self, repos):
        """The core bug: a branch pushed after the device's last fetch must be switchable."""
        upstream, device, device_dir = repos

        # Create a brand-new branch upstream AFTER the device cloned, so the device has no
        # local knowledge of it yet.
        upstream.git.checkout("-b", "device-mjpeg-http-stream")
        _commit(upstream, "file.txt", "v2", "feature work")
        upstream.git.checkout("master")

        du = updater.DeviceUpdater(str(device_dir))
        du.change_branch("device-mjpeg-http-stream")

        assert device.active_branch.name == "device-mjpeg-http-stream"
        assert (device_dir / "file.txt").read_text() == "v2"

    def test_switch_existing_branch_lands_on_remote_tip(self, repos):
        """Switching to a known branch advances to the latest remote commit."""
        upstream, device, device_dir = repos

        # Branch exists at clone time...
        upstream.git.checkout("-b", "feature")
        _commit(upstream, "file.txt", "vA", "feature A")
        upstream.git.checkout("master")
        device.remotes.origin.fetch()  # device now knows feature@vA

        # ...then upstream advances the branch.
        upstream.git.checkout("feature")
        _commit(upstream, "file.txt", "vB", "feature B")
        upstream.git.checkout("master")

        du = updater.DeviceUpdater(str(device_dir))
        du.change_branch("feature")

        assert device.active_branch.name == "feature"
        assert (device_dir / "file.txt").read_text() == "vB"

    def test_switch_back_to_master(self, repos):
        """Regression: switching to the default branch still works."""
        upstream, device, device_dir = repos

        upstream.git.checkout("-b", "other")
        _commit(upstream, "file.txt", "v2", "other work")
        upstream.git.checkout("master")

        du = updater.DeviceUpdater(str(device_dir))
        du.change_branch("other")
        assert device.active_branch.name == "other"

        du.change_branch("master")
        assert device.active_branch.name == "master"
        assert (device_dir / "file.txt").read_text() == "v1"

    def test_invalid_branch_type_raises(self, repos):
        upstream, device, device_dir = repos
        du = updater.DeviceUpdater(str(device_dir))
        with pytest.raises(updater.DeviceUpdateError):
            du.change_branch(123)

    def test_unknown_branch_raises(self, repos):
        upstream, device, device_dir = repos
        du = updater.DeviceUpdater(str(device_dir))
        with pytest.raises(updater.DeviceUpdateError):
            du.change_branch("does-not-exist-anywhere")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
