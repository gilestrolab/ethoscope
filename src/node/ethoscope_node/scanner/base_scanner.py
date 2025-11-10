import json
import logging
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import wraps
from threading import RLock
from threading import Thread
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from zeroconf import IPVersion
from zeroconf import ServiceBrowser
from zeroconf import Zeroconf

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
    last_seen: Optional[float] = None


class DeviceStatus:
    """
    Sophisticated device status management class that tracks status changes,
    user interactions, and provides intelligent alerting logic.
    """

    # Valid status types
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

    # Graceful operation types
    GRACEFUL_OPERATIONS = {"poweroff", "reboot", "restart"}

    def __init__(
        self,
        status_name: str,
        is_user_triggered: bool = False,
        trigger_source: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize device status.

        Args:
            status_name: Name of the status (must be in VALID_STATUSES)
            is_user_triggered: Whether this status change was triggered by user action
            trigger_source: Source of the trigger ("user", "system", "network", "graceful")
            metadata: Additional metadata about the status change
        """
        if status_name not in self.VALID_STATUSES:
            raise ValueError(
                f"Invalid status: {status_name}. Must be one of: {self.VALID_STATUSES}"
            )

        self._status_name = status_name
        self._is_user_triggered = is_user_triggered
        self._trigger_source = trigger_source
        self._timestamp = time.time()
        self._previous_status = None
        self._metadata = metadata or {}
        self._unreachable_start_time = None
        self._consecutive_errors = 0
        self._is_initial_discovery = False  # Flag to track initial device discovery

        # Set unreachable start time if this is an unreached status
        if status_name == "unreached":
            self._unreachable_start_time = self._timestamp

    @property
    def status_name(self) -> str:
        """Get the status name."""
        return self._status_name

    @property
    def is_user_triggered(self) -> bool:
        """Check if this status change was triggered by user action."""
        return self._is_user_triggered

    @property
    def trigger_source(self) -> str:
        """Get the trigger source."""
        return self._trigger_source

    @property
    def timestamp(self) -> float:
        """Get the timestamp when this status was set."""
        return self._timestamp

    @property
    def metadata(self) -> Dict[str, Any]:
        """Get status metadata."""
        return self._metadata.copy()

    @property
    def consecutive_errors(self) -> int:
        """Get the number of consecutive errors."""
        return self._consecutive_errors

    def set_previous_status(self, previous_status: Optional["DeviceStatus"]):
        """Set the previous status for transition tracking."""
        self._previous_status = previous_status

    def get_previous_status(self) -> Optional["DeviceStatus"]:
        """Get the previous status."""
        return self._previous_status

    def increment_errors(self):
        """Increment the consecutive error count."""
        self._consecutive_errors += 1

    def reset_errors(self):
        """Reset the consecutive error count."""
        self._consecutive_errors = 0

    def mark_as_initial_discovery(self):
        """Mark this status as an initial device discovery (server startup)."""
        self._is_initial_discovery = True

    def should_send_alert(self, unreachable_timeout_minutes: int = 20) -> bool:
        """
        Determine if an alert should be sent for this status.

        Args:
            unreachable_timeout_minutes: Minutes to wait before alerting for unreachable devices

        Returns:
            True if an alert should be sent
        """
        # No alerts for user-triggered actions
        if self._is_user_triggered:
            return False

        # No alerts for graceful operations within grace period
        if self.is_graceful_operation():
            return False

        # Check for interrupted tracking session (reboot scenario)
        if (
            self._status_name in ["stopped", "offline"]
            and self.is_interrupted_tracking_session()
        ):
            return True

        # Alert for autonomous stops and other system issues (direct transitions)
        # But exclude initial device discovery transitions during server startup
        if (
            self._status_name in ["stopped", "offline"]
            and self._trigger_source == "system"
        ):
            # Don't alert for initial device discovery
            if self._is_initial_discovery:
                return False
            return True

        return False

    def is_timeout_exceeded(self, timeout_minutes: int) -> bool:
        """
        Check if the timeout has been exceeded for unreachable devices.

        Args:
            timeout_minutes: Timeout in minutes

        Returns:
            True if timeout has been exceeded
        """
        if not self._unreachable_start_time:
            return False

        elapsed_minutes = (time.time() - self._unreachable_start_time) / 60
        return elapsed_minutes > timeout_minutes

    def is_graceful_operation(self) -> bool:
        """
        Check if this status resulted from a graceful operation.

        Returns:
            True if this is a graceful operation
        """
        return self._trigger_source == "graceful"

    def get_age_seconds(self) -> float:
        """
        Get the age of this status in seconds.

        Returns:
            Age in seconds
        """
        return time.time() - self._timestamp

    def get_age_minutes(self) -> float:
        """
        Get the age of this status in minutes.

        Returns:
            Age in minutes
        """
        return self.get_age_seconds() / 60

    def is_interrupted_tracking_session(self) -> bool:
        """
        Detect if this represents an interrupted tracking session.

        Pattern: {tracking,recording,running} -> (intermediate_states)n -> {stopped,offline}
        where intermediate_states are: unreached, busy, initialising, stopping

        This detects when an active tracking/recording session is permanently
        interrupted (e.g., by reboot, crash) rather than just temporarily unreachable.

        Returns:
            True if this appears to be an interrupted tracking session
        """
        # Only relevant for final states that indicate permanent interruption
        if self._status_name not in ["stopped", "offline"]:
            return False

        # Check if we have a previous status chain
        if not self._previous_status:
            return False

        # Look for interrupted session patterns
        current = self._previous_status
        found_active_session = False
        went_through_intermediates = False
        status_chain = []

        # Active session states that we care about being interrupted
        active_states = {"running", "recording", "tracking"}

        # Intermediate states that indicate interruption (not user-initiated)
        intermediate_states = {"unreached", "busy", "initialising", "stopping"}

        # Walk back through status chain (max 10 steps for complex sequences)
        max_lookback = 10
        steps = 0

        while current and steps < max_lookback:
            status_chain.append(current.status_name)

            if current.status_name in active_states:
                found_active_session = True
                break
            elif current.status_name in intermediate_states:
                went_through_intermediates = True

            current = current._previous_status
            steps += 1

        # Store debug info for external logging
        self._debug_chain = (
            " -> ".join(reversed(status_chain)) + f" -> {self._status_name}"
        )
        self._debug_found_active_session = found_active_session
        self._debug_went_through_intermediates = went_through_intermediates

        # We have an interrupted session if:
        # 1. We found an active session state in the history
        # 2. We went through intermediate states (indicating non-graceful transition)
        return found_active_session and went_through_intermediates

    def update_metadata(self, key: str, value: Any):
        """
        Update metadata for this status.

        Args:
            key: Metadata key
            value: Metadata value
        """
        self._metadata[key] = value

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert status to dictionary for serialization.

        Returns:
            Dictionary representation of the status
        """
        return {
            "status_name": self._status_name,
            "is_user_triggered": self._is_user_triggered,
            "trigger_source": self._trigger_source,
            "timestamp": self._timestamp,
            "metadata": self._metadata,
            "unreachable_start_time": self._unreachable_start_time,
            "consecutive_errors": self._consecutive_errors,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeviceStatus":
        """
        Create DeviceStatus from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            DeviceStatus instance
        """
        status = cls(
            status_name=data["status_name"],
            is_user_triggered=data.get("is_user_triggered", False),
            trigger_source=data.get("trigger_source", "system"),
            metadata=data.get("metadata", {}),
        )

        status._timestamp = data.get("timestamp", time.time())
        status._unreachable_start_time = data.get("unreachable_start_time")
        status._consecutive_errors = data.get("consecutive_errors", 0)

        return status

    def __str__(self) -> str:
        """String representation of the status."""
        age_minutes = self.get_age_minutes()
        return f"DeviceStatus({self._status_name}, {self._trigger_source}, {age_minutes:.1f}m ago)"

    def __repr__(self) -> str:
        """Detailed string representation."""
        return (
            f"DeviceStatus(status_name='{self._status_name}', "
            f"is_user_triggered={self._is_user_triggered}, "
            f"trigger_source='{self._trigger_source}', "
            f"age_minutes={self.get_age_minutes():.1f})"
        )


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
        self._device_status = DeviceStatus("offline", trigger_source="system")
        self._info = {"ip": ip}
        self._id = ""
        self._is_online = True
        self._skip_scanning = False

        # Synchronization and error tracking
        self._lock = RLock()
        self._last_refresh = 0
        self._consecutive_errors = 0
        self._max_consecutive_errors = 10
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
        timeout: Optional[float] = None,
        post_data: Optional[bytes] = None,
    ) -> Dict[str, Any]:
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
                    raise ScanException(f"Invalid JSON from {url}: {e}")

        except urllib.error.HTTPError as e:
            raise NetworkError(f"HTTP {e.code} error from {url}")
        except urllib.error.URLError as e:
            raise NetworkError(f"URL error from {url}: {e.reason}")
        except socket.timeout:
            raise NetworkError(f"Timeout connecting to {url}")
        except Exception as e:
            raise ScanException(f"Unexpected error from {url}: {e}")

    def run(self):
        """Main device monitoring loop"""
        while self._is_online:
            time.sleep(0.2)

            current_time = time.time()

            # Check if it's time for regular refresh (use dynamic refresh period)
            effective_refresh_period = self._get_effective_refresh_period()
            if current_time - self._last_refresh > effective_refresh_period:
                if not self._skip_scanning:
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
                        # Only handle error if not already marked for skipping
                        if not self._skip_scanning:
                            self._handle_device_error(e)
                else:
                    # Device is marked for skipping - just update status to offline
                    self._reset_info()

                self._last_refresh = current_time

    def _handle_device_error(self, error):
        """Handle device errors. Stop interrogating devices that appear to have shut down ungracefully."""
        with self._lock:
            self._consecutive_errors += 1

            # Always reset device info to offline
            self._reset_info()

            error_str = str(error).lower()

            # Check if this is a "connection refused" error - indicates potential shutdown
            if "connection refused" in error_str or "actively refused" in error_str:
                # After 3 consecutive connection refused errors, determine if this is graceful or ungraceful
                if self._consecutive_errors >= 3:
                    # Check if this might be a graceful shutdown
                    is_graceful = self._is_graceful_shutdown()

                    if is_graceful:
                        self._logger.info(
                            f"Device {self._ip} appears to have been shut down gracefully (recent user action). Stopping interrogation."
                        )
                        self._skip_scanning = True
                        self._update_device_status(
                            "offline",
                            trigger_source="graceful",
                            metadata={"reason": "graceful_shutdown"},
                        )
                    else:
                        self._logger.info(
                            f"Device {self._ip} has {self._consecutive_errors} consecutive connection refused errors - appears shut down ungracefully. Stopping interrogation."
                        )
                        self._skip_scanning = True
                        self._update_device_status(
                            "offline",
                            trigger_source="system",
                            metadata={"reason": "ungraceful_shutdown"},
                        )

                    self._info.update({"last_seen": time.time()})
                    return
                else:
                    self._logger.info(
                        f"Device {self._ip} connection refused (attempt {self._consecutive_errors}/3)"
                    )
                    return

            if self._consecutive_errors >= self._max_consecutive_errors:
                # Device seems to have gone offline normally, stop interrogating
                self._logger.info(
                    f"Device {self._ip} appears offline after {self._consecutive_errors} errors, stopping interrogation"
                )
                self._skip_scanning = True
                self._update_device_status(
                    "offline",
                    trigger_source="system",
                    metadata={"reason": "max_errors_reached"},
                )
                self._info.update({"last_seen": time.time()})
            else:
                # Log errors less frequently to reduce noise
                if self._consecutive_errors == 1:
                    self._logger.info(
                        f"Device {self._ip} connection failed: {str(error)}"
                    )
                elif self._consecutive_errors == 5:
                    self._logger.warning(
                        f"Device {self._ip} has 5 consecutive errors, will stop interrogating at 10"
                    )
                else:
                    self._logger.debug(
                        f"Device {self._ip} error #{self._consecutive_errors}: {str(error)}"
                    )

    def _update_id(self):
        """Update device ID with proper error handling."""
        if self._skip_scanning:
            raise ScanException(f"Not scanning IP {self._ip}")

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
            raise ScanException(f"Failed to update device ID: {e}")

    def _update_device_status(
        self,
        status_name: str,
        is_user_triggered: bool = False,
        trigger_source: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Update device status using DeviceStatus object.

        Args:
            status_name: New status name
            is_user_triggered: Whether this was triggered by user action
            trigger_source: Source of the trigger
            metadata: Additional metadata
        """
        with self._lock:
            # Create new status object
            previous_status = self._device_status
            new_status = DeviceStatus(
                status_name=status_name,
                is_user_triggered=is_user_triggered,
                trigger_source=trigger_source,
                metadata=metadata or {},
            )

            # Set previous status for transition tracking
            new_status.set_previous_status(previous_status)

            # Mark as initial discovery if transitioning from initial offline state
            if (
                previous_status
                and previous_status.status_name == "offline"
                and not hasattr(self, "_has_received_real_status")
            ):
                new_status.mark_as_initial_discovery()
                self._has_received_real_status = True

            # Update consecutive errors from previous status
            if previous_status:
                new_status._consecutive_errors = previous_status.consecutive_errors

            # Update device status
            self._device_status = new_status

            # Update info dict (no longer storing status directly)
            self._info["last_seen"] = time.time()
            self._info["consecutive_errors"] = new_status.consecutive_errors

            # Log status change
            if previous_status and previous_status.status_name != status_name:
                self._logger.info(
                    f"Status changed: {previous_status.status_name} -> {status_name} "
                    f"(trigger: {trigger_source}, user: {is_user_triggered})"
                )

    def _reset_info(self):
        """Reset device info to offline state."""
        with self._lock:
            # Preserve important identifying information
            preserved_name = self._info.get("name", "")
            preserved_id = self._info.get("id", self._id)

            # Update status using DeviceStatus
            self._update_device_status("offline", trigger_source="system")

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
            self._update_device_status("online", trigger_source="system")
            self._info["last_seen"] = time.time()

    def stop(self):
        """Stop the device monitoring thread."""
        self._is_online = False

    def skip_scanning(self, value: bool):
        """Enable/disable scanning for this device."""
        self._skip_scanning = value
        if not value:
            # Re-enabling scanning - reset error state
            self._consecutive_errors = 0

    def reset_error_state(self):
        """Reset error state for this device."""
        self._consecutive_errors = 0
        self._error_backoff_time = 0

    def _is_graceful_shutdown(self) -> bool:
        """
        Check if a connection refused error is likely due to graceful shutdown.

        Returns:
            True if this appears to be a graceful shutdown
        """
        # The DeviceStatus class already handles graceful operation detection
        current_status = self.get_device_status()
        return current_status and current_status.is_graceful_operation()

    def _get_effective_refresh_period(self) -> float:
        """
        Get the effective refresh period based on device status.

        Returns:
            Refresh period in seconds (60s for busy devices, normal for others)
        """
        current_status = self.get_device_status()
        if current_status and current_status.status_name == "busy":
            return 60.0  # Busy devices refresh every 60 seconds
        return self._refresh_period  # Normal refresh period

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

    def info(self) -> Dict[str, Any]:
        """Get device information dictionary."""
        with self._lock:
            info_copy = self._info.copy()

            # Add enhanced status information from DeviceStatus
            if self._device_status:
                # Get timeout from configuration if available (for Ethoscope devices)
                unreachable_timeout = 20  # Default
                if hasattr(self, "_config"):
                    alert_config = self._config.get_custom("alerts") or {}
                    unreachable_timeout = alert_config.get(
                        "unreachable_timeout_minutes", 20
                    )

                # Add status at root level for backward compatibility
                info_copy["status"] = self._device_status.status_name

                # Add detailed status information
                info_copy["status_details"] = {
                    "status": self._device_status.status_name,
                    "is_user_triggered": self._device_status.is_user_triggered,
                    "trigger_source": self._device_status.trigger_source,
                    "age_minutes": self._device_status.get_age_minutes(),
                    "consecutive_errors": self._device_status.consecutive_errors,
                    "should_alert": self._device_status.should_send_alert(
                        unreachable_timeout
                    ),
                }

            # Add skip_scanning status for debugging
            info_copy["skip_scanning"] = self._skip_scanning

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
        self.devices: List[BaseDevice] = []
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
    def current_devices_id(self) -> List[str]:
        """Get list of current device IDs."""
        with self._lock:
            return [device.id() for device in self.devices if device.id()]

    def get_all_devices_info(self) -> Dict[str, Dict[str, Any]]:
        """Get information for all devices."""
        with self._lock:
            return {
                device.id(): device.info() for device in self.devices if device.id()
            }

    def get_device(self, device_id: str) -> Optional[BaseDevice]:
        """Get device by ID."""
        with self._lock:
            for device in self.devices:
                if device.id() == device_id:
                    return device
        return None

    def add(
        self,
        ip: str,
        port: int,
        name: Optional[str] = None,
        device_id: Optional[str] = None,
        zcinfo: Optional[Dict] = None,
    ):
        """Add a device to the scanner."""
        if not self._is_running:
            self._logger.warning(f"Cannot add device {ip}:{port} - scanner not running")
            return

        try:
            with self._lock:
                # Check if device already exists by IP (more immediate than waiting for ID)
                for existing_device in self.devices:
                    if existing_device.ip() == ip:
                        was_skipping = existing_device._skip_scanning
                        device_status = existing_device._device_status.status_name

                        self._logger.info(
                            f"Device at {ip} already exists (was skipping: {was_skipping}, status: {device_status}), updating zeroconf info"
                        )

                        if hasattr(existing_device, "zeroconf_name"):
                            existing_device.zeroconf_name = name

                        # Reset error state and re-enable scanning in case it was offline
                        existing_device.reset_error_state()
                        existing_device.skip_scanning(False)

                        # Explicitly reset status to allow device info to be updated
                        with existing_device._lock:
                            existing_device._update_device_status(
                                "offline", trigger_source="system"
                            )
                            existing_device._info.update({"last_seen": time.time()})

                        self._logger.info(
                            f"Re-enabled scanning for {self.DEVICE_TYPE} at {ip} (was skipping: {was_skipping})"
                        )
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
                        f"{self.DEVICE_TYPE} {device_id or 'unknown'} at {ip} went offline via zeroconf removal"
                    )

                    # Stop interrogating the device but keep it in the list
                    device.skip_scanning(True)

                    # Explicitly set status to offline
                    with device._lock:
                        device._update_device_status("offline", trigger_source="system")
                        device._info.update({"last_seen": time.time()})

                    break

    def update_service(self, zeroconf, service_type: str, name: str):
        """Zeroconf callback for service updates."""
        pass
