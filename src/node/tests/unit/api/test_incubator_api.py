"""
Unit tests for the Incubator API bridge.

After Phase 2 the bridge delegates to
``ethoscope_node.incubators.routes.IncubatorRoutes`` — the heavy logic
(merged view, push, bind) is covered exhaustively in the subpackage tests.
Here we verify route registration and the bridge's responsibility:
deserialising bottle requests, talking to the ExperimentalDB adapter, and
keeping the legacy URL contract.
"""

import unittest
from unittest.mock import Mock, patch

from ethoscope_node.api.incubator_api import IncubatorAPI


def _make_mock_server():
    server = Mock()
    server.app = Mock()
    server.config = {}
    server.device_scanner = Mock()
    server.sensor_scanner = Mock()

    # Scanner returns a list of devices with id/info — the routes inspect these.
    scanner = Mock()
    scanner.get_all_devices_info.return_value = {}
    server.incubator_scanner = scanner

    # ExperimentalDB stub: the adapter calls these by name.
    db = Mock()
    db.getAllIncubators.return_value = {}
    db.getIncubatorByName.return_value = {}  # empty dict == not found
    db.getIncubatorById.return_value = {}
    db.updateIncubator.return_value = 1
    db.addIncubator.return_value = 1
    db.deleteIncubator.return_value = 1
    server.database = db

    server.results_dir = "/tmp/results"
    server.sensors_dir = "/tmp/sensors"
    server.roi_templates_dir = "/tmp/templates"
    server.tmp_imgs_dir = "/tmp/imgs"
    server.videos_dir = "/tmp/videos"
    return server


