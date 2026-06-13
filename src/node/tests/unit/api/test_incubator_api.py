"""
Unit tests for the Incubator API endpoints (live / merged / bind).
"""

import unittest
from unittest.mock import Mock, patch

from ethoscope_node.api.incubator_api import IncubatorAPI


class TestIncubatorAPI(unittest.TestCase):
    """Test suite for IncubatorAPI."""

    def setUp(self):
        self.mock_server = Mock()
        self.mock_server.app = Mock()
        self.mock_server.config = {}
        self.mock_server.device_scanner = Mock()
        self.mock_server.sensor_scanner = Mock()
        self.mock_server.incubator_scanner = Mock()
        self.mock_server.database = Mock()
        self.mock_server.results_dir = "/tmp/results"
        self.mock_server.sensors_dir = "/tmp/sensors"
        self.mock_server.roi_templates_dir = "/tmp/templates"
        self.mock_server.tmp_imgs_dir = "/tmp/imgs"

        self.api = IncubatorAPI(self.mock_server)

    def test_register_routes(self):
        """Three routes are registered."""
        route_calls = []

        def mock_route(path, method):
            def decorator(func):
                route_calls.append((path, method))
                return func

            return decorator

        self.api.app.route = mock_route
        self.api.register_routes()

        paths = {c[0] for c in route_calls}
        self.assertEqual(len(route_calls), 3)
        self.assertIn("/incubators/live", paths)
        self.assertIn("/incubators/merged", paths)
        self.assertIn("/incubator/bind", paths)

    def test_get_live_returns_scanner_info(self):
        self.api.incubator_scanner.get_all_devices_info.return_value = {
            "incubator-1": {"hostname": "incubator-1", "temperature": 22.0}
        }
        result = self.api._get_incubators_live()
        self.assertIn("incubator-1", result)

    def test_get_live_no_scanner(self):
        self.api.incubator_scanner = None
        self.assertEqual(self.api._get_incubators_live(), {})

    @patch("ethoscope_node.utils.etho_db.ExperimentalDB")
    def test_merged_joins_on_hostname(self, mock_db_cls):
        """A configured incubator bound to an online unit merges to source='both';
        a discovered unbound unit appears as source='discovered'."""
        self.api.incubator_scanner.get_all_devices_info.return_value = {
            "incubator-1": {
                "hostname": "incubator-1",
                "status": "online",
                "temperature": 22.5,
                "node_id": 1,
            },
            "incubator-9": {
                "hostname": "incubator-9",
                "status": "online",
                "temperature": 19.0,
                "node_id": 9,
            },
        }
        mock_db = mock_db_cls.return_value
        mock_db.getAllIncubators.return_value = {
            "Incubator 1": {"name": "Incubator 1", "hostname": "incubator-1", "active": 1},
            "Spare": {"name": "Spare", "hostname": None, "active": 1},
        }

        merged = self.api._get_incubators_merged()

        self.assertEqual(merged["Incubator 1"]["source"], "both")
        self.assertEqual(merged["Incubator 1"]["temperature"], 22.5)
        self.assertEqual(merged["Incubator 1"]["live_status"], "online")

        # Unbound configured record -> still present, no live data
        self.assertEqual(merged["Spare"]["source"], "configured")
        self.assertEqual(merged["Spare"]["live_status"], "unbound")

        # Discovered-only unit (no record references incubator-9)
        self.assertIn("incubator-9", merged)
        self.assertEqual(merged["incubator-9"]["source"], "discovered")

    @patch("ethoscope_node.utils.etho_db.ExperimentalDB")
    def test_bind_updates_db_and_pushes_location(self, mock_db_cls):
        mock_db = mock_db_cls.return_value
        mock_db.updateIncubator.return_value = 0  # >= 0 == success
        self.api.get_request_json = Mock(
            return_value={"name": "Incubator 1", "hostname": "incubator-1"}
        )
        self.api.incubator_scanner.set_location.return_value = {"status": "ok"}

        result = self.api._bind_incubator()

        self.assertEqual(result["result"], "success")
        self.assertTrue(result["location_pushed"])
        mock_db.updateIncubator.assert_called_once_with(
            name="Incubator 1", hostname="incubator-1"
        )
        self.api.incubator_scanner.set_location.assert_called_once_with(
            "incubator-1", "Incubator 1"
        )

    @patch("ethoscope_node.utils.etho_db.ExperimentalDB")
    def test_bind_requires_name(self, mock_db_cls):
        self.api.get_request_json = Mock(return_value={"hostname": "incubator-1"})
        result = self.api._bind_incubator()
        self.assertEqual(result["result"], "error")
        mock_db_cls.return_value.updateIncubator.assert_not_called()

    @patch("ethoscope_node.utils.etho_db.ExperimentalDB")
    def test_unbind_with_null_hostname(self, mock_db_cls):
        """A null hostname unbinds and does not push a location."""
        mock_db = mock_db_cls.return_value
        mock_db.updateIncubator.return_value = 0
        self.api.get_request_json = Mock(
            return_value={"name": "Incubator 1", "hostname": None}
        )

        result = self.api._bind_incubator()

        self.assertEqual(result["result"], "success")
        self.assertFalse(result["location_pushed"])
        mock_db.updateIncubator.assert_called_once_with(
            name="Incubator 1", hostname=None
        )
        self.api.incubator_scanner.set_location.assert_not_called()


if __name__ == "__main__":
    unittest.main()
