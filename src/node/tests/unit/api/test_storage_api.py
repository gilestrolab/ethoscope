"""
Unit tests for Storage API endpoints.

Cover the node's orchestration: fetching the device listing, marking each run against
the node's own copies, refusing to forward anything unverified to the device, and the
pre-flight assessment the web interface asks for before starting a run.
"""

import unittest
from unittest.mock import Mock, patch

from ethoscope_node.api.storage_api import (
    OUTDATED_FIRMWARE_ERROR,
    UNREACHABLE_ERROR,
    StorageAPI,
)
from ethoscope_node.utils.device_storage import DEFAULT_PERCENT_THRESHOLD

REL_DIR = "abc123/ETHOSCOPE_025/2026-06-15_16-17-33"
RUN_PATH = f"/ethoscope_data/results/{REL_DIR}"
OTHER_RUN_PATH = "/ethoscope_data/results/abc123/ETHOSCOPE_025/2026-02-11_17-01-03"


def device_listing(runs=None):
    """A device ``/data/runs`` response."""
    if runs is None:
        runs = [
            {
                "root": "results",
                "rel_dir": REL_DIR,
                "path": RUN_PATH,
                "size_bytes": 300,
                "files": [{"name": "a.db", "size": 300, "mtime": 1_782_143_000}],
            }
        ]
    return {
        "runs": runs,
        "other": {"files": 1, "size_bytes": 7},
        "disk": {"Use%": "93%"},
    }


