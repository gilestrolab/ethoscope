"""mDNS discovery + telemetry polling for smart incubator units.

Self-contained: no imports from the rest of ``ethoscope_node``. The minimal
``_BaseDevice`` / ``_DeviceScanner`` slice below is a deliberately pared-down
duplication of ``ethoscope_node.scanner.base_scanner`` — same policy as
``ethoscope_node/utils/video_helpers.py``. We do NOT inherit from the upstream
base scanner because doing so would pull in netifaces-filtered interface
discovery, the ethoscope-specific zeroconf re-anchor logic, and dependencies
we want to keep out of the minimal install.

What we keep:
- Thread-per-device polling with a ``refresh_period`` cadence
- Online/offline status with timestamp
- ``_get_json(url, post_data=None)`` via stdlib ``urllib.request`` (same call
  shape the existing Phase 1 tests assert against)
- Zeroconf ``ServiceBrowser`` discovery (``add_service`` / ``remove_service``
  / ``update_service`` callbacks)
- Public surface used by the node bridge: ``info()``, ``ip()``, ``id()``,
  ``set_location()``, ``get_device_by_hostname()``, ``get_all_devices_info()``

What we drop:
- netifaces-based interface filtering (zeroconf default is fine for the
  single-purpose standalone server; full node still uses its richer scanner
  elsewhere)
- Retry decorator (one failed poll → offline; recover on next success)
- ``zeroconf_name`` re-anchoring across DHCP IP changes
- ``config_dir`` constructor inspection
"""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from threading import RLock, Thread
from typing import Any

from zeroconf import IPVersion, ServiceBrowser, Zeroconf

DEFAULT_TIMEOUT_S = 5.0
DEFAULT_REFRESH_PERIOD_S = 60.0  # match firmware report_interval
INCUBATOR_PORT = 80


class ScanException(Exception):
    """Raised when a device-side HTTP poll fails. Caught by ``_update_info``."""


class _DeviceStatus:
    """Tiny status snapshot — string + timestamp, no behavior."""

    __slots__ = ("status_name", "timestamp")

    def __init__(self, status_name: str) -> None:
        self.status_name = status_name
        self.timestamp = time.time()


