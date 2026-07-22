"""
Tests for BareRepoUpdater.update_all_visible_branches.

The dict this method returns is what feeds the branch-switch dropdown in the update
server UI (via the /bare/update endpoint). A namespaced branch such as 'fix/222' must
appear in that dict, otherwise it can never be selected. The regression guarded against
here is a filter that only kept refs with exactly one slash, silently dropping every
branch whose name itself contained a slash.
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
def bare_updater(tmp_path):
    """Create an upstream with several branches and a bare clone wrapped in a BareRepoUpdater."""
    upstream_dir = tmp_path / "upstream"
    upstream = Repo.init(upstream_dir, initial_branch="master")
    _configure(upstream)
    _commit(upstream, "file.txt", "v1", "initial commit on master")

    # A plain branch and two namespaced (slash-containing) branches.
    for branch in ("dev", "fix/222", "feature/new-ui"):
        upstream.git.checkout("-b", branch, "master")
        _commit(upstream, "file.txt", f"content-{branch}", f"work on {branch}")
    upstream.git.checkout("master")

    bare_dir = tmp_path / "bare"
    upstream.clone(bare_dir, bare=True)

    return updater.BareRepoUpdater(str(bare_dir))


class TestUpdateAllVisibleBranches:
    def test_namespaced_branch_is_visible(self, bare_updater):
        """A branch like 'fix/222' must be selectable, i.e. present in the results dict."""
        results = bare_updater.update_all_visible_branches()

        assert "fix/222" in results
        assert "feature/new-ui" in results
        assert results["fix/222"] is True

    def test_plain_branches_still_visible(self, bare_updater):
        """Regression: ordinary single-segment branches remain present."""
        results = bare_updater.update_all_visible_branches()

        assert "master" in results
        assert "dev" in results

    def test_head_ref_excluded(self, bare_updater):
        """The remote HEAD pseudo-ref must not leak in as a branch."""
        results = bare_updater.update_all_visible_branches()

        assert "HEAD" not in results


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
