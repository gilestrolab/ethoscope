import fcntl
import json
import logging
import socket
import struct
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import wraps
from threading import RLock, Thread
from typing import Any

import netifaces
from zeroconf import IPVersion, ServiceBrowser, Zeroconf

# ioctl request code for getting interface flags (SIOCGIFFLAGS)
_SIOCGIFFLAGS = 0x8913
_IFF_LOOPBACK = 0x0008
_IFF_MULTICAST = 0x1000


def _get_multicast_interfaces() -> list[str]:
    """Return IPv4 addresses of interfaces that support multicast.

    Filters out loopback and non-multicast interfaces (e.g. WireGuard/VPN
    tunnels) which cause errors when used with zeroconf.

    Returns:
        List of IPv4 address strings suitable for passing to Zeroconf(interfaces=...).
    """
    logger = logging.getLogger("ethoscope.scanner")
    result = []
    for iface in netifaces.interfaces():
        addrs = netifaces.ifaddresses(iface)
        if netifaces.AF_INET not in addrs:
            continue
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            flags_raw = fcntl.ioctl(
                sock, _SIOCGIFFLAGS, struct.pack("256s", iface.encode())
            )
            sock.close()
            flags = struct.unpack("H", flags_raw[16:18])[0]
        except OSError:
            continue
        if not (flags & _IFF_MULTICAST) or (flags & _IFF_LOOPBACK):
            continue
        for addr in addrs[netifaces.AF_INET]:
            result.append(addr["addr"])
    if result:
        logger.info(f"Zeroconf will use interfaces: {result}")
    else:
        logger.warning("No multicast-capable interfaces found, using all interfaces")
    return result


DEFAULT_TIMEOUT = 5
MAX_RETRIES = 2
INITIAL_RETRY_DELAY = 1
MAX_RETRY_DELAY = 5


@dataclass
class DeviceInfo:
    """Data class for device information."""

    ip: str
    port: int = 80
    status: str = "offline"
    name: str = ""
    id: str = ""
    last_seen: float | None = None


class DeviceStatus:
    """Per-device status snapshot.

    Reduced to what the UI and the polling cadence actually need: the status
    name, the timestamp it was set, and a "how long since" helper. Alert
    decisions, user-triggered classification, and chain walking — historically
    smeared across this class — have all moved to ``Ethoscope._reconcile_run_state``,
    which reasons about ``runs`` rows instead of in-memory state chains.
    """

    VALID_STATUSES = {
        "online",
        "offline",
        "running",
        "stopped",
        "unreached",
        "initialising",
        "stopping",
        "recording",
        "streaming",
        "busy",
    }

    ACTIVE_TRACKING_STATUSES = {"running", "recording", "streaming"}

    def __init__(self, status_name: str):
        if status_name not in self.VALID_STATUSES:
            raise ValueError(
                f"Invalid status: {status_name}. Must be one of: {self.VALID_STATUSES}"
            )
        self._status_name = status_name
        self._timestamp = time.time()

    @property
    def status_name(self) -> str:
        return self._status_name

    @property
    def timestamp(self) -> float:
        return self._timestamp

    def get_age_seconds(self) -> float:
        return time.time() - self._timestamp

    def get_age_minutes(self) -> float:
        return self.get_age_seconds() / 60

    def is_timeout_exceeded(self, timeout_minutes: int) -> bool:
        return self.get_age_minutes() > timeout_minutes

    def is_active_tracking(self) -> bool:
        return self._status_name in self.ACTIVE_TRACKING_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {"status_name": self._status_name, "timestamp": self._timestamp}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceStatus":
        status = cls(status_name=data["status_name"])
        status._timestamp = data.get("timestamp", time.time())
        return status

    def __str__(self) -> str:
        return f"DeviceStatus({self._status_name}, {self.get_age_minutes():.1f}m ago)"

    __repr__ = __str__


class ScanException(Exception):
    """Custom exception for scanning operations."""

    pass