class _BaseDevice(Thread):
    """Polling-thread skeleton shared by ``Incubator`` and any future device class."""

    def __init__(
        self,
        ip: str,
        port: int = INCUBATOR_PORT,
        refresh_period: float = DEFAULT_REFRESH_PERIOD_S,
        results_dir: str = "",
        timeout: float = DEFAULT_TIMEOUT_S,
    ):
        super().__init__(daemon=True)
        self._ip = ip
        self._port = port
        self._refresh_period = refresh_period
        self._results_dir = results_dir
        self._timeout = timeout

        self._device_status = _DeviceStatus("offline")
        self._info: dict[str, Any] = {"ip": ip}
        self._id = ""
        self._is_online = True
        self._lock = RLock()
        self._last_refresh = 0.0

        self._logger = logging.getLogger(f"{self.__class__.__name__}_{ip}")
        if self._logger.level == logging.NOTSET:
            self._logger.setLevel(logging.getLogger().level or logging.INFO)

        self._setup_urls()
        self._reset_info()

    # --- overridable hooks -------------------------------------------------------

    def _setup_urls(self) -> None:
        self._data_url = f"http://{self._ip}:{self._port}/"
        self._id_url = f"http://{self._ip}:{self._port}/id"

    def _update_info(self) -> None:
        """Default: fetch ``self._data_url`` and merge into ``_info``."""
        try:
            resp = self._get_json(self._data_url)
        except ScanException:
            self._reset_info()
            return
        with self._lock:
            self._info.update(resp)
            self._info["ip"] = self._ip
            self._update_device_status("online")
            self._info["last_seen"] = time.time()

    # --- HTTP helper -------------------------------------------------------------

    def _get_json(
        self,
        url: str,
        timeout: float | None = None,
        post_data: bytes | None = None,
    ) -> dict[str, Any]:
        """Fetch JSON via stdlib urllib. Raises :class:`ScanException` on any failure.

        The signature matches the upstream BaseDevice so existing call-sites
        (notably ``set_location``) work unchanged.
        """
        timeout = timeout or self._timeout
        try:
            req = urllib.request.Request(
                url,
                data=post_data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "EthoscopeIncubatorNode/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                message = response.read()
            if not message:
                raise ScanException(f"Empty response from {url}")
            try:
                return json.loads(message)
            except json.JSONDecodeError as e:
                raise ScanException(f"Invalid JSON from {url}: {e}") from e
        except urllib.error.HTTPError as e:
            raise ScanException(f"HTTP {e.code} error from {url}") from e
        except urllib.error.URLError as e:
            raise ScanException(f"URL error from {url}: {e.reason}") from e
        except TimeoutError as e:
            raise ScanException(f"Timeout connecting to {url}") from e
        except Exception as e:
            # Catch-all so polling-loop never crashes on transient errors
            # (e.g. raw OSError from socket layer).
            raise ScanException(f"Unexpected error from {url}: {e}") from e

    # --- status / info -----------------------------------------------------------

    def _update_device_status(self, status_name: str) -> None:
        with self._lock:
            previous = self._device_status.status_name
            self._device_status = _DeviceStatus(status_name)
            self._info["last_seen"] = time.time()
            if previous != status_name:
                self._logger.info("Status changed: %s -> %s", previous, status_name)

    def _reset_info(self) -> None:
        """Mark offline while preserving identifying fields."""
        with self._lock:
            preserved_name = self._info.get("name", "")
            preserved_id = self._info.get("id", self._id)
            preserved_hostname = self._info.get("hostname", "")
            self._update_device_status("offline")
            base = {
                "ip": self._ip,
                "last_seen": time.time(),
            }
            if preserved_name:
                base["name"] = preserved_name
            if preserved_id:
                base["id"] = preserved_id
            if preserved_hostname:
                base["hostname"] = preserved_hostname
            self._info.update(base)

    # --- thread loop -------------------------------------------------------------

    def run(self) -> None:
        while self._is_online:
            time.sleep(0.2)
            now = time.time()
            if now - self._last_refresh > self._refresh_period:
                try:
                    self._update_info()
                except Exception as e:
                    self._logger.warning("Polling error: %s", e)
                    self._reset_info()
                self._last_refresh = now

    def stop(self) -> None:
        self._is_online = False

    # --- public surface ----------------------------------------------------------

    def ip(self) -> str:
        return self._ip

    def id(self) -> str:
        with self._lock:
            return self._id

    def info(self) -> dict[str, Any]:
        with self._lock:
            snap = dict(self._info)
            snap["status"] = self._device_status.status_name
            return snap


class Incubator(_BaseDevice):
    """A WiFi smart-incubator unit polled over its ``/telemetry`` endpoint.

    The unit reports ``node_id`` in ``/telemetry`` rather than a top-level
    ``id`` field, so we derive a stable hostname ``incubator-<node_id>`` from
    it. That hostname is what the node DB ``hostname`` column binds against
    and what ``get_device_by_hostname()`` keys on.
    """

    def __init__(
        self,
        ip: str,
        port: int = INCUBATOR_PORT,
        refresh_period: float = DEFAULT_REFRESH_PERIOD_S,
        results_dir: str = "",
    ):
        super().__init__(ip, port, refresh_period, results_dir)

    def _setup_urls(self) -> None:
        self._data_url = f"http://{self._ip}:{self._port}/telemetry"
        self._health_url = f"http://{self._ip}:{self._port}/health"
        # /telemetry carries the identity (node_id); point _id_url at it too.
        self._id_url = self._data_url

    def _update_info(self) -> None:
        try:
            resp = self._get_json(self._data_url)
        except ScanException:
            self._reset_info()
            return
        except Exception as e:
            self._logger.error("Error updating incubator info: %s", e)
            self._reset_info()
            return

        node_id = resp.get("node_id")
        hostname = (
            f"incubator-{node_id}" if node_id is not None else (self._id or self._ip)
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


class _DeviceScanner:
    """Minimal Zeroconf-driven device scanner.

    Subclasses set ``SERVICE_TYPE`` and pass a ``device_class``. Discovered
    devices are appended to ``self.devices``; addresses are not re-anchored
    on DHCP changes (recreated on next discovery instead).
    """

    SERVICE_TYPE = "_device._tcp.local."
    DEVICE_TYPE = "device"

    def __init__(
        self,
        device_refresh_period: float = DEFAULT_REFRESH_PERIOD_S,
        device_class: type = _BaseDevice,
    ):
        self._zeroconf: Zeroconf | None = None
        self._browser: ServiceBrowser | None = None
        self.devices: list[_BaseDevice] = []
        self.device_refresh_period = device_refresh_period
        self._device_class = device_class
        self._lock = RLock()
        self._is_running = False
        self._logger = logging.getLogger(self.__class__.__name__)
        if self._logger.level == logging.NOTSET:
            self._logger.setLevel(logging.getLogger().level or logging.INFO)
        self.results_dir = ""

    def start(self) -> None:
        if self._is_running:
            self._logger.warning("Scanner already running")
            return
        try:
            self._zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
            self._browser = ServiceBrowser(self._zeroconf, self.SERVICE_TYPE, self)
            self._is_running = True
            self._logger.info("Started %s scanner", self.DEVICE_TYPE)
        except Exception as e:
            self._logger.error("Error starting scanner: %s", e)
            self._cleanup_zeroconf()
            raise

    def stop(self) -> None:
        if not self._is_running:
            return
        self._is_running = False
        with self._lock:
            for device in self.devices:
                try:
                    device.stop()
                except Exception as e:
                    self._logger.warning("Error stopping device %s: %s", device.ip(), e)
        self._cleanup_zeroconf()
        self._logger.info("Stopped %s scanner", self.DEVICE_TYPE)

    def _cleanup_zeroconf(self) -> None:
        try:
            if self._browser is not None:
                self._browser.cancel()
                self._browser = None
            if self._zeroconf is not None:
                self._zeroconf.close()
                self._zeroconf = None
        except Exception as e:
            self._logger.warning("Error during zeroconf cleanup: %s", e)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def __del__(self):
        try:
            self.stop()
        except Exception:
            pass

    def add(self, ip: str, port: int, name: str | None = None) -> None:
        if not self._is_running:
            self._logger.warning("Cannot add %s:%d - scanner not running", ip, port)
            return
        with self._lock:
            for existing in self.devices:
                if existing.ip() == ip:
                    self._logger.info(
                        "Device at %s already present, refreshing status", ip
                    )
                    existing._update_device_status("offline")
                    existing._info["last_seen"] = time.time()
                    return
            device = self._device_class(
                ip=ip,
                port=port,
                refresh_period=self.device_refresh_period,
                results_dir=self.results_dir,
            )
            device.start()
            self.devices.append(device)
            self._logger.info("Added %s %s at %s:%d", self.DEVICE_TYPE, name, ip, port)

    def add_service(self, zeroconf, service_type: str, name: str) -> None:
        if not self._is_running:
            return
        try:
            info = zeroconf.get_service_info(service_type, name)
            if info and info.addresses:
                ip = socket.inet_ntoa(info.addresses[0])
                self.add(ip, info.port, name)
        except Exception as e:
            self._logger.error("Error adding zeroconf service %s: %s", name, e)

    def remove_service(self, zeroconf, service_type: str, name: str) -> None:
        if not self._is_running:
            return
        try:
            info = zeroconf.get_service_info(service_type, name)
            if not info or not info.addresses:
                return
            ip = socket.inet_ntoa(info.addresses[0])
            with self._lock:
                for device in self.devices:
                    if device.ip() == ip:
                        self._logger.info(
                            "%s at %s went offline (zeroconf removal)",
                            self.DEVICE_TYPE,
                            ip,
                        )
                        device._update_device_status("offline")
                        break
        except Exception as e:
            self._logger.error("Error removing zeroconf service %s: %s", name, e)

    def update_service(self, zeroconf, service_type: str, name: str) -> None:
        # Simplest valid behaviour: rediscover. Phase 1 didn't need IP
        # re-anchoring for incubators and we keep it that way.
        self.add_service(zeroconf, service_type, name)

    def get_all_devices_info(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {d.id(): d.info() for d in self.devices if d.id()}


class IncubatorScanner(_DeviceScanner):
    """Discovers smart incubators via ``_incubator._tcp`` and polls their telemetry."""

    SERVICE_TYPE = "_incubator._tcp.local."
    DEVICE_TYPE = "incubator"

    def __init__(
        self,
        results_dir: str = "",
        device_refresh_period: float = DEFAULT_REFRESH_PERIOD_S,
        device_class: type = Incubator,
    ):
        super().__init__(device_refresh_period, device_class)
        self.results_dir = results_dir

    def get_device_by_hostname(self, hostname: str) -> Incubator | None:
        with self._lock:
            for device in self.devices:
                if device.info().get("hostname") == hostname:
                    return device  # type: ignore[return-value]
        return None

    def set_identity(
        self,
        hostname: str,
        *,
        name: str | None = None,
        location: str | None = None,
    ) -> dict[str, Any]:
        """Push sensor ``name`` / ``location`` to a discovered incubator via ``POST /set``.

        Only the provided fields are sent. Returns the firmware's JSON response.
        Raises ``ValueError`` when no online unit with that hostname is known.
        """
        device = self.get_device_by_hostname(hostname)
        if device is None:
            raise ValueError(f"No live incubator found for hostname '{hostname}'")

        payload: dict[str, str] = {}
        if name is not None:
            payload["name"] = name
        if location is not None:
            payload["location"] = location

        url = f"http://{device.ip()}:{device._port}/set"
        data = json.dumps(payload).encode("utf-8")
        return device._get_json(url, post_data=data)

    def set_location(self, hostname: str, location: str) -> dict[str, Any]:
        """Backwards-compatible wrapper: push only the sensor ``location``."""
        return self.set_identity(hostname, location=location)
