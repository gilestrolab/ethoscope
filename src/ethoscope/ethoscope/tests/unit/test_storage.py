"""
Unit tests for ``ethoscope.utils.storage``: listing and removing run directories.

The node decides what is backed up; these tests cover the device's side of the
contract — describing files faithfully and refusing anything that is not a
well-formed run directory under a data root.
"""

import os

import pytest

try:
    from ethoscope.utils import storage
except ImportError:
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))
    from ethoscope.utils import storage


MACHINE = "0256424ac3f545b6b3c687723085ffcb"
NAME = "ETHOSCOPE_025"


def _make_file(path, size, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def roots(tmp_path):
    results = tmp_path / "results"
    videos = tmp_path / "videos"
    results.mkdir()
    videos.mkdir()
    return {"results": str(results), "videos": str(videos)}


def _run_dir(roots, key, dt):
    return os.path.join(roots[key], MACHINE, NAME, dt)


class TestListRuns:
    def test_groups_files_by_run_and_orders_oldest_first(self, roots):
        newer = _run_dir(roots, "results", "2026-06-15_16-17-33")
        older = _run_dir(roots, "results", "2026-02-11_17-01-03")
        _make_file(
            os.path.join(newer, f"2026-06-15_16-17-33_{MACHINE}.db"), 300, 1_782_143_000
        )
        _make_file(os.path.join(newer, f"2026-06-15_16-17-33_{MACHINE}.db-wal"), 0)
        _make_file(
            os.path.join(older, f"2026-02-11_17-01-03_{MACHINE}.db"), 100, 1_771_332_543
        )

        listing = storage.list_runs(roots)

        assert [r["rel_dir"] for r in listing["runs"]] == [
            f"{MACHINE}/{NAME}/2026-02-11_17-01-03",
            f"{MACHINE}/{NAME}/2026-06-15_16-17-33",
        ]
        run = listing["runs"][1]
        assert run["root"] == "results"
        assert run["path"] == newer
        assert run["size_bytes"] == 300
        by_name = {f["name"]: f for f in run["files"]}
        db = by_name[f"2026-06-15_16-17-33_{MACHINE}.db"]
        assert db["size"] == 300
        assert db["mtime"] == pytest.approx(1_782_143_000)
        assert by_name[f"2026-06-15_16-17-33_{MACHINE}.db-wal"]["size"] == 0

    def test_deeper_files_belong_to_their_run(self, roots):
        run = _run_dir(roots, "videos", "2026-03-01_10-00-00")
        _make_file(os.path.join(run, "chunk_00001.h264"), 10)
        _make_file(os.path.join(run, "sub", "recording.info"), 5)

        listing = storage.list_runs(roots)

        assert len(listing["runs"]) == 1
        names = sorted(f["name"] for f in listing["runs"][0]["files"])
        assert names == ["chunk_00001.h264", os.path.join("sub", "recording.info")]
        assert listing["runs"][0]["size_bytes"] == 15

    def test_shallow_files_are_other_and_never_runs(self, roots):
        _make_file(os.path.join(roots["videos"], "index.html"), 7)
        _make_file(os.path.join(roots["results"], MACHINE, "stray.txt"), 3)

        listing = storage.list_runs(roots)

        assert listing["runs"] == []
        assert listing["other"] == {"files": 2, "size_bytes": 10}

    def test_symlinks_are_ignored(self, roots, tmp_path):
        run = _run_dir(roots, "results", "2026-03-01_10-00-00")
        target = _make_file(str(tmp_path / "outside.bin"), 50)
        os.makedirs(run)
        os.symlink(target, os.path.join(run, "link.db"))

        listing = storage.list_runs(roots)

        assert listing["runs"] == []
        assert listing["other"]["files"] == 0

    def test_missing_root_is_skipped(self, roots):
        roots["videos"] = os.path.join(roots["videos"], "does-not-exist")
        assert storage.list_runs(roots) == {
            "runs": [],
            "other": {"files": 0, "size_bytes": 0},
        }


class TestValidateRunDir:
    def test_accepts_a_run_directory(self, roots):
        run = _run_dir(roots, "results", "2026-03-01_10-00-00")
        assert storage.validate_run_dir(run, roots) == (
            "results",
            os.path.realpath(run),
        )

    @pytest.mark.parametrize(
        "bad",
        [
            "relative/path",
            "/etc/passwd",
            os.path.join("{results}", MACHINE, NAME),  # two components
            os.path.join("{results}", MACHINE, NAME, "2026-03-01_10-00-00", "extra"),
            os.path.join("{results}", MACHINE, NAME, "not-a-date"),
            os.path.join("{results}", MACHINE, "..", "..", "2026-03-01_10-00-00"),
            os.path.join("{results}", MACHINE, "na me", "2026-03-01_10-00-00"),
            "{results}",
        ],
    )
    def test_rejects_malformed_paths(self, roots, bad):
        path = bad.format(results=roots["results"])
        with pytest.raises(ValueError):
            storage.validate_run_dir(path, roots)

    def test_rejects_symlink_escaping_the_root(self, roots, tmp_path):
        outside = tmp_path / "elsewhere" / "2026-03-01_10-00-00"
        outside.mkdir(parents=True)
        parent = os.path.join(roots["results"], MACHINE, NAME)
        os.makedirs(parent)
        link = os.path.join(parent, "2026-03-01_10-00-00")
        os.symlink(str(outside), link)

        with pytest.raises(ValueError):
            storage.validate_run_dir(link, roots)


class TestRemoveRuns:
    def test_removes_valid_run_and_reports_freed_bytes(self, roots):
        run = _run_dir(roots, "results", "2026-03-01_10-00-00")
        _make_file(os.path.join(run, "a.db"), 40)
        _make_file(os.path.join(run, "a.db-wal"), 2)
        keep = _run_dir(roots, "results", "2026-04-01_10-00-00")
        _make_file(os.path.join(keep, "b.db"), 9)

        result = storage.remove_runs([run], roots)

        assert result == {
            "removed": [{"path": run, "freed_bytes": 42}],
            "failed": [],
            "freed_bytes": 42,
        }
        assert not os.path.exists(run)
        assert os.path.exists(os.path.join(keep, "b.db"))

    def test_refuses_run_holding_protected_file(self, roots):
        run = _run_dir(roots, "results", "2026-03-01_10-00-00")
        live = _make_file(os.path.join(run, "live.db"), 40)

        result = storage.remove_runs([run], roots, protected=[live, None])

        assert result["removed"] == []
        assert result["failed"][0]["path"] == run
        assert "currently in use" in result["failed"][0]["error"]
        assert os.path.exists(live)

    def test_failure_does_not_stop_the_rest(self, roots):
        good = _run_dir(roots, "videos", "2026-03-01_10-00-00")
        _make_file(os.path.join(good, "chunk.h264"), 8)
        missing = _run_dir(roots, "videos", "2026-03-02_10-00-00")

        result = storage.remove_runs(["/etc", missing, good], roots)

        assert [f["path"] for f in result["failed"]] == ["/etc", missing]
        assert result["removed"] == [{"path": good, "freed_bytes": 8}]
        assert result["freed_bytes"] == 8
        assert os.path.isdir("/etc")
        assert not os.path.exists(good)