class NetworkError(ScanException):
    """Network-related scanning error."""

    pass


class DeviceError(ScanException):
    """Device-specific error."""

    pass


def retry(
    exception_to_check,
    tries: int = MAX_RETRIES,
    delay: float = INITIAL_RETRY_DELAY,
    backoff: float = 1.5,
    max_delay: float = MAX_RETRY_DELAY,
    logger=None,
):
    """
    Retry decorator with exponential backoff and maximum delay cap.

    Args:
        exception_to_check: Exception type to catch and retry on
        tries: Maximum number of attempts
        delay: Initial delay between attempts
        backoff: Multiplier for delay increase
        max_delay: Maximum delay between attempts
        logger: Optional logger for retry attempts
    """

    def deco_retry(func):
        @wraps(func)
        def func_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return func(*args, **kwargs)
                except exception_to_check as e:
                    if logger:
                        logger.debug(
                            f"Retry {tries - mtries + 1}/{tries} for {func.__name__}: {e}"
                        )
                    time.sleep(min(mdelay, max_delay))
                    mtries -= 1
                    mdelay *= backoff
            return func(*args, **kwargs)

        return func_retry

    return deco_retry


class BaseDevice(Thread):
    """Base class for all devices with common functionality."""

    def __init__(
        self,
        ip: str,
        port: int = 80,
        refresh_period: float = 5,
        results_dir: str = "",
        timeout: float = DEFAULT_TIMEOUT,
    ):
        super().__init__(daemon=True)

        self._ip = ip
        self._port = port
        self._refresh_period = refresh_period
        self._results_dir = results_dir
        self._timeout = timeout

        # Device state with DeviceStatus
        self._device_status = DeviceStatus("offline")
        self._info = {"ip": ip}
        self._id = ""
        self._is_online = True

        # mDNS service name (e.g. "ETHOSCOPE000-<id>._ethoscope._tcp.local.").
        # Stable across IP changes — used by the scanner to re-locate a known
        # device after a DHCP renewal moves it to a new address.
        self.zeroconf_name: str | None = None

        # Synchronization and error tracking
        self._lock = RLock()
        self._last_refresh = 0
        self._consecutive_errors = 0
        # Reason: at the default 5s refresh, 30 errors = ~2.5 min of consistent
        # failure before we slow polling. Transient WiFi blips and short Pi
        # restarts shouldn't trip this.
        self._max_consecutive_errors = 30
        # Polling cadence to use once _consecutive_errors crosses the threshold;
        # the device is still probed (allowing automatic recovery) but at a much
        # lower rate to avoid log spam and wasted network calls.
        self._unreachable_refresh_period = 60.0
        self._last_successful_contact = time.time()

        # Logging
        self._logger = logging.getLogger(f"{self.__class__.__name__}_{ip}")
        # Ensure device loggers inherit the root logger's level
        if self._logger.level == logging.NOTSET:
            self._logger.setLevel(logging.getLogger().level or logging.INFO)

        # URLs
        self._setup_urls()

        # Initialize device info
        self._reset_info()

    def _setup_urls(self):
        """Setup device-specific URLs. Override in subclasses."""
        self._id_url = f"http://{self._ip}:{self._port}/id"
        self._data_url = f"http://{self._ip}:{self._port}/"

    @retry(ScanException, tries=MAX_RETRIES, delay=INITIAL_RETRY_DELAY, backoff=1.5)
    def _get_json(
        self,
        url: str,
        timeout: float | None = None,
        post_data: bytes | None = None,
    ) -> dict[str, Any]:
        """
        Fetch JSON data from URL with retry logic and improved error handling.
        """
        timeout = timeout or self._timeout

        try:
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "EthoscopeNode/1.0",
            }
            req = urllib.request.Request(url, data=post_data, headers=headers)

            with urllib.request.urlopen(req, timeout=timeout) as response:
                message = response.read()

                if not message:
                    raise ScanException(f"Empty response from {url}")

                try:
                    return json.loads(message)
                except json.JSONDecodeError as e:
                    raise ScanException(f"Invalid JSON from {url}: {e}") from e

        except urllib.error.HTTPError as e:
            raise NetworkError(f"HTTP {e.code} error from {url}") from e
        except urllib.error.URLError as e:
            raise NetworkError(f"URL error from {url}: {e.reason}") from e
        except TimeoutError as e:
            raise NetworkError(f"Timeout connecting to {url}") from e
        except Exception as e:
            raise ScanException(f"Unexpected error from {url}: {e}") from e

    def run(self):
        """Main device monitoring loop"""
        while self._is_online:
            time.sleep(0.2)

            current_time = time.time()

            # Check if it's time for regular refresh (use dynamic refresh period)
            effective_refresh_period = self._get_effective_refresh_period()
            if current_time - self._last_refresh > effective_refresh_period:
                try:
                    self._update_info()
                    # Reset error counter on successful update
                    if self._consecutive_errors > 0:
                        self._logger.info(
                            f"Device {self._ip} recovered after {self._consecutive_errors} errors"
                        )
                        self._consecutive_errors = 0
                    self._last_successful_contact = current_time
                except Exception as e:
                    self._handle_device_error(e)

                self._last_refresh = current_time

    def _handle_device_error(self, error):
        """Record a polling failure.

        We never stop probing the device — once ``_consecutive_errors`` crosses
        ``_max_consecutive_errors`` the polling loop simply switches to a
        slower cadence (see ``_get_effective_refresh_period``) so dead hosts
        don't waste resources, but recovery is automatic on the next
        successful poll.
        """
        with self._lock:
            self._consecutive_errors += 1
            # Always reset device info to offline (status, counters, etc.)
            self._reset_info()

            # Log at decreasing verbosity so a long-offline device doesn't spam.
            if self._consecutive_errors == 1:
                self._logger.info(f"Device {self._ip} connection failed: {str(error)}")
            elif self._consecutive_errors == self._max_consecutive_errors:
                self._logger.warning(
                    f"Device {self._ip} unreachable after "
                    f"{self._consecutive_errors} errors; backing off to "
                    f"{self._unreachable_refresh_period:.0f}s polling"
                )
            else:
                self._logger.debug(
                    f"Device {self._ip} error #{self._consecutive_errors}: {str(error)}"
                )

    def _update_id(self):
        """Update device ID with proper error handling."""
        try:
            # Try data URL first, then ID URL
            try:
                resp = self._get_json(self._data_url)
            except ScanException:
                resp = self._get_json(self._id_url)

            old_id = self._id
            new_id = resp.get("id", "")

            if new_id != old_id:
                if old_id:
                    self._logger.info(f"Device ID changed: {old_id} -> {new_id}")
                self._reset_info()

            self._id = new_id
            self._info["ip"] = self._ip
            self._info["id"] = new_id

        except ScanException:
            raise
        except Exception as e:
            raise ScanException(f"Failed to update device ID: {e}") from e

    def _update_device_status(self, status_name: str):
        """Set the current ``DeviceStatus`` to ``status_name`` and log changes."""
        with self._lock:
            previous_status = self._device_status
            self._device_status = DeviceStatus(status_name=status_name)
            self._info["last_seen"] = time.time()
            self._info["consecutive_errors"] = self._consecutive_errors

            if previous_status and previous_status.status_name != status_name:
                self._logger.info(
                    f"Status changed: {previous_status.status_name} -> {status_name}"
                )

    def _reset_info(self):
        """Reset device info to offline state."""
        with self._lock:
            # Preserve important identifying information
            preserved_name = self._info.get("name", "")
            preserved_id = self._info.get("id", self._id)

            # Update status using DeviceStatus
            self._update_device_status("offline")

            base_info = {
                "ip": self._ip,
                "last_seen": time.time(),
                "consecutive_errors": self._consecutive_errors,
            }

            # Preserve name and id if they exist
            if preserved_name:
                base_info["name"] = preserved_name
            if preserved_id:
                base_info["id"] = preserved_id

            self._info.update(base_info)

    def _update_info(self):
        """Update device information. Override in subclasses."""
        self._update_id()
        with self._lock:
            self._update_device_status("online")
            self._info["last_seen"] = time.time()

    def stop(self):
        """Stop the device monitoring thread."""
        self._is_online = False

    def reset_error_state(self):
        """Reset error state for this device."""
        self._consecutive_errors = 0
        self._error_backoff_time = 0

    def _get_effective_refresh_period(self) -> float:
        """Get the effective refresh period.

        Falls back to a slower cadence for busy devices and for devices that
        appear unreachable (so we don't hammer dead hosts but still recover
        automatically as soon as they respond).
        """
        current_status = self.get_device_status()
        if current_status and current_status.status_name == "busy":
            return 60.0
        if self._consecutive_errors >= self._max_consecutive_errors:
            return self._unreachable_refresh_period
        return self._refresh_period

    def _update_address(self, new_ip: str, new_port: int) -> bool:
        """Update the device's network address (e.g. after a DHCP IP change).

        Rebuilds cached URLs and clears error state so the next refresh hits
        the new address. Returns True if anything actually changed.
        """
        with self._lock:
            if new_ip == self._ip and new_port == self._port:
                return False
            old_ip = self._ip
            self._ip = new_ip
            self._port = new_port
            self._info["ip"] = new_ip
            # Reason: subclasses cache URLs built from _ip/_port at construction
            # time (see _setup_urls); we must rebuild them after an address change.
            self._setup_urls()
            self.reset_error_state()
            self._logger.info(
                f"Device address updated: {old_ip} -> {new_ip}:{new_port}"
            )
            return True

    # Public interface methods
    def ip(self) -> str:
        """Get device IP address."""
        return self._ip

    def id(self) -> str:
        """Get device ID."""
        with self._lock:
            return self._id

    def get_device_status(self) -> DeviceStatus:
        """Get the current DeviceStatus object."""
        with self._lock:
            return self._device_status

    def info(self) -> dict[str, Any]:
        """Get device information dictionary."""
        with self._lock:
            info_copy = self._info.copy()

            if self._device_status:
                info_copy["status"] = self._device_status.status_name
                info_copy["status_details"] = {
                    "status": self._device_status.status_name,
                    "age_minutes": self._device_status.get_age_minutes(),
                    "consecutive_errors": self._consecutive_errors,
                }

            # Expose backup status at root level for frontend compatibility
            progress_info = info_copy.get("progress", {})
            if progress_info:
                # Extract backup status from progress and expose at root level
                backup_status = progress_info.get("status")
                if backup_status:
                    info_copy["backup_status"] = backup_status

                # Also expose backup_size and time_since_backup if available
                backup_size = progress_info.get("backup_size")
                if backup_size is not None:
                    info_copy["backup_size"] = backup_size

                time_since_backup = progress_info.get("time_since_backup")
                if time_since_backup is not None:
                    info_copy["time_since_backup"] = time_since_backup

            return info_copy


