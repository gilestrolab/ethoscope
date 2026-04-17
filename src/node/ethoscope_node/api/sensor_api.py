"""
Sensor API Module

Handles sensor management including discovery, configuration, and data visualization.
"""

import json
import os

from .base import BaseAPI, error_decorator


class SensorAPI(BaseAPI):
    """API endpoints for sensor management and data."""

    def register_routes(self):
        """Register sensor-related routes."""
        self.app.route("/sensors", method="GET")(self._get_sensors)
        self.app.route("/sensors/merged", method="GET")(self._get_sensors_merged)
        self.app.route("/sensor/set", method="POST")(self._edit_sensor)
        self.app.route("/list_sensor_csv_files", method="GET")(self._list_csv_files)
        self.app.route("/get_sensor_csv_data/<filename>", method="GET")(
            self._get_csv_data
        )

    @error_decorator
    def _get_sensors(self):
        """Get all sensor information."""
        return self.sensor_scanner.get_all_devices_info() if self.sensor_scanner else {}

    @error_decorator
    def _get_sensors_merged(self):
        """Get merged view of discovered and configured sensors.

        Combines live discovered sensors (from mDNS) with configured sensors
        (from ethoscope.conf). Reconciles by matching sensor name.
        Each sensor gets a 'source' field: 'discovered', 'configured', or 'both'.
        """
        # Get discovered sensors (keyed by MAC-based ID)
        discovered = {}
        if self.sensor_scanner:
            discovered = self.sensor_scanner.get_all_devices_info() or {}

        # Get configured sensors (keyed by name)
        configured = self.config.get_all_sensors() if self.config else {}

        # Get global alert config for reference
        global_alerts = (
            self.config.get_temperature_alert_config() if self.config else {}
        )

        # Build name-indexed map of discovered sensors
        discovered_by_name = {}
        for dev_id, dev_info in discovered.items():
            name = dev_info.get("name", "")
            if name:
                discovered_by_name[name] = {**dev_info, "_discovered_id": dev_id}

        merged = {}

        # Add all configured sensors first
        for name, cfg in configured.items():
            entry = dict(cfg)
            if name in discovered_by_name:
                # Merge live data from discovered sensor
                live = discovered_by_name.pop(name)
                entry.update(
                    {
                        "id": live.get("_discovered_id", ""),
                        "ip": live.get("ip", ""),
                        "status": live.get("status", "offline"),
                        "temperature": live.get("temperature", ""),
                        "humidity": live.get("humidity", ""),
                        "pressure": live.get("pressure", ""),
                        "light": live.get("light", ""),
                        "last_seen": live.get("last_seen", ""),
                        "source": "both",
                    }
                )
            else:
                entry.update(
                    {
                        "status": "configured",
                        "source": "configured",
                    }
                )
            entry["global_alerts"] = global_alerts
            merged[name] = entry

        # Add remaining discovered-only sensors
        for name, live in discovered_by_name.items():
            entry = {
                "name": name,
                "id": live.get("_discovered_id", ""),
                "ip": live.get("ip", ""),
                "URL": f"http://{live.get('ip', '')}",
                "location": live.get("location", ""),
                "description": "",
                "active": True,
                "status": live.get("status", "online"),
                "temperature": live.get("temperature", ""),
                "humidity": live.get("humidity", ""),
                "pressure": live.get("pressure", ""),
                "light": live.get("light", ""),
                "last_seen": live.get("last_seen", ""),
                "source": "discovered",
                "global_alerts": global_alerts,
            }
            merged[name] = entry

        return merged

    def _edit_sensor(self):
        """Edit sensor settings."""
        input_string = self.get_request_data().decode("utf-8")

        # Use json.loads instead of eval for security
        try:
            data = json.loads(input_string)
        except json.JSONDecodeError:
            # Fallback for malformed JSON - but this is risky
            try:
                data = eval(input_string)  # This should eventually be removed
            except Exception:
                return {"error": "Invalid data format"}

        if self.sensor_scanner:
            try:
                sensor = self.sensor_scanner.get_device(data["id"])
                if sensor:
                    return sensor.set(
                        {"location": data["location"], "sensor_name": data["name"]}
                    )
            except Exception as e:
                return {"error": f"Sensor operation failed: {str(e)}"}

        return {"error": "Sensor not found"}

    @error_decorator
    def _list_csv_files(self):
        """List CSV files in sensors directory."""
        directory = self.sensors_dir
        try:
            if directory and os.path.exists(directory):
                csv_files = [f for f in os.listdir(directory) if f.endswith(".csv")]
                return {"files": csv_files}
        except Exception:
            pass
        return {"files": []}

    @error_decorator
    def _get_csv_data(self, filename):
        """Read CSV file and return data for plotting."""
        directory = self.sensors_dir
        filepath = os.path.join(directory, filename)

        data = []
        with open(filepath) as csvfile:
            headers = csvfile.readline().strip().split(",")
            for line in csvfile:
                data.append(line.strip().split(","))

        return {"headers": headers, "data": data}