class TestStorageAPI(unittest.TestCase):
    """Test suite for StorageAPI."""

    def setUp(self):
        self.mock_server = Mock()
        self.mock_server.app = Mock()
        self.mock_server.device_scanner = Mock()
        self.mock_server.results_dir = "/node/results"
        self.mock_server.videos_dir = "/node/videos"
        self.mock_server.config = Mock()
        self.mock_server.config.content = {
            "folders": {
                "results": {"path": "/configured/results"},
                "video": {"path": "/configured/videos"},
            }
        }

        self.api = StorageAPI(self.mock_server)

        self.device = Mock()
        self.device.info.return_value = {"status": "stopped"}
        self.device.list_runs.return_value = device_listing()
        self.mock_server.device_scanner.get_device.return_value = self.device

    def test_register_routes(self):
        """Both storage routes are registered."""
        route_calls = []

        def mock_route(path, method):
            def decorator(func):
                route_calls.append((path, method))
                return func

            return decorator

        self.api.app.route = mock_route
        self.api.register_routes()

        self.assertIn(("/device/<id>/storage", "GET"), route_calls)
        self.assertIn(("/device/<id>/storage/purge", "POST"), route_calls)

    def test_node_dirs_prefer_configuration(self):
        """The node dirs match what the backup daemon writes to."""
        self.assertEqual(
            self.api._node_dirs(),
            {"results": "/configured/results", "videos": "/configured/videos"},
        )

    def test_node_dirs_fall_back_to_server_directories(self):
        """A configuration without folder paths falls back to the server's."""
        self.mock_server.config.content = {}
        api = StorageAPI(self.mock_server)

        self.assertEqual(
            api._node_dirs(), {"results": "/node/results", "videos": "/node/videos"}
        )

    @patch("ethoscope_node.api.storage_api.classify_run")
    def test_get_storage_returns_classified_runs_and_totals(self, mock_classify):
        """The GET reports disk usage, runs and reclaimable totals."""
        mock_classify.side_effect = lambda run, dirs: {**run, "backed_up": True}

        result = self.api._get_device_storage("device1")

        self.assertEqual(result["device_id"], "device1")
        self.assertEqual(result["disk"], {"Use%": "93%"})
        self.assertEqual(result["other"], {"files": 1, "size_bytes": 7})
        self.assertEqual(result["totals"]["backed_up_runs"], 1)
        self.assertEqual(result["totals"]["reclaimable_bytes"], 300)
        self.assertTrue(result["runs"][0]["backed_up"])

    @patch("ethoscope_node.api.storage_api.BaseAPI.get_query_param")
    @patch("ethoscope_node.api.storage_api.classify_run")
    def test_no_action_leaves_the_response_unchanged(self, mock_classify, mock_param):
        """The Free up space modal asks without an action and must see what it did."""
        mock_classify.side_effect = lambda run, dirs: {**run, "backed_up": True}
        mock_param.return_value = None

        self.assertNotIn("preflight", self.api._get_device_storage("device1"))

    @patch("ethoscope_node.api.storage_api.BaseAPI.get_query_param")
    @patch("ethoscope_node.api.storage_api.classify_run")
    def test_an_unknown_action_is_ignored(self, mock_classify, mock_param):
        """A typo must not be answered with an assessment of the wrong kind."""
        mock_classify.side_effect = lambda run, dirs: {**run, "backed_up": True}
        mock_param.return_value = "trakcing"

        self.assertNotIn("preflight", self.api._get_device_storage("device1"))

    @patch("ethoscope_node.api.storage_api.BaseAPI.get_query_param")
    @patch("ethoscope_node.api.storage_api.classify_run")
    def test_preflight_warns_on_a_full_card(self, mock_classify, mock_param):
        """A 93% full device is reported as low on space, with the reason in words."""
        mock_classify.side_effect = lambda run, dirs: {**run, "backed_up": True}
        mock_param.return_value = "tracking"

        preflight = self.api._get_device_storage("device1")["preflight"]

        self.assertTrue(preflight["warn"])
        self.assertEqual(preflight["action"], "tracking")
        self.assertEqual(preflight["used_percent"], 93)
        self.assertTrue(preflight["reasons"])

    @patch("ethoscope_node.api.storage_api.BaseAPI.get_query_param")
    @patch("ethoscope_node.api.storage_api.classify_run")
    def test_preflight_quotes_what_the_purge_would_reclaim(
        self, mock_classify, mock_param
    ):
        """The figure in the warning is the one the Free up space modal would act on."""
        mock_classify.side_effect = lambda run, dirs: {**run, "backed_up": True}
        mock_param.return_value = "tracking"

        result = self.api._get_device_storage("device1")

        self.assertEqual(
            result["preflight"]["reclaimable_bytes"],
            result["totals"]["reclaimable_bytes"],
        )

    @patch("ethoscope_node.api.storage_api.BaseAPI.get_query_param")
    @patch("ethoscope_node.api.storage_api.classify_run")
    def test_video_and_tracking_are_judged_differently(self, mock_classify, mock_param):
        """The same disk warns for a recording and not for tracking."""
        mock_classify.side_effect = lambda run, dirs: {**run, "backed_up": True}
        self.device.list_runs.return_value = device_listing()
        self.device.list_runs.return_value["disk"] = {
            "Size": "29G",
            "Avail": "5.0G",
            "Use%": "82%",
        }

        mock_param.return_value = "tracking"
        self.assertFalse(self.api._get_device_storage("device1")["preflight"]["warn"])

        mock_param.return_value = "video"
        self.assertTrue(self.api._get_device_storage("device1")["preflight"]["warn"])

    @patch("ethoscope_node.api.storage_api.BaseAPI.get_query_param")
    @patch("ethoscope_node.api.storage_api.classify_run")
    def test_preflight_does_not_require_a_stopped_device(
        self, mock_classify, mock_param
    ):
        """Unlike a purge, asking about space is harmless while a run is going."""
        mock_classify.side_effect = lambda run, dirs: {**run, "backed_up": True}
        mock_param.return_value = "video"
        self.device.info.return_value = {"status": "running"}

        self.assertIn("preflight", self.api._get_device_storage("device1"))

    @patch("ethoscope_node.api.storage_api.BaseAPI.get_query_param")
    def test_an_unreachable_device_carries_no_assessment(self, mock_param):
        """Fail open: no assessment means the caller starts the run as before."""
        mock_param.return_value = "tracking"
        self.mock_server.device_scanner.get_device.return_value = None

        result = self.api._get_device_storage("device1")

        self.assertEqual(result, {"error": UNREACHABLE_ERROR})
        self.assertNotIn("preflight", result)

    @patch("ethoscope_node.api.storage_api.BaseAPI.get_query_param")
    def test_outdated_firmware_carries_no_assessment(self, mock_param):
        """A device too old to list its runs also must not block a start."""
        mock_param.return_value = "video"
        self.device.list_runs.return_value = None

        result = self.api._get_device_storage("device1")

        self.assertEqual(result, {"error": OUTDATED_FIRMWARE_ERROR})
        self.assertNotIn("preflight", result)

    def test_thresholds_come_from_the_configuration(self):
        """An operator can retune the gates without touching the code."""
        self.mock_server.config.content = {
            "alerts": {"storage_start_warning_percent": 50}
        }
        api = StorageAPI(self.mock_server)

        self.assertEqual(api._thresholds("tracking")["percent"], 50)

    def test_thresholds_fall_back_when_the_configuration_has_no_alerts(self):
        """Installations predating these keys still get the default warning."""
        self.mock_server.config.content = {}
        api = StorageAPI(self.mock_server)

        gates = api._thresholds("video")

        self.assertEqual(gates["percent"], DEFAULT_PERCENT_THRESHOLD)
        self.assertEqual(gates["min_free_bytes"], 10 * 1024**3)

    def test_get_storage_reports_unreachable_device(self):
        """A device the scanner does not have reads as unreachable, not a traceback."""
        self.mock_server.device_scanner.get_device.return_value = None

        self.assertEqual(
            self.api._get_device_storage("device1"), {"error": UNREACHABLE_ERROR}
        )

    @patch("ethoscope_node.api.storage_api.BaseAPI.get_request_json")
    def test_purge_reports_unreachable_device(self, mock_json):
        """Purging an absent device reports it plainly and deletes nothing."""
        mock_json.return_value = {"runs": [RUN_PATH]}
        self.mock_server.device_scanner.get_device.return_value = None

        self.assertEqual(
            self.api._purge_device_storage("device1"), {"error": UNREACHABLE_ERROR}
        )

    def test_get_storage_reports_outdated_firmware(self):
        """A device that cannot list its runs gets an explanatory error."""
        self.device.list_runs.return_value = None

        self.assertEqual(
            self.api._get_device_storage("device1"), {"error": OUTDATED_FIRMWARE_ERROR}
        )

    @patch("ethoscope_node.api.storage_api.BaseAPI.get_request_json")
    def test_purge_refuses_while_device_is_running(self, mock_json):
        """No deletion happens unless the device is stopped."""
        mock_json.return_value = {"runs": [RUN_PATH]}
        self.device.info.return_value = {"status": "running"}

        result = self.api._purge_device_storage("device1")

        self.assertIn("running", result["error"])
        self.device.remove_runs.assert_not_called()

    @patch("ethoscope_node.api.storage_api.BaseAPI.get_request_json")
    def test_purge_refuses_empty_selection(self, mock_json):
        """An empty request is rejected before the device is contacted."""
        mock_json.return_value = {"runs": []}

        self.assertEqual(
            self.api._purge_device_storage("device1"), {"error": "No runs selected"}
        )
        self.device.remove_runs.assert_not_called()

    @patch("ethoscope_node.api.storage_api.classify_run")
    @patch("ethoscope_node.api.storage_api.BaseAPI.get_request_json")
    def test_purge_forwards_only_verified_runs(self, mock_json, mock_classify):
        """A run that is not backed up is skipped, never sent to the device."""
        mock_json.return_value = {"runs": [RUN_PATH]}
        mock_classify.side_effect = lambda run, dirs: {
            **run,
            "backed_up": False,
            "reason": "Not backed up yet: 1 file(s) missing on the node.",
        }

        result = self.api._purge_device_storage("device1")

        self.device.remove_runs.assert_not_called()
        self.assertEqual(result["deleted"], [])
        self.assertEqual(result["freed_bytes"], 0)
        self.assertEqual(result["skipped"][0]["path"], RUN_PATH)
        self.assertIn("missing", result["skipped"][0]["reason"])

    @patch("ethoscope_node.api.storage_api.classify_run")
    @patch("ethoscope_node.api.storage_api.BaseAPI.get_request_json")
    def test_purge_skips_runs_absent_from_fresh_listing(self, mock_json, mock_classify):
        """A path the device no longer reports is never forwarded."""
        mock_json.return_value = {"runs": [OTHER_RUN_PATH]}
        mock_classify.side_effect = lambda run, dirs: {**run, "backed_up": True}

        result = self.api._purge_device_storage("device1")

        self.device.remove_runs.assert_not_called()
        self.assertEqual(result["skipped"][0]["path"], OTHER_RUN_PATH)
        self.assertIn("No longer present", result["skipped"][0]["reason"])

    @patch("ethoscope_node.api.storage_api.classify_run")
    @patch("ethoscope_node.api.storage_api.BaseAPI.get_request_json")
    def test_purge_deletes_verified_run(self, mock_json, mock_classify):
        """A verified run is deleted and the device's report passed back."""
        mock_json.return_value = {"runs": [RUN_PATH]}
        mock_classify.side_effect = lambda run, dirs: {**run, "backed_up": True}
        self.device.remove_runs.return_value = {
            "removed": [{"path": RUN_PATH, "freed_bytes": 300}],
            "failed": [],
            "freed_bytes": 300,
            "disk": {"Use%": "80%"},
        }

        result = self.api._purge_device_storage("device1")

        self.device.remove_runs.assert_called_once_with([RUN_PATH])
        self.assertEqual(result["deleted"], [{"path": RUN_PATH, "freed_bytes": 300}])
        self.assertEqual(result["freed_bytes"], 300)
        self.assertEqual(result["disk"], {"Use%": "80%"})
        self.assertEqual(result["skipped"], [])

    @patch("ethoscope_node.api.storage_api.classify_run")
    @patch("ethoscope_node.api.storage_api.BaseAPI.get_request_json")
    def test_purge_reports_device_side_failures(self, mock_json, mock_classify):
        """A run the device refused is reported as skipped with its reason."""
        mock_json.return_value = {"runs": [RUN_PATH]}
        mock_classify.side_effect = lambda run, dirs: {**run, "backed_up": True}
        self.device.remove_runs.return_value = {
            "removed": [],
            "failed": [{"path": RUN_PATH, "error": "run holds the database in use"}],
            "freed_bytes": 0,
            "disk": {},
        }

        result = self.api._purge_device_storage("device1")

        self.assertEqual(result["deleted"], [])
        self.assertIn("database in use", result["skipped"][0]["reason"])

    @patch("ethoscope_node.api.storage_api.classify_run")
    @patch("ethoscope_node.api.storage_api.BaseAPI.get_request_json")
    def test_purge_handles_unreachable_device(self, mock_json, mock_classify):
        """A device that drops out mid-purge yields an error, not a false success."""
        mock_json.return_value = {"runs": [RUN_PATH]}
        mock_classify.side_effect = lambda run, dirs: {**run, "backed_up": True}
        self.device.remove_runs.return_value = None

        result = self.api._purge_device_storage("device1")

        self.assertIn("did not confirm", result["error"])


if __name__ == "__main__":
    unittest.main()