class TestIncubatorAPI(unittest.TestCase):
    def setUp(self):
        self.mock_server = _make_mock_server()
        self.api = IncubatorAPI(self.mock_server)

    def test_register_routes(self):
        """Phase 1 endpoints + Phase 2 push-schedule / telemetry are registered."""
        route_calls = []

        def mock_route(path, method):
            def decorator(func):
                route_calls.append((path, method))
                return func

            return decorator

        self.api.app.route = mock_route
        self.api.register_routes()

        paths = {c[0] for c in route_calls}
        self.assertIn("/incubators/live", paths)
        self.assertIn("/incubators/merged", paths)
        self.assertIn("/incubator/bind", paths)
        self.assertIn("/incubator/push-schedule", paths)
        self.assertIn("/incubator/<name>/telemetry", paths)

    def test_get_live_returns_scanner_info(self):
        self.api.incubator_scanner.get_all_devices_info.return_value = {
            "incubator-1": {"hostname": "incubator-1", "temperature": 22.0}
        }
        # Recreate routes so the scanner mock change is picked up.
        self.api = IncubatorAPI(self.mock_server)
        result = self.api._get_incubators_live()
        self.assertIn("incubator-1", result)

    def test_get_live_no_scanner(self):
        self.mock_server.incubator_scanner = None
        api = IncubatorAPI(self.mock_server)
        self.assertEqual(api._get_incubators_live(), {})

    def test_merged_joins_on_hostname(self):
        scanner = self.mock_server.incubator_scanner
        scanner.get_all_devices_info.return_value = {
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
        self.mock_server.database.getAllIncubators.return_value = {
            "Incubator 1": {
                "name": "Incubator 1",
                "hostname": "incubator-1",
                "active": 1,
            },
            "Spare": {"name": "Spare", "hostname": None, "active": 1},
        }
        api = IncubatorAPI(self.mock_server)
        merged = api._get_incubators_merged()

        self.assertEqual(merged["Incubator 1"]["source"], "both")
        self.assertEqual(merged["Incubator 1"]["temperature"], 22.5)
        self.assertEqual(merged["Incubator 1"]["live_status"], "online")
        self.assertEqual(merged["Spare"]["source"], "configured")
        self.assertEqual(merged["Spare"]["live_status"], "unbound")
        self.assertIn("incubator-9", merged)
        self.assertEqual(merged["incubator-9"]["source"], "discovered")

    def test_bind_updates_db_and_pushes_location(self):
        # Configure a live unit at incubator-1 so the route pushes the location.
        scanner = self.mock_server.incubator_scanner
        device = Mock()
        device.ip.return_value = "10.0.0.1"
        device._port = 80
        scanner.get_device_by_hostname.return_value = device
        scanner.set_location.return_value = {"status": "ok"}
        scanner.get_all_devices_info.return_value = {
            "incubator-1": {
                "hostname": "incubator-1",
                "ip": "10.0.0.1",
                "status": "online",
            }
        }
        # DB record exists so route.bind() can look it up.
        self.mock_server.database.getIncubatorByName.return_value = {
            "id": 1,
            "name": "Incubator 1",
            "hostname": None,
        }
        api = IncubatorAPI(self.mock_server)
        api.get_request_json = Mock(
            return_value={"name": "Incubator 1", "hostname": "incubator-1"}
        )

        result = api._bind_incubator()

        self.assertEqual(result["result"], "success")
        self.assertTrue(result["location_pushed"])
        # Binding a physical unit also promotes the record to the 'smart' category.
        self.mock_server.database.updateIncubator.assert_called_with(
            name="Incubator 1",
            incubator_id=None,
            hostname="incubator-1",
            type="smart",
            parent="",
        )
        # The unit's sensor name + location mirror the incubator name.
        scanner.set_identity.assert_called_once_with(
            "incubator-1", name="Incubator 1", location="Incubator 1"
        )

    def test_bind_requires_name(self):
        api = IncubatorAPI(self.mock_server)
        api.get_request_json = Mock(return_value={"hostname": "incubator-1"})
        result = api._bind_incubator()
        self.assertEqual(result["result"], "error")
        self.mock_server.database.updateIncubator.assert_not_called()

    def test_unbind_with_null_hostname(self):
        scanner = self.mock_server.incubator_scanner
        self.mock_server.database.getIncubatorByName.return_value = {
            "id": 1,
            "name": "Incubator 1",
            "hostname": "incubator-1",
        }
        api = IncubatorAPI(self.mock_server)
        api.get_request_json = Mock(
            return_value={"name": "Incubator 1", "hostname": None}
        )

        result = api._bind_incubator()

        self.assertEqual(result["result"], "success")
        self.assertFalse(result["location_pushed"])
        # Unbinding reverts the record to a plain manual 'normal' incubator.
        self.mock_server.database.updateIncubator.assert_called_with(
            name="Incubator 1",
            incubator_id=None,
            hostname=None,
            type="normal",
            parent="",
        )
        scanner.set_location.assert_not_called()

    def test_push_schedule_endpoint(self):
        """``POST /incubator/push-schedule`` looks up the record and pushes."""
        scanner = self.mock_server.incubator_scanner
        device = Mock()
        device.ip.return_value = "10.0.0.1"
        device._port = 80
        scanner.get_device_by_hostname.return_value = device
        self.mock_server.database.getIncubatorByName.return_value = {
            "id": 1,
            "name": "Incubator 1",
            "hostname": "incubator-1",
            "lights_on": "09:00",
            "lights_off": "21:00",
        }
        api = IncubatorAPI(self.mock_server)
        api.get_request_json = Mock(return_value={"name": "Incubator 1"})

        with patch(
            "ethoscope_node.incubators.routes.IncubatorRoutes._maybe_push",
            return_value=True,
        ):
            result = api._push_schedule()

        self.assertEqual(result["result"], "success")

    def test_push_schedule_requires_name(self):
        api = IncubatorAPI(self.mock_server)
        api.get_request_json = Mock(return_value={})
        result = api._push_schedule()
        self.assertEqual(result["result"], "error")

    def test_push_schedule_to_unit_helper(self):
        """The helper consumed by setup_api delegates to _maybe_push."""
        api = IncubatorAPI(self.mock_server)
        with patch(
            "ethoscope_node.incubators.routes.IncubatorRoutes._maybe_push",
            return_value=True,
        ) as m:
            assert api.push_schedule_to_unit("Inc1") is True
            m.assert_called_once_with("Inc1")


if __name__ == "__main__":
    unittest.main()