class DeviceScanner:
    """Base scanner class for discovering devices via Zeroconf."""

    SUFFIX = ".local"
    SERVICE_TYPE = "_device._tcp.local."
    DEVICE_TYPE = "device"

    def __init__(self, device_refresh_period: float = 5, device_class=BaseDevice):
        self._zeroconf = None
        self.devices: list[BaseDevice] = []
        self.device_refresh_period = device_refresh_period
        self._device_class = device_class
        self._browser = None
        self._lock = RLock()
        self._logger = logging.getLogger(self.__class__.__name__)
        # Ensure scanner loggers inherit the root logger's level
        if self._logger.level == logging.NOTSET:
            self._logger.setLevel(logging.getLogger().level or logging.INFO)
        self.results_dir = ""  # Default, override in subclasses
        self._is_running = False

    def start(self):
        """Start the Zeroconf service browser."""
        if self._is_running:
            self._logger.warning("Scanner already running")
            return

        try:
            ifaces = _get_multicast_interfaces()
            if ifaces:
                self._zeroconf = Zeroconf(
                    ip_version=IPVersion.V4Only, interfaces=ifaces
                )
            else:
                self._zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
            self._browser = ServiceBrowser(self._zeroconf, self.SERVICE_TYPE, self)
            self._is_running = True
            self._logger.info(f"Started {self.DEVICE_TYPE} scanner")
        except Exception as e:
            self._logger.error(f"Error starting scanner: {e}")
            self._cleanup_zeroconf()
            raise

    def stop(self):
        """Stop the scanner and cleanup."""
        if not self._is_running:
            return

        self._is_running = False

        try:
            # Stop all devices first
            with self._lock:
                for device in self.devices:
                    try:
                        device.stop()
                    except Exception as e:
                        self._logger.warning(
                            f"Error stopping device {device.ip()}: {e}"
                        )

            # Clean up zeroconf resources
            self._cleanup_zeroconf()

            self._logger.info(f"Stopped {self.DEVICE_TYPE} scanner")

        except Exception as e:
            self._logger.error(f"Error stopping scanner: {e}")

    def _cleanup_zeroconf(self):
        """Clean up zeroconf resources properly."""
        try:
            if self._browser:
                self._browser.cancel()
                self._browser = None

            if self._zeroconf:
                self._zeroconf.close()
                self._zeroconf = None

        except Exception as e:
            self._logger.warning(f"Error during zeroconf cleanup: {e}")

    def __del__(self):
        """Destructor to ensure cleanup."""
        try:
            self.stop()
        except Exception:
            pass

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()

    @property
    def current_devices_id(self) -> list[str]:
        """Get list of current device IDs."""
        with self._lock:
            return [device.id() for device in self.devices if device.id()]

    def get_all_devices_info(self) -> dict[str, dict[str, Any]]:
        """Get information for all devices."""
        with self._lock:
            return {
                device.id(): device.info() for device in self.devices if device.id()
            }

    def get_device(self, device_id: str) -> BaseDevice | None:
        """Get device by ID."""
        with self._lock:
            for device in self.devices:
                if device.id() == device_id:
                    return device
        return None

    def _find_device_by_zeroconf_name(self, name: str):
        """Find a device by its mDNS service name. Caller must hold self._lock."""
        if not name:
            return None
        for device in self.devices:
            if getattr(device, "zeroconf_name", None) == name:
                return device
        return None

    def add(
        self,
        ip: str,
        port: int,
        name: str | None = None,
        device_id: str | None = None,
        zcinfo: dict | None = None,
    ):
        """Add a device to the scanner."""
        if not self._is_running:
            self._logger.warning(f"Cannot add device {ip}:{port} - scanner not running")
            return

        try:
            with self._lock:
                # Reason: mDNS service name embeds the device ID and is stable
                # across DHCP IP changes — match by it first so a re-announced
                # device updates its existing entry instead of being treated as
                # new (which would orphan the old entry at the stale IP).
                existing_device = self._find_device_by_zeroconf_name(name)
                if existing_device is not None and existing_device.ip() != ip:
                    self._logger.info(
                        f"{self.DEVICE_TYPE} {name} re-announced at new address "
                        f"{ip}:{port} (was {existing_device.ip()}:{existing_device._port})"
                    )
                    existing_device._update_address(ip, port)
                    with existing_device._lock:
                        existing_device._update_device_status("offline")
                        existing_device._info.update({"last_seen": time.time()})
                    return

                # Check if device already exists by IP (more immediate than waiting for ID)
                for existing_device in self.devices:
                    if existing_device.ip() == ip:
                        device_status = existing_device._device_status.status_name
                        prev_errors = existing_device._consecutive_errors

                        self._logger.info(
                            f"Device at {ip} already exists "
                            f"(status: {device_status}, errors: {prev_errors}), "
                            f"updating zeroconf info"
                        )

                        if hasattr(existing_device, "zeroconf_name"):
                            existing_device.zeroconf_name = name

                        # Reset error state so the next poll fires immediately
                        existing_device.reset_error_state()

                        # Explicitly reset status to allow device info to be updated
                        with existing_device._lock:
                            existing_device._update_device_status("offline")
                            existing_device._info.update({"last_seen": time.time()})

                        return

                # Create and start device
                device_kwargs = {
                    "ip": ip,
                    "port": port,
                    "refresh_period": self.device_refresh_period,
                    "results_dir": getattr(self, "results_dir", ""),
                }

                # Only add config_dir if the device class supports it (for Ethoscope)
                if hasattr(self, "config_dir"):
                    import inspect

                    sig = inspect.signature(self._device_class.__init__)
                    if "config_dir" in sig.parameters:
                        device_kwargs["config_dir"] = self.config_dir

                device = self._device_class(**device_kwargs)

                if hasattr(device, "zeroconf_name"):
                    device.zeroconf_name = name

                device.start()

                # Check for duplicates
                device_id = device_id or device.id()
                if device_id in self.current_devices_id:
                    self._logger.info(f"Device {device_id} already exists, skipping")
                    device.stop()
                    return

                self.devices.append(device)
                self._logger.info(
                    f"Added {self.DEVICE_TYPE} {name} (ID: {device_id}) at {ip}:{port}"
                )

        except Exception as e:
            self._logger.error(f"Error adding device at {ip}:{port}: {e}")

    def add_service(self, zeroconf, service_type: str, name: str):
        """Zeroconf callback for new services."""
        if not self._is_running:
            return

        try:
            info = zeroconf.get_service_info(service_type, name)
            if info and info.addresses:
                ip = socket.inet_ntoa(info.addresses[0])
                port = info.port
                self.add(ip, port, name, zcinfo=info.properties)

        except Exception as e:
            self._logger.error(f"Error adding zeroconf service {name}: {e}")

    def remove_service(self, zeroconf, service_type: str, name: str):
        """Zeroconf callback for removed services - mark devices as offline."""
        if not self._is_running:
            return

        info = zeroconf.get_service_info(service_type, name)
        if not info or not info.addresses:
            return

        ip = socket.inet_ntoa(info.addresses[0])
        with self._lock:
            for device in self.devices:
                if device.ip() == ip:
                    device_id = device.id()
                    self._logger.info(
                        f"{self.DEVICE_TYPE} {device_id or 'unknown'} at {ip} "
                        f"went offline via zeroconf removal"
                    )

                    # Mark offline; the device thread keeps probing on the
                    # slow cadence in case it comes back.
                    with device._lock:
                        device._update_device_status("offline")
                        device._info.update({"last_seen": time.time()})

                    break

    def update_service(self, zeroconf, service_type: str, name: str):
        """Zeroconf callback for service updates (e.g. IP address change).

        Looks up the known device by mDNS service name and updates its address
        in place. If the service is unknown (e.g. we missed the original add),
        falls back to the regular add path.
        """
        if not self._is_running:
            return

        try:
            info = zeroconf.get_service_info(service_type, name)
            if not info or not info.addresses:
                return

            new_ip = socket.inet_ntoa(info.addresses[0])
            new_port = info.port

            with self._lock:
                existing_device = self._find_device_by_zeroconf_name(name)

            if existing_device is None:
                self._logger.info(
                    f"Zeroconf update for unknown {self.DEVICE_TYPE} {name} "
                    f"at {new_ip}:{new_port}, treating as new device"
                )
                self.add(new_ip, new_port, name, zcinfo=info.properties)
                return

            if existing_device._update_address(new_ip, new_port):
                # _update_address already calls reset_error_state(); just refresh
                # the published status so the next poll re-promotes it to online.
                with existing_device._lock:
                    existing_device._update_device_status("offline")
                    existing_device._info.update({"last_seen": time.time()})

        except Exception as e:
            self._logger.error(f"Error handling zeroconf update for {name}: {e}")
