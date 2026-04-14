import csv
import datetime
import json
import os
import time
import urllib.parse
import urllib.request
from threading import RLock
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from ethoscope_node.scanner.base_scanner import BaseDevice, DeviceScanner, ScanException

if TYPE_CHECKING:
    from ethoscope_node.notifications.temperature_monitor import TemperatureAlertMonitor
    from ethoscope_node.utils.configuration import EthoscopeConfiguration


class Sensor(BaseDevice):
    """Enhanced sensor device class with improved CSV handling."""

    SENSOR_FIELDS = ["Time", "Temperature", "Humidity", "Pressure", "Light"]

    def __init__(
        self,
        ip: str,
        port: int = 80,
        refresh_period: float = 5,
        results_dir: str = "/ethoscope_data/sensors",
        save_to_csv: bool = True,
        temperature_callback: Optional[Callable[[str, str, str, float], None]] = None,
    ):
        """
        Initialize sensor device.

        Args:
            ip: Sensor IP address
            port: Sensor port
            refresh_period: How often to poll sensor data (seconds)
            results_dir: Directory for CSV data storage
            save_to_csv: Whether to save data to CSV files
            temperature_callback: Optional callback for temperature monitoring.
                Called with (sensor_id, sensor_name, location, temperature)
        """
        self.save_to_csv = save_to_csv
        self._csv_lock = RLock()
        self._temperature_callback = temperature_callback

        super().__init__(ip, port, refresh_period, results_dir)

        # Set CSV path for this sensor and ensure CSV directory exists before calling parent
        self.CSV_PATH = results_dir
        if save_to_csv:
            os.makedirs(self.CSV_PATH, exist_ok=True)

    def _setup_urls(self):
        """Setup sensor-specific URLs."""
        self._data_url = f"http://{self._ip}:{self._port}/"
        self._id_url = f"http://{self._ip}:{self._port}/id"
        self._post_url = f"http://{self._ip}:{self._port}/set"

    def set(self, post_data: Dict[str, Any], use_json: bool = False) -> Any:
        """
        Set remote sensor variables.

        Args:
            post_data: Dictionary of key-value pairs to set
            use_json: Whether to send data as JSON

        Returns:
            Response from sensor
        """
        try:
            if use_json:
                data = json.dumps(post_data).encode("utf-8")
                return self._get_json(self._post_url, post_data=data)
            else:
                data = urllib.parse.urlencode(post_data).encode("utf-8")
                req = urllib.request.Request(self._post_url, data=data)

                with urllib.request.urlopen(req, timeout=self._timeout) as response:
                    result = response.read()

                self._update_info()
                return result

        except Exception as e:
            self._logger.error(f"Error setting sensor variables: {e}")
            raise

    def set_temperature_callback(
        self, callback: Optional[Callable[[str, str, str, float], None]]
    ) -> None:
        """
        Set the temperature monitoring callback.

        Args:
            callback: Function to call with (sensor_id, sensor_name, location, temperature)
        """
        self._temperature_callback = callback

    def _update_info(self):
        """Update sensor information and save to CSV if enabled."""
        try:
            self._update_id()

            # Get sensor data
            resp = self._get_json(self._data_url)

            with self._lock:
                self._info.update(resp)
                self._update_device_status("online", trigger_source="system")
                self._info["last_seen"] = time.time()

            # Save to CSV if enabled
            if self.save_to_csv:
                self._save_to_csv()

            # Check temperature thresholds if callback is set
            if self._temperature_callback:
                self._check_temperature()

        except ScanException:
            self._reset_info()
        except Exception as e:
            self._logger.error(f"Error updating sensor info: {e}")
            self._reset_info()

    def _check_temperature(self) -> None:
        """Check temperature against thresholds and trigger callback if needed."""
        if not self._temperature_callback:
            return

        try:
            with self._lock:
                temperature = self._info.get("temperature")
                if temperature is None:
                    return

                # Convert to float if needed
                try:
                    temp_float = float(temperature)
                except (ValueError, TypeError):
                    self._logger.warning(f"Invalid temperature value: {temperature}")
                    return

                sensor_id = self._info.get("id", self._id or "unknown")
                sensor_name = self._info.get("name", "Unknown Sensor")
                location = self._info.get("location", "Unknown")

            # Call the temperature callback (outside lock to avoid deadlocks)
            self._temperature_callback(sensor_id, sensor_name, location, temp_float)

        except Exception as e:
            self._logger.error(f"Error checking temperature: {e}")

    def _save_to_csv(self):
        """Save sensor data to CSV file with thread safety."""
        try:
            with self._csv_lock:
                # Extract sensor data
                sensor_data = self._extract_sensor_data()
                filename = self._get_csv_filename(sensor_data["name"])

                # Check if file exists
                file_exists = os.path.isfile(filename)

                with open(filename, mode="a", newline="", encoding="utf-8") as csvfile:
                    writer = csv.writer(csvfile)

                    # Write header if new file
                    if not file_exists:
                        self._write_csv_header(csvfile, sensor_data)
                        writer.writerow(self.SENSOR_FIELDS)

                    # Write data row
                    current_time = datetime.datetime.now(
                        tz=datetime.timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    writer.writerow(
                        [
                            current_time,
                            sensor_data.get("temperature", "N/A"),
                            sensor_data.get("humidity", "N/A"),
                            sensor_data.get("pressure", "N/A"),
                            sensor_data.get("light", "N/A"),
                        ]
                    )

        except Exception as e:
            self._logger.error(f"Error saving to CSV: {e}")

    def _extract_sensor_data(self) -> Dict[str, Any]:
        """Extract sensor data from info dictionary."""
        with self._lock:
            return {
                "id": self._info.get("id", "unknown_id"),
                "ip": self._info.get("ip", "unknown_ip"),
                "name": self._info.get("name", "unknown_sensor"),
                "location": self._info.get("location", "unknown_location"),
                "temperature": self._info.get("temperature", "N/A"),
                "humidity": self._info.get("humidity", "N/A"),
                "pressure": self._info.get("pressure", "N/A"),
                "light": self._info.get("light", "N/A"),
            }

    def _get_csv_filename(self, sensor_name: str) -> str:
        """Get CSV filename for sensor."""
        safe_name = "".join(c for c in sensor_name if c.isalnum() or c in "_-")
        return os.path.join(self.CSV_PATH, f"{safe_name}.csv")

    def _write_csv_header(self, csvfile, sensor_data: Dict[str, Any]):
        """Write CSV metadata header."""
        header = (
            f"# Sensor ID: {sensor_data['id']}\n"
            f"# IP: {sensor_data['ip']}\n"
            f"# Name: {sensor_data['name']}\n"
            f"# Location: {sensor_data['location']}\n"
        )
        csvfile.write(header)


class SensorScanner(DeviceScanner):
    """Sensor-specific scanner with temperature alert monitoring."""

    SERVICE_TYPE = "_sensor._tcp.local."
    DEVICE_TYPE = "sensor"

    def __init__(
        self,
        results_dir: str = "/ethoscope_data/sensors",
        device_refresh_period: float = 300,
        device_class=Sensor,
        config: Optional["EthoscopeConfiguration"] = None,
    ):
        """
        Initialize sensor scanner with optional temperature monitoring.

        Args:
            results_dir: Directory for sensor data CSV files
            device_refresh_period: How often to poll sensors (seconds)
            device_class: Device class to use for sensors
            config: Configuration instance for temperature alert settings
        """
        super().__init__(device_refresh_period, device_class)
        self.results_dir = results_dir

        # Initialize temperature alert monitoring
        self._config = config
        self._temperature_monitor: Optional[TemperatureAlertMonitor] = None

        # Lazily initialize temperature monitor when config is available
        if self._config:
            self._init_temperature_monitor()

    def _init_temperature_monitor(self) -> None:
        """Initialize the temperature alert monitor."""
        try:
            from ethoscope_node.notifications.temperature_monitor import (
                TemperatureAlertMonitor,
            )

            self._temperature_monitor = TemperatureAlertMonitor(self._config)
            self._logger.info("Temperature alert monitor initialized")

            # Retroactively attach callback to sensors discovered before init.
            # Reason: device discovery can race ahead of monitor construction.
            callback = self._get_temperature_callback()
            if callback:
                with self._lock:
                    for device in self.devices:
                        if hasattr(device, "set_temperature_callback"):
                            device.set_temperature_callback(callback)
        except Exception as e:
            self._logger.error(f"Failed to initialize temperature monitor: {e}")
            self._temperature_monitor = None

    def _get_temperature_callback(self):
        """
        Get the temperature callback function for sensors.

        Returns:
            Callback function or None if monitoring is not enabled
        """
        if self._temperature_monitor is None:
            return None

        def callback(
            sensor_id: str, sensor_name: str, location: str, temperature: float
        ):
            """Check temperature and send alert if needed."""
            self._temperature_monitor.check_temperature(
                sensor_id=sensor_id,
                sensor_name=sensor_name,
                location=location,
                temperature=temperature,
            )

        return callback

    def add(
        self,
        ip: str,
        port: int,
        name: Optional[str] = None,
        device_id: Optional[str] = None,
        zcinfo: Optional[Dict] = None,
    ):
        """Add a sensor device and attach the temperature callback if present.

        Overrides DeviceScanner.add() — the actual entry point used by both
        direct adds and zeroconf service discovery — so newly-created sensors
        receive the temperature monitoring callback.
        """
        devices_before_ids = {id(d) for d in self.devices}
        super().add(ip, port, name, device_id, zcinfo)

        callback = self._get_temperature_callback()
        if callback is None:
            return

        with self._lock:
            for device in self.devices:
                if id(device) in devices_before_ids:
                    continue
                if hasattr(device, "set_temperature_callback"):
                    device.set_temperature_callback(callback)
                    self._logger.debug(
                        f"Temperature monitoring enabled for sensor: {name or device_id}"
                    )

    def get_temperature_alert_states(self) -> Dict[str, Any]:
        """
        Get temperature alert states for all sensors.

        Returns:
            Dictionary mapping sensor_id to alert state info
        """
        if self._temperature_monitor:
            return self._temperature_monitor.get_all_alert_states()
        return {}

    def reset_temperature_alert_state(self, sensor_id: str) -> None:
        """
        Reset temperature alert state for a specific sensor.

        Args:
            sensor_id: Sensor ID to reset
        """
        if self._temperature_monitor:
            self._temperature_monitor.reset_alert_state(sensor_id)
