"""
Unit tests for ``ethoscope_node.utils.device_storage``.

These cover the rule that decides whether a device run may be deleted: every file
present on the node with the same size and mtime, with the documented exceptions for
SQLite write-ahead logs and for h264 chunks the node has already merged into an mp4.
"""

import os
import unittest

from ethoscope_node.utils.device_storage import (
    MP4_SETTLE_S,
    classify_run,
    summarise,
)

NODE_RESULTS = "/node/results"
NODE_VIDEOS = "/node/videos"
NODE_DIRS = {"results": NODE_RESULTS, "videos": NODE_VIDEOS}
REL_DIR = "abc123/ETHOSCOPE_025/2026-06-15_16-17-33"
NOW = 2_000_000_000.0


class FakeStat:
    """Minimal stand-in for ``os.stat_result``."""

    def __init__(self, size, mtime):
        self.st_size = size
        self.st_mtime = mtime


def make_run(files, root="results"):
    """Build a device listing entry."""
    return {
        "root": root,
        "rel_dir": REL_DIR,
        "path": f"/ethoscope_data/{root}/{REL_DIR}",
        "size_bytes": sum(f["size"] for f in files),
        "files": files,
    }


def fake_fs(files, entries=None):
    """
    Return ``(stat, listdir)`` backed by a dict of node paths to (size, mtime).

    Args:
        files (dict): Node path to ``(size, mtime)``.
        entries (dict | None): Directory path to the names it contains.
    """

    def stat(path):
        if path not in files:
            raise FileNotFoundError(path)
        return FakeStat(*files[path])

    def listdir(path):
        if entries is None or path not in entries:
            raise FileNotFoundError(path)
        return entries[path]

    return stat, listdir


def node_path(name, root="results"):
    base = NODE_RESULTS if root == "results" else NODE_VIDEOS
    return os.path.join(base, REL_DIR, name)


