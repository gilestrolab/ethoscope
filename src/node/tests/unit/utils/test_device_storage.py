"""
Unit tests for ``ethoscope_node.utils.device_storage``.

These cover the rule that decides whether a device run may be deleted: every file
present on the node with the same size and mtime, with the documented exceptions for
SQLite write-ahead logs and for h264 chunks the node has already merged into an mp4.
They also cover the free-space assessment the web interface consults before a run
starts.
"""

import os
import unittest

from ethoscope_node.utils.device_storage import (
    DEFAULT_PERCENT_THRESHOLD,
    MP4_SETTLE_S,
    _parse_df_size,
    assess_free_space,
    classify_run,
    summarise,
    thresholds_for,
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


# A 32 GB card, the standard ethoscope medium, at various degrees of fullness.
def disk(size="29G", used="15G", avail="14G", use="52%"):
    """A df line shaped like the one a device serves with its run listing."""
    return {
        "Filesystem": "/dev/mmcblk0p2",
        "Type": "ext4",
        "Size": size,
        "Used": used,
        "Avail": avail,
        "Use%": use,
        "Mounted": "/",
    }


FULL_CARD = disk(used="27G", avail="1.9G", use="93%")
HALF_CARD = disk()
# 82% used still leaves a tracking run all the room it needs, and a video run none.
TIGHT_CARD = disk(used="23G", avail="5.0G", use="82%")


class TestParseDfSize(unittest.TestCase):
    """Reading df's human-readable figures."""

    def test_suffixes(self):
        self.assertEqual(_parse_df_size("440K"), 440 * 1024)
        self.assertEqual(_parse_df_size("512M"), 512 * 1024**2)
        self.assertEqual(_parse_df_size("5.0G"), int(5.0 * 1024**3))
        self.assertEqual(_parse_df_size("1.5T"), int(1.5 * 1024**4))

    def test_bare_byte_count_and_zero(self):
        self.assertEqual(_parse_df_size("1024"), 1024)
        self.assertEqual(_parse_df_size(4096), 4096)
        self.assertEqual(_parse_df_size("0"), 0)

    def test_explicit_byte_and_binary_suffixes(self):
        self.assertEqual(_parse_df_size("512B"), 512)
        self.assertEqual(_parse_df_size("29GiB"), 29 * 1024**3)

    def test_decimal_comma_from_a_non_c_locale(self):
        self.assertEqual(_parse_df_size("9,2G"), _parse_df_size("9.2G"))

    def test_a_grouped_number_is_unreadable_rather_than_tiny(self):
        # Reason: reading "1,024" as 1.024 bytes would look like a full disk.
        self.assertIsNone(_parse_df_size("1,024"))

    def test_unreadable_values_are_none_not_zero(self):
        for value in ("", "-", "n/a", "abc", None, True, "-5G"):
            self.assertIsNone(_parse_df_size(value), value)


class TestThresholdsFor(unittest.TestCase):
    """Resolving the gates from the node's alerts configuration."""

    def test_video_is_held_to_a_higher_bar_than_tracking(self):
        self.assertGreater(
            thresholds_for("video")["min_free_bytes"],
            thresholds_for("tracking")["min_free_bytes"],
        )

    def test_defaults_apply_when_the_configuration_predates_the_keys(self):
        gates = thresholds_for("tracking", {"storage_warning_threshold": 80})

        self.assertEqual(gates["percent"], DEFAULT_PERCENT_THRESHOLD)
        self.assertEqual(gates["min_free_bytes"], 2 * 1024**3)

    def test_configuration_overrides(self):
        gates = thresholds_for(
            "video",
            {
                "storage_start_warning_percent": 75,
                "min_free_gb_video": 40,
                "storage_percent_warning_ceiling_gb": 100,
            },
        )

        self.assertEqual(gates["percent"], 75)
        self.assertEqual(gates["min_free_bytes"], 40 * 1024**3)
        self.assertEqual(gates["percent_ceiling_bytes"], 100 * 1024**3)

    def test_an_unknown_action_gets_the_lower_bar(self):
        self.assertEqual(
            thresholds_for("nonsense")["min_free_bytes"],
            thresholds_for("tracking")["min_free_bytes"],
        )

    def test_junk_values_fall_back_rather_than_raise(self):
        gates = thresholds_for("tracking", {"min_free_gb_tracking": "lots"})

        self.assertEqual(gates["min_free_bytes"], 2 * 1024**3)


class TestAssessFreeSpace(unittest.TestCase):
    """The warning shown before a run starts."""

    def test_a_full_card_warns_on_percentage(self):
        result = assess_free_space(FULL_CARD, {}, "tracking")

        self.assertTrue(result["warn"])
        self.assertIn("percent", result["triggered_by"])
        self.assertEqual(result["used_percent"], 93)

    def test_a_half_empty_card_is_quiet(self):
        for action in ("tracking", "video"):
            self.assertFalse(assess_free_space(HALF_CARD, {}, action)["warn"], action)

    def test_the_same_card_warns_for_video_but_not_tracking(self):
        self.assertFalse(assess_free_space(TIGHT_CARD, {}, "tracking")["warn"])

        video = assess_free_space(TIGHT_CARD, {}, "video")
        self.assertTrue(video["warn"])
        self.assertEqual(video["triggered_by"], ["free_space"])

    def test_a_large_disk_does_not_cry_wolf(self):
        # 91% of a terabyte is still 90 GB free, which is not a problem.
        roomy = disk(size="1.0T", used="930G", avail="90G", use="91%")

        for action in ("tracking", "video"):
            self.assertFalse(assess_free_space(roomy, {}, action)["warn"], action)

    def test_both_gates_can_fire_at_once(self):
        result = assess_free_space(FULL_CARD, {}, "video")

        self.assertEqual(result["triggered_by"], ["percent", "free_space"])

    def test_an_unreadable_disk_never_warns(self):
        for bad in (None, {}, {"Use%": "", "Avail": "-"}, {"Avail": "abc"}):
            self.assertFalse(assess_free_space(bad, {}, "video")["warn"], bad)

    def test_percentage_still_works_when_free_space_is_unreadable(self):
        result = assess_free_space({"Use%": "95%", "Avail": "n/a"}, {}, "tracking")

        self.assertTrue(result["warn"])
        self.assertEqual(result["triggered_by"], ["percent"])

    def test_reclaimable_space_is_quoted(self):
        totals = {
            "reclaimable_bytes": 18 * 1024**3,
            "backed_up_runs": 17,
            "pending_runs": 0,
        }

        reasons = " ".join(assess_free_space(FULL_CARD, totals, "tracking")["reasons"])

        self.assertIn("18.0 GB can be freed", reasons)
        self.assertIn("17 runs are already backed up", reasons)

    def test_a_single_backed_up_run_reads_as_singular(self):
        totals = {"reclaimable_bytes": 1024**3, "backed_up_runs": 1, "pending_runs": 2}

        reasons = " ".join(assess_free_space(FULL_CARD, totals, "tracking")["reasons"])

        self.assertIn("1 run is already backed up", reasons)

    def test_nothing_backed_up_says_there_is_nothing_safe_to_delete(self):
        totals = {"reclaimable_bytes": 0, "backed_up_runs": 0, "pending_runs": 6}

        result = assess_free_space(FULL_CARD, totals, "tracking")

        self.assertEqual(result["reclaimable_bytes"], 0)
        self.assertIn("None of its 6 runs", " ".join(result["reasons"]))

    def test_a_single_pending_run_reads_as_singular(self):
        totals = {"reclaimable_bytes": 0, "backed_up_runs": 0, "pending_runs": 1}

        reasons = " ".join(assess_free_space(FULL_CARD, totals, "tracking")["reasons"])

        self.assertIn("Its one run is not backed up yet", reasons)

    def test_a_full_card_holding_no_runs_points_elsewhere(self):
        totals = {"reclaimable_bytes": 0, "backed_up_runs": 0, "pending_runs": 0}

        reasons = " ".join(assess_free_space(FULL_CARD, totals, "tracking")["reasons"])

        self.assertIn("holds no runs", reasons)

    def test_the_most_recent_run_of_the_same_kind_is_quoted(self):
        runs = [
            {
                "root": "videos",
                "kind": "videos",
                "date": "2026-05-11_12-09-57",
                "size_bytes": 8 * 1024**3,
            },
            {
                "root": "results",
                "kind": "results",
                "date": "2026-06-15_16-17-33",
                "size_bytes": 2 * 1024**3,
            },
        ]

        video = assess_free_space(FULL_CARD, {}, "video", runs=runs)
        tracking = assess_free_space(FULL_CARD, {}, "tracking", runs=runs)

        self.assertIn(
            "recording run used 8.0 GB (2026-05-11)", " ".join(video["reasons"])
        )
        self.assertIn(
            "tracking run used 2.0 GB (2026-06-15)", " ".join(tracking["reasons"])
        )

    def test_no_run_of_that_kind_is_simply_not_mentioned(self):
        runs = [{"root": "results", "kind": "results", "size_bytes": 1024}]

        reasons = " ".join(
            assess_free_space(FULL_CARD, {}, "video", runs=runs)["reasons"]
        )

        self.assertNotIn("most recent", reasons)

    def test_explicit_thresholds_are_honoured(self):
        gates = {
            "percent": 99,
            "min_free_bytes": 100 * 1024**3,
            "percent_ceiling_bytes": 200 * 1024**3,
        }

        result = assess_free_space(HALF_CARD, {}, "tracking", gates)

        self.assertTrue(result["warn"])
        self.assertEqual(result["triggered_by"], ["free_space"])

    def test_a_quiet_assessment_carries_no_sentences(self):
        self.assertEqual(assess_free_space(HALF_CARD, {}, "tracking")["reasons"], [])


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
