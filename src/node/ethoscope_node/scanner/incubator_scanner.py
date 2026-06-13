"""Discovery and monitoring of WiFi smart incubators.

Smart incubators expose an HTTP REST API (``/telemetry``, ``/config``, ``/command``,
``/health``) and advertise the mDNS service ``_incubator._tcp``. This scanner mirrors the
sensor/ethoscope scanner pattern: each unit runs on its own polling thread and liveness is
inferred from poll success/timeout.

The *same* physical unit is also discovered independently by :class:`SensorScanner` — the
firmware serves the ethoscope sensor API (``GET /``, ``/id``, ``POST /set``) on the same
port and advertises ``_sensor._tcp`` too. That channel handles CSV logging and temperature
alerts, so this class only deals with the incubator-specific telemetry (setpoints, light
schedule, Peltier state). Phase 1 is monitor-only — no setpoints are pushed from the node.
"""

import time
from typing import Any

from ethoscope_node.scanner.base_scanner import BaseDevice, DeviceScanner, ScanException

INCUBATOR_PORT = 80


class Incubator(BaseDevice):
    """A WiFi smart incubator polled over its ``/telemetry`` endpoint."""

    def __init__(
        self,
        ip: str,
        port: int = INCUBATOR_PORT,
        refresh_period: float = 60,
        results_dir: str = "",
    ):
        super().__init__(ip, port, refresh_period, results_dir)

    def _setup_urls(self):
        """Set up incubator-specific URLs."""
        self._data_url = f"http://{self._ip}:{self._port}/telemetry"
        self._health_url = f"http://{self._ip}:{self._port}/health"
        # /telemetry carries the identity (node_id), so the base _update_id() path is not
        # used; point _id_url at it anyway so any base lookup still resolves.
        self._id_url = self._data_url

    def _update_info(self):
        """Poll ``/telemetry`` and store it, keyed by a stable ``incubator-<id>`` hostname.

        ``/telemetry`` has no ``id`` field (it reports ``node_id``), so unlike the base
        class we derive a stable id/hostname from ``node_id`` — this is what the node DB
        binds against and what ``get_all_devices_info()`` keys on.
        """
        try:
            resp = self._get_json(self._data_url)

            node_id = resp.get("node_id")
            hostname = (
                f"incubator-{node_id}"
                if node_id is not None
                else (self._id or self._ip)
            )

            with self._lock:
                self._info.update(resp)
                self._info["ip"] = self._ip
                self._info["hostname"] = hostname
                self._info["id"] = hostname
                self._info.setdefault("name", hostname)
                self._id = hostname
                self._update_device_status("online")
                self._info["last_seen"] = time.time()

        except ScanException:
            self._reset_info()
        except Exception as e:
            self._logger.error(f"Error updating incubator info: {e}")
            self._reset_info()


class IncubatorScanner(DeviceScanner):
    """Discovers smart incubators via mDNS (``_incubator._tcp``) and polls their telemetry."""

    SERVICE_TYPE = "_incubator._tcp.local."
    DEVICE_TYPE = "incubator"

    def __init__(
        self,
        results_dir: str = "",
        device_refresh_period: float = 60,
        device_class=Incubator,
    ):
        """Initialize the incubator scanner.

        Args:
            results_dir: Directory for any incubator data files (unused in Phase 1).
            device_refresh_period: How often to poll each incubator (seconds). Defaults to
                60 s, matching the firmware's ``report_interval``.
            device_class: Device class to instantiate per discovered unit.
        """
        super().__init__(device_refresh_period, device_class)
        self.results_dir = results_dir

    def get_device_by_hostname(self, hostname: str) -> Incubator | None:
        """Return the live incubator whose derived hostname matches, or None."""
        with self._lock:
            for device in self.devices:
                if device.info().get("hostname") == hostname:
                    return device
        return None

    def set_location(self, hostname: str, location: str) -> dict[str, Any]:
        """Push a sensor ``location`` to a discovered incubator via its ``POST /set``.

        Keeps the unit's sensor-channel ``location`` equal to its bound incubator name so
        CSV/alerts/Sensors-page readings group under that incubator. Returns the device's
        JSON response.

        Raises:
            ValueError: if no online incubator with that hostname is known.
        """
        import json
        import urllib.request

        device = self.get_device_by_hostname(hostname)
        if device is None:
            raise ValueError(f"No live incubator found for hostname '{hostname}'")

        url = f"http://{device.ip()}:{device._port}/set"
        data = json.dumps({"location": location}).encode("utf-8")
        return device._get_json(url, post_data=data)