class TestClassifyRun(unittest.TestCase):
    """The backed-up decision for a single run."""

    def _classify(self, run, files, entries=None):
        stat, listdir = fake_fs(files, entries)
        return classify_run(run, NODE_DIRS, stat=stat, listdir=listdir, now=NOW)

    def test_identical_file_is_backed_up(self):
        run = make_run([{"name": "a.db", "size": 300, "mtime": 1_782_143_000}])
        result = self._classify(run, {node_path("a.db"): (300, 1_782_143_000)})

        self.assertTrue(result["backed_up"])
        self.assertEqual(result["reason"], "Backed up")
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["date"], "2026-06-15_16-17-33")
        self.assertEqual(result["kind"], "results")

    def test_missing_file_is_not_backed_up(self):
        run = make_run([{"name": "a.db", "size": 300, "mtime": 1_782_143_000}])
        result = self._classify(run, {})

        self.assertFalse(result["backed_up"])
        self.assertEqual(result["missing"], ["a.db"])
        self.assertIn("1 file(s) missing", result["reason"])

    def test_size_mismatch_is_not_backed_up(self):
        run = make_run([{"name": "a.db", "size": 300, "mtime": 1_782_143_000}])
        result = self._classify(run, {node_path("a.db"): (299, 1_782_143_000)})

        self.assertFalse(result["backed_up"])
        self.assertEqual(result["missing"], ["a.db"])

    def test_mtime_within_tolerance_is_backed_up(self):
        run = make_run([{"name": "a.db", "size": 300, "mtime": 1_782_143_000}])
        result = self._classify(run, {node_path("a.db"): (300, 1_782_143_001)})

        self.assertTrue(result["backed_up"])

    def test_mtime_beyond_tolerance_is_not_backed_up(self):
        run = make_run([{"name": "a.db", "size": 300, "mtime": 1_782_143_000}])
        result = self._classify(run, {node_path("a.db"): (300, 1_782_143_003)})

        self.assertFalse(result["backed_up"])
        self.assertEqual(result["missing"], ["a.db"])

    def test_non_empty_wal_blocks_deletion(self):
        run = make_run(
            [
                {"name": "a.db", "size": 300, "mtime": 1_782_143_000},
                {"name": "a.db-wal", "size": 4_606_192, "mtime": 1_782_143_000},
            ]
        )
        result = self._classify(run, {node_path("a.db"): (300, 1_782_143_000)})

        self.assertFalse(result["backed_up"])
        self.assertIn("write-ahead log", result["reason"])
        self.assertIn("4.4 MB", result["reason"])

    def test_empty_wal_and_shm_need_no_copy(self):
        run = make_run(
            [
                {"name": "a.db", "size": 300, "mtime": 1_782_143_000},
                {"name": "a.db-wal", "size": 0, "mtime": 1_782_143_000},
                {"name": "a.db-shm", "size": 32768, "mtime": 1_782_143_000},
            ]
        )
        result = self._classify(run, {node_path("a.db"): (300, 1_782_143_000)})

        self.assertTrue(result["backed_up"])

    def test_missing_h264_accepted_when_node_holds_settled_mp4(self):
        run = make_run(
            [{"name": "c_00001.h264", "size": 10, "mtime": 1_700_000_000}],
            root="videos",
        )
        node_dir = os.path.join(NODE_VIDEOS, REL_DIR)
        files = {os.path.join(node_dir, "c_merged.mp4"): (5, NOW - MP4_SETTLE_S - 1)}
        result = self._classify(run, files, {node_dir: ["c_merged.mp4"]})

        self.assertTrue(result["backed_up"])

    def test_missing_h264_rejected_when_mp4_is_still_being_written(self):
        run = make_run(
            [{"name": "c_00001.h264", "size": 10, "mtime": 1_700_000_000}],
            root="videos",
        )
        node_dir = os.path.join(NODE_VIDEOS, REL_DIR)
        files = {os.path.join(node_dir, "c_merged.mp4"): (5, NOW - 10)}
        result = self._classify(run, files, {node_dir: ["c_merged.mp4"]})

        self.assertFalse(result["backed_up"])
        self.assertEqual(result["missing"], ["c_00001.h264"])

    def test_missing_h264_rejected_when_a_tmp_file_is_present(self):
        run = make_run(
            [{"name": "c_00001.h264", "size": 10, "mtime": 1_700_000_000}],
            root="videos",
        )
        node_dir = os.path.join(NODE_VIDEOS, REL_DIR)
        files = {os.path.join(node_dir, "c_merged.mp4"): (5, NOW - MP4_SETTLE_S - 1)}
        entries = {node_dir: ["c_merged.mp4", "c_merged.tmp"]}
        result = self._classify(run, files, entries)

        self.assertFalse(result["backed_up"])

    def test_missing_h264_rejected_when_node_dir_is_absent(self):
        run = make_run(
            [{"name": "c_00001.h264", "size": 10, "mtime": 1_700_000_000}],
            root="videos",
        )
        result = self._classify(run, {})

        self.assertFalse(result["backed_up"])

    def test_unknown_root_is_never_deletable(self):
        run = make_run([{"name": "a.db", "size": 1, "mtime": 1}], root="sensors")
        result = self._classify(run, {})

        self.assertFalse(result["backed_up"])
        self.assertIn("No backup folder", result["reason"])

    def test_reports_at_most_five_missing_files(self):
        files = [
            {"name": f"c_{i:05d}.h264", "size": 10, "mtime": 1_700_000_000}
            for i in range(9)
        ]
        result = self._classify(make_run(files, root="videos"), {})

        self.assertEqual(len(result["missing"]), 5)
        self.assertIn("9 file(s) missing", result["reason"])

    def test_original_run_is_not_mutated(self):
        run = make_run([{"name": "a.db", "size": 300, "mtime": 1_782_143_000}])
        self._classify(run, {})

        self.assertNotIn("backed_up", run)


class TestSummarise(unittest.TestCase):
    """Totals shown above the run table."""

    def test_counts_and_reclaimable_bytes(self):
        runs = [
            {"backed_up": True, "size_bytes": 100},
            {"backed_up": True, "size_bytes": 250},
            {"backed_up": False, "size_bytes": 40},
        ]

        self.assertEqual(
            summarise(runs),
            {
                "reclaimable_bytes": 350,
                "backed_up_runs": 2,
                "pending_runs": 1,
                "total_bytes": 390,
            },
        )

    def test_empty_listing(self):
        self.assertEqual(
            summarise([]),
            {
                "reclaimable_bytes": 0,
                "backed_up_runs": 0,
                "pending_runs": 0,
                "total_bytes": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
