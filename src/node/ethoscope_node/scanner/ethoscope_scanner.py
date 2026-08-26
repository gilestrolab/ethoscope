import datetime
import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any

from ethoscope_node.notifications.manager import NotificationManager
from ethoscope_node.scanner.base_scanner import (
    BaseDevice,
    DeviceError,
    DeviceScanner,
    DeviceStatus,
    ScanException,
)
from ethoscope_node.scanner.ethoscope_streaming import EthoscopeStreamManager
from ethoscope_node.utils.configuration import (
    EthoscopeConfiguration,
    get_ssh_key_paths,
)
from ethoscope_node.utils.etho_db import ExperimentalDB
from ethoscope_node.utils.network import open_http_url
from ethoscope_node.utils.paths import resolve_config_dir

# Constants
STREAMING_PORT = 8887
ETHOSCOPE_PORT = 9000
DB_UPDATE_INTERVAL = 30  # seconds
SSH_RETRY_INTERVAL = 300  # seconds (5 minutes between retry attempts)


class Ethoscope(BaseDevice):
    """Enhanced Ethoscope device class with improved state management."""

    REMOTE_PAGES = {
        "id": "id",
        "data": "data",
        "databases_info": "data/databases",
        "videofiles": "data/listfiles/video",
        "stream": "stream.mjpg",
        "user_options": "user_options",
        "log": "data/log",
        "static": "static",
        "controls": "controls",
        "machine_info": "machine",
        "connected_module": "module",
        "update": "update",
        "dumpdb": "dumpSQLdb",
    }

    ALLOWED_INSTRUCTIONS = {
        "stream": ["stopped"],
        "start": ["stopped"],
        "start_record": ["stopped"],
        "stop": ["streaming", "running", "recording"],
        # Reschedules or cancels the automatic stop of a run already under way, so it
        # is only meaningful while one is.
        "set_autostop": ["streaming", "running", "recording"],
        "poweroff": ["stopped"],
        "reboot": ["stopped"],
        "restart": ["stopped"],
        "dumpdb": ["stopped"],
        "offline": [],
        "convertvideos": ["stopped"],
        "test_module": ["stopped"],
    }

    # Instructions that cause the device to stop tracking. Recorded as user
    # interventions so the scanner can attribute a subsequent run termination
    # to a user action and suppress the alert.
    _STOP_INTERVENTION_INSTRUCTIONS = {
        "stop",
        "poweroff",
        "reboot",
        "restart",
    }

    def __init__(
        self,
        ip: str,
        port: int = ETHOSCOPE_PORT,
        refresh_period: float = 5,
        results_dir: str = "/ethoscope_data/results",
        config_dir: str | None = None,
        config: EthoscopeConfiguration | None = None,
    ):
        # Initialize ethoscope-specific attributes BEFORE calling parent
        self._results_dir = results_dir
        self._config_dir = config_dir or resolve_config_dir()
        self._edb = ExperimentalDB(self._config_dir)
        self._last_db_info = 0
        self._device_controller_created = time.time()
        self._ping_count = 0  # Initialize ping counter
        self._last_ssh_attempt = 0  # Timestamp of last SSH key setup attempt

        # Run reconciliation state. ``_active_run_id`` is the run_id we last
        # observed this device tracking; ``None`` means we have not seen a
        # tracking session active. ``_unreached_since`` is the wall-clock
        # timestamp when we started being unable to reach the device, used to
        # decide if we have hit the unreachable timeout. Both are cleared on
        # run finalisation. See ``_reconcile_run_state``.
        self._active_run_id: str | None = None
        self._unreached_since: float | None = None

        # Use provided configuration or create new one
        self._config = config or EthoscopeConfiguration()
        self._notification_manager = NotificationManager(self._config, self._edb)

        # Streaming manager
        self._stream_manager = None

        # Call parent initialization
        super().__init__(ip, port, refresh_period, results_dir)

    def _setup_urls(self):
        """Setup ethoscope-specific URLs."""
        self._id_url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['id']}"
        self._data_url = (
            f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['data']}/{self._id}"
        )

    def _reset_info(self):
        """Reset device info to offline state."""
        with self._lock:
            # Preserve important identifying information
            preserved_name = self._info.get("name", "")
            preserved_id = self._info.get("id", self._id)

            base_info = {
                "ip": self._ip,
                "last_ip": self._ip,
                "last_seen": time.time(),
                "ping": self._ping_count,
                "consecutive_errors": self._consecutive_errors,
            }

            # Preserve name and id if they exist
            if preserved_name:
                base_info["name"] = preserved_name
            if preserved_id:
                base_info["id"] = preserved_id

            self._info.update(base_info)

    def send_instruction(self, instruction: str, post_data: dict | bytes | None = None):
        """Send instruction to ethoscope with validation and intervention logging.

        Stop-like instructions are persisted as device interventions BEFORE the
        device is touched, so that a concurrent polling thread observing the
        ensuing ``running -> unreached -> stopped`` chain can attribute the
        transition to the user and skip the alert. (Race window: a single poll
        period, currently 5 s. The intervention row is written synchronously
        before any HTTP call to the device.)
        """
        if instruction in self._STOP_INTERVENTION_INSTRUCTIONS:
            self._edb.recordIntervention(self._id, instruction)

        self._check_instruction_status(instruction)

        # Handle post_data properly - it might already be bytes or need conversion
        json_data = None
        if post_data is not None:
            if isinstance(post_data, bytes):
                # Already bytes, use as-is
                json_data = post_data
            elif isinstance(post_data, (dict, list, str, int, float, bool)):
                # JSON serializable data, convert to bytes
                json_data = json.dumps(post_data).encode("utf-8")
            else:
                # Unknown type, try to convert to string then encode
                json_data = str(post_data).encode("utf-8")

        post_url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['controls']}/{self._id}/{instruction}"
        try:
            self._get_json(post_url, timeout=3, post_data=json_data)
        except ScanException as e:
            if instruction in ["poweroff", "reboot", "restart"]:
                pass  # Expected for power operations
            else:
                raise DeviceError(
                    "Cannot send '{instruction}' to device in status '{current_status}'"
                ) from e

        self._update_info()

    def send_settings(self, post_data: dict | bytes) -> Any:
        """Send settings update to ethoscope."""

        # Handle post_data properly
        if isinstance(post_data, bytes):
            json_data = post_data
        else:
            json_data = json.dumps(post_data).encode("utf-8")

        update_url = (
            f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['update']}/{self._id}"
        )
        result = self._get_json(update_url, timeout=3, post_data=json_data)
        self._update_info()
        return result

    def _check_instruction_status(self, instruction: str):
        """Validate that instruction is allowed for current status."""
        self._update_info()

        current_status = self._device_status.status_name
        allowed_statuses = self.ALLOWED_INSTRUCTIONS.get(instruction)

        if allowed_statuses is None:
            raise ValueError(f"Unknown instruction: {instruction}")

        if current_status not in allowed_statuses:
            raise DeviceError(
                f"Cannot send '{instruction}' to device in status '{current_status}'"
            )

    def databases_info(self) -> dict[str, Any]:
        """Get information about all the databases on the ethoscope."""

        if not self._id:
            return {}

        try:
            url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['databases_info']}/{self._id}"
            return self._get_json(url)
        except ScanException:
            return {}

    def machine_info(self) -> dict[str, Any]:
        """Get machine information from ethoscope."""
        if not self._id:
            return {}

        try:
            url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['machine_info']}/{self._id}"
            return self._get_json(url)
        except ScanException:
            return {}

    def connected_module(self) -> dict[str, Any]:
        """Get connected module information."""
        if not self._id:
            return {}

        try:
            url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['connected_module']}/{self._id}"
            return self._get_json(url, timeout=12)
        except ScanException:
            return {}

    def firmware_status(self) -> dict[str, Any]:
        """Get firmware status from device (read-only check)."""
        if not self._id:
            return {}

        try:
            url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['controls']}/{self._id}/firmware_status"
            return self._get_json(url, timeout=15, post_data=b"{}")
        except ScanException:
            return {}

    def update_firmware(self) -> dict[str, Any]:
        """Trigger firmware update on device (compile + upload).

        Uses a longer timeout (120s) since compilation and upload take time.
        Records a user intervention so the run-termination it may trigger is
        attributed to the user.
        """
        if not self._id:
            return {}

        self._edb.recordIntervention(self._id, "update_firmware")
        try:
            url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['controls']}/{self._id}/update_firmware"
            return self._get_json(url, timeout=120, post_data=b"{}")
        except ScanException as e:
            return {"status": "failed", "error": str(e)}

    def videofiles(self) -> list[str]:
        """Get list of available video files."""
        try:
            url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['videofiles']}/{self._id}"
            return self._get_json(url)
        except ScanException:
            return []

    def user_options(self) -> dict[str, Any] | None:
        """Get user options from ethoscope."""
        try:
            url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['user_options']}/{self._id}"
            return self._get_json(url)
        except ScanException:
            return None

    def get_log(self) -> dict[str, Any] | None:
        """Get log from ethoscope."""
        try:
            url = (
                f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['log']}/{self._id}"
            )
            return self._get_json(url)
        except ScanException:
            return None

    def dump_sql_db(self) -> dict[str, Any] | None:
        """Trigger SQL database dump on ethoscope."""
        try:
            url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['dumpdb']}/{self._id}"
            return self._get_json(url, timeout=3)
        except ScanException:
            return None

    def dumpSQLdb(self):
        """Legacy method name for compatibility."""
        return self.dump_sql_db()

    def last_image(self):
        """Get the last drawn image from ethoscope."""
        if self._device_status.status_name not in self.ALLOWED_INSTRUCTIONS["stop"]:
            return None

        try:
            img_path = self._info["last_drawn_img"]
            img_url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['static']}/{img_path}"
            return open_http_url(img_url, timeout=3)
        except (KeyError, urllib.error.HTTPError) as e:
            self._logger.error(f"Could not get image for {self._id}: {e}")
            raise

    def dbg_img(self):
        """Get debug image from ethoscope."""
        try:
            img_path = self._info["dbg_img"]
            img_url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['static']}/{img_path}"
            return open_http_url(img_url, timeout=3)
        except Exception as e:
            self._logger.warning(f"Could not get debug image: {e}")
            return None

    def relay_stream(self) -> Iterator[bytes]:
        """Relay video stream from ethoscope using shared connection."""
        # Lazy import to avoid circular dependencies
        # from .streaming import EthoscopeStreamManager

        # Create stream manager if it doesn't exist
        if self._stream_manager is None:
            self._stream_manager = EthoscopeStreamManager(self._ip, self._id)

        # Delegate to stream manager
        return self._stream_manager.get_stream_for_client()

    def cleanup_stream_manager(self):
        """Clean up the stream manager to force connection reset on next streaming attempt."""
        if self._stream_manager is not None:
            self._logger.info(f"Cleaning up stream manager for device {self._id}")
            self._stream_manager.stop()
            self._stream_manager = None

    def stop(self):
        """Stop the ethoscope device and cleanup streaming connections."""
        # Stop stream manager if it exists
        if self._stream_manager is not None:
            self._stream_manager.stop()
            self._stream_manager = None

        # Call parent stop method
        super().stop()

    def _update_info(self):
        """Poll the device, update local status, and reconcile run state."""
        previous_status_obj = self.get_device_status()
        previous_status = (
            previous_status_obj.status_name if previous_status_obj else "offline"
        )

        # Safely increment ping counter
        self._ping_count += 1
        self._info["ping"] = self._ping_count

        # Fetch device info
        if not self._fetch_device_info():
            self._handle_unreachable_state(previous_status)
            raise ScanException(f"Failed to fetch device info from {self._ip}")

        new_status = self._info.get("status", "offline")

        if previous_status != new_status:
            self._update_device_status(new_status)

            # Clean up stream manager when device stops streaming
            if previous_status == "streaming" and new_status != "streaming":
                self._logger.info(
                    f"Device {self._id} stopped streaming (status changed from {previous_status} to {new_status})"
                )
                self.cleanup_stream_manager()

            # Check SSH key status when device becomes accessible
            # Only check when transitioning to an accessible state (not offline, unreached, or initialising)
            accessible_states = ["stopped", "running", "recording", "streaming", "busy"]
            if (
                new_status in accessible_states
                and previous_status not in accessible_states
            ):
                with self._lock:
                    self._info["ssh_key_installed"] = self.check_ssh_key_installed()
                    self._logger.debug(
                        f"SSH key status for {self._id}: {self._info.get('ssh_key_installed', False)}"
                    )

        # Handle device states
        if previous_status == "offline" and new_status != "offline":
            self._handle_device_coming_online()

        # Check if backup_filename from API response has changed
        # Note: _reorganize_experimental_info moves backup_filename to latest_cache
        current_backup_filename = self._info.get("backup_filename") or self._info.get(
            "latest_cache", {}
        ).get("backup_filename")
        previous_backup_filename = getattr(self, "_last_backup_filename", None)
        backup_filename_changed = (
            current_backup_filename != previous_backup_filename
            and current_backup_filename is not None
        )

        # Additional check: if backup_path contains a different timestamp than current backup_filename
        # This handles cases where the scanner missed the initial change
        current_backup_path = self._info.get("backup_path")
        backup_path_mismatch = False
        if current_backup_filename and current_backup_path:
            try:
                # Extract timestamp from backup_filename: "2025-07-24_10-32-01_..."
                backup_filename_timestamp = "_".join(
                    current_backup_filename.split("_")[:2]
                )
                # Check if backup_path contains the same timestamp
                backup_path_mismatch = (
                    backup_filename_timestamp not in current_backup_path
                )
                if backup_path_mismatch:
                    self._logger.debug(
                        f"Device {self._ip}: Backup path timestamp mismatch detected. "
                        f"Filename: {backup_filename_timestamp}, Path: {current_backup_path}"
                    )
            except (IndexError, AttributeError):
                pass

        # Update backup path if status changed, backup_path is None, backup_filename changed, or path mismatch
        if (
            previous_status != new_status
            or self._info.get("backup_path") is None
            or backup_filename_changed
            or backup_path_mismatch
        ):
            # Force recalculation if backup filename changed or path doesn't match
            force_recalc = backup_filename_changed or backup_path_mismatch
            if backup_path_mismatch:
                self._logger.info(
                    f"Device {self._ip}: Forcing backup path recalculation due to timestamp mismatch"
                )
            self._make_backup_path(force_recalculate=force_recalc)
            # Track the backup_filename used for this backup_path
            self._last_backup_filename = current_backup_filename

        # Reconcile run lifecycle every poll, not just on status changes — that
        # way an unreached/offline timeout fires even if status looks "stable".
        current_run_id = self._observed_current_run_id(new_status)
        self._reconcile_run_state(new_status, current_run_id, previous_status)

        # Check for storage warnings
        self._check_storage_warnings()

        # Periodic SSH key retry for devices that missed initial transfer
        accessible_states = ["stopped", "running", "recording", "streaming", "busy"]
        if (
            new_status in accessible_states
            and not self._info.get("ssh_key_installed", False)
            and time.time() - self._last_ssh_attempt > SSH_RETRY_INTERVAL
        ):
            self._last_ssh_attempt = time.time()
            self._logger.info(
                f"Retrying SSH key setup for {self._info.get('name', self._ip)}"
            )
            ssh_success = self.setup_ssh_authentication()
            with self._lock:
                self._info["ssh_key_installed"] = ssh_success

        # update comprehensive list of databases - this should not be served here
        self._info.update({"databases": self.databases_info()})

    def _reorganize_experimental_info(self, new_info: dict):
        """
        Reorganize experimental_info into nested structure with current and previous.

        Structure:
        experimental_info: {
            current: {}, // Current experiment info (when running/recording)
            previous: {} // Previous experiment info (when stopped)
        }
        """
        # Get incoming experimental_info from device
        incoming_experimental_info = new_info.get("experimental_info", {})

        # Handle legacy previous_* fields - migrate them to nested structure
        legacy_previous_fields = {}
        for field_name in [
            "previous_date_time",
            "previous_backup_filename",
            "previous_user",
            "previous_location",
        ]:
            if field_name in new_info:
                # Map legacy field names to new structure
                field_key = field_name.replace("previous_", "")
                # Map 'date_time' instead of 'time'
                if field_key == "date_time":
                    field_key = "date_time"
                legacy_previous_fields[field_key] = new_info[field_name]
                # Remove legacy field from new_info
                del new_info[field_name]

        # Handle interactor field - move to experimental_info.current (it's part of experimental setup)
        interactor_data = {}
        if "interactor" in new_info:
            interactor_data["interactor"] = new_info["interactor"]
            # Remove from top-level new_info - will be added to current experimental_info
            del new_info["interactor"]

        # Handle cache-derived fields - move them to latest_cache section for better organization
        cache_fields = [
            "result_writer_type",
            "sqlite_source_path",
            "cache_file",
            "cached_run_id",
            "backup_filename",
        ]
        cache_field_data = {}
        for field_name in cache_fields:
            if field_name in new_info:
                cache_field_data[field_name] = new_info[field_name]
                # Remove from top-level new_info - will be added to latest_cache section
                del new_info[field_name]

        # Get current device status
        current_status = new_info.get("status", "offline")
        previous_status = self._info.get("status", "offline")

        # Get existing nested structure or initialize
        existing_nested = self._info.get("experimental_info", {})
        if not isinstance(existing_nested, dict) or "current" not in existing_nested:
            # Initialize nested structure
            nested_experimental_info = {"current": {}, "previous": {}}
        else:
            # Use existing nested structure
            nested_experimental_info = {
                "current": existing_nested.get("current", {}),
                "previous": existing_nested.get("previous", {}),
            }

        # Handle incoming experimental_info format - check if it's already nested
        if incoming_experimental_info and isinstance(incoming_experimental_info, dict):
            if (
                "current" in incoming_experimental_info
                and "previous" in incoming_experimental_info
            ):
                # Already in nested format - merge with existing
                nested_experimental_info["current"] = incoming_experimental_info.get(
                    "current", {}
                )
                if incoming_experimental_info.get("previous"):
                    nested_experimental_info["previous"].update(
                        incoming_experimental_info["previous"]
                    )
                # Add any legacy fields to previous
                if legacy_previous_fields:
                    nested_experimental_info["previous"].update(legacy_previous_fields)
                # Update the new_info with nested structure and return early
                new_info["experimental_info"] = nested_experimental_info
                return
            else:
                # Legacy flat format - treat as current experimental_info
                pass  # Continue with existing logic below

        # Add any legacy previous fields to the previous structure
        if legacy_previous_fields:
            nested_experimental_info["previous"].update(legacy_previous_fields)
            self._logger.debug(
                f"Device {self._ip}: Migrated legacy previous_* fields to nested structure"
            )

        # Determine what to do with the incoming experimental_info
        if incoming_experimental_info and not (
            "current" in incoming_experimental_info
            and "previous" in incoming_experimental_info
        ):
            # Device has experimental info
            if current_status in ["running", "recording", "streaming", "initialising"]:
                # Device is active - incoming info becomes current
                nested_experimental_info["current"] = incoming_experimental_info
                # Add interactor data to current experimental_info if present
                if interactor_data:
                    nested_experimental_info["current"].update(interactor_data)
                self._logger.debug(
                    f"Device {self._ip}: Updated current experimental_info for active session"
                )

            elif current_status == "stopped" and previous_status in [
                "running",
                "recording",
                "streaming",
            ]:
                # Device just stopped - move current to previous, clear current
                if nested_experimental_info["current"]:
                    nested_experimental_info["previous"] = nested_experimental_info[
                        "current"
                    ].copy()
                    self._logger.debug(
                        f"Device {self._ip}: Moved experimental_info to previous after stopping"
                    )
                nested_experimental_info["current"] = {}

            else:
                # Device is in other state - keep as current for now
                nested_experimental_info["current"] = incoming_experimental_info
                # Add interactor data to current experimental_info if present
                if interactor_data:
                    nested_experimental_info["current"].update(interactor_data)

        else:
            # No incoming experimental_info
            if current_status == "stopped" and previous_status in [
                "running",
                "recording",
                "streaming",
            ]:
                # Device stopped and lost experimental_info - move current to previous
                if nested_experimental_info["current"]:
                    nested_experimental_info["previous"] = nested_experimental_info[
                        "current"
                    ].copy()
                    self._logger.debug(
                        f"Device {self._ip}: Moved experimental_info to previous after session ended"
                    )
                nested_experimental_info["current"] = {}

            elif (
                current_status in ["running", "recording", "streaming"]
                and nested_experimental_info["current"]
            ):
                # Device is active but no experimental_info - keep existing current
                # Add interactor data to current experimental_info if present
                if interactor_data:
                    nested_experimental_info["current"].update(interactor_data)
                self._logger.debug(
                    f"Device {self._ip}: Keeping existing current experimental_info for active session"
                )
                pass

            else:
                # Clear current if device is not active
                nested_experimental_info["current"] = {}

        # Update the new_info with nested structure
        new_info["experimental_info"] = nested_experimental_info

        # Add cache-derived fields to latest_cache section
        if cache_field_data:
            new_info["latest_cache"] = cache_field_data
            self._logger.debug(
                f"Device {self._ip}: Organized cache-derived fields in latest_cache section"
            )

    def _fetch_device_info(self) -> bool:
        """Fetch latest device information."""
        try:
            if not self._id:
                self._update_id()

            _data_url = (
                f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['data']}/{self._id}"
            )
            new_info = self._get_json(_data_url)

            with self._lock:
                # Reorganize experimental_info before updating
                self._reorganize_experimental_info(new_info)

                # Update device info with reorganized data
                self._info.update(new_info)

                self._info["last_seen"] = time.time()

                # Update logger name if we have a valid device name
                self._update_logger_name()

            return True

        except ScanException as e:
            try:
                did = self._get_json(self._id_url, timeout=5)
                if did:
                    with self._lock:
                        self._info["last_seen"] = time.time()
                        self._update_device_status("busy")

                self._logger.warning(
                    f"The device is online and responding but cannot communicate its status. Flagged as busy. {e}"
                )
                return False

            except ScanException as inner_e:
                # Device doesn't respond to either /data/<id> or /id - mark for offline transition
                current_status = self.get_device_status()
                if current_status and current_status.status_name == "busy":
                    # If previously busy, transition to unreached to start timeout countdown
                    self._logger.warning(
                        f"Busy device {self._id} no longer responding to any endpoint. Starting offline transition. {inner_e}"
                    )
                    self._handle_unreachable_state("busy")
                else:
                    self._logger.warning(f"Error fetching device info: {inner_e}")
                return False

    def _update_logger_name(self):
        """Update logger name to use proper device name if available."""
        device_name = self._info.get("name", "")

        # Only update if we have a valid device name and it's different from current
        if device_name and device_name != "unknown_name":
            new_logger_name = f"{device_name}"
            current_logger_name = self._logger.name

            # Only update if the name has changed
            if new_logger_name != current_logger_name:
                self._logger = logging.getLogger(new_logger_name)
                # Ensure updated logger inherits proper level
                if self._logger.level == logging.NOTSET:
                    self._logger.setLevel(logging.getLogger().level or logging.INFO)
                self._logger.debug(
                    f"Updated logger name from {current_logger_name} to {new_logger_name}"
                )

    def _handle_unreachable_state(self, previous_status: str):
        """Promote / demote the device status when polling fails.

        Pure UI-side concern. Alert decisions live in ``_reconcile_run_state``.

        * busy device exceeding ``busy_timeout_minutes`` -> offline.
        * busy device under that timeout -> stay busy.
        * unreached device crossing ``unreachable_timeout_minutes`` or polling
          backoff -> offline.
        * unreached device under that timeout -> stay unreached.
        * already-offline device -> stay offline (no flap back to unreached).
        * anything else -> first transition to unreached.
        """
        current_status = self.get_device_status()
        alert_config = self._config.get_custom("alerts") or {}
        unreachable_timeout = alert_config.get("unreachable_timeout_minutes", 20)
        busy_timeout = alert_config.get("busy_timeout_minutes", 10)

        if current_status.status_name == "busy":
            if current_status.is_timeout_exceeded(busy_timeout):
                self._logger.info(
                    f"Device {self._id} busy timeout exceeded ({busy_timeout}m), marking offline"
                )
                self._update_device_status("offline")
                self._edb.updateEthoscopes(ethoscope_id=self._id, status="offline")
            else:
                self._logger.info(
                    f"Device {self._id} busy for {current_status.get_age_minutes():.1f}m (timeout: {busy_timeout}m)"
                )
                self._edb.updateEthoscopes(ethoscope_id=self._id, status="busy")
            return

        if current_status.status_name == "unreached":
            crossed_error_threshold = (
                self._consecutive_errors >= self._max_consecutive_errors
            )
            timeout_exceeded = current_status.is_timeout_exceeded(unreachable_timeout)
            if crossed_error_threshold or timeout_exceeded:
                reason = (
                    "max_errors_reached"
                    if crossed_error_threshold
                    else "unreachable_timeout"
                )
                self._logger.info(f"Device {self._id} marked offline ({reason})")
                self._update_device_status("offline")
                self._edb.updateEthoscopes(ethoscope_id=self._id, status="offline")
            return

        if previous_status == "offline":
            # Already offline and still unreachable — stay there. Without this,
            # the next poll would re-create "unreached" and the pair would
            # ping-pong every cycle.
            return

        self._logger.info(
            f"Device {self._id} becoming unreachable (was {previous_status})"
        )
        self._update_device_status("unreached")
        if previous_status == "stopped":
            self._edb.updateEthoscopes(ethoscope_id=self._id, status="offline")
        else:
            self._edb.updateEthoscopes(ethoscope_id=self._id, status="unreached")
        self._reset_info()

    def _handle_device_coming_online(self):
        """Handle device coming online with SSH key setup."""
        device_name = self._info.get("name", "")
        if "ETHOSCOPE_OOO" in device_name.upper():
            return

        # Wait 10 seconds for device to stabilize before attempting SSH operations
        self._logger.debug(
            f"Device {device_name} coming online, waiting 10s for stabilization"
        )
        time.sleep(10)

        try:
            machine_info_dict = self.machine_info()
            machine_info = ""

            if "kernel" in machine_info_dict and "pi_version" in machine_info_dict:
                machine_info = f"{machine_info_dict['kernel']} on pi{machine_info_dict['pi_version']}"

            self._edb.updateEthoscopes(
                ethoscope_id=self._id,
                ethoscope_name=device_name,
                last_ip=self._ip,
                machineinfo=machine_info,
            )

            # Auto-transfer SSH key if not already installed
            ssh_key_installed = self._info.get("ssh_key_installed", False)
            if not ssh_key_installed:
                self._logger.info(
                    f"SSH key not installed on {device_name}, attempting auto-transfer"
                )
                self._last_ssh_attempt = time.time()
                ssh_success = self.setup_ssh_authentication()

                with self._lock:
                    if ssh_success:
                        self._logger.info(
                            f"SSH key successfully installed on {device_name}"
                        )
                        self._info["ssh_key_installed"] = True
                    else:
                        self._logger.warning(
                            f"Failed to install SSH key on {device_name}. Will retry on next status change."
                        )
                        self._info["ssh_key_installed"] = False
            else:
                self._logger.debug(
                    f"SSH key already installed on {device_name}, skipping auto-transfer"
                )

        except Exception as e:
            self._logger.error(f"Error updating device info: {e}")

    # ------------------------------------------------------------------ run state
    #
    # Alerting is driven by the lifecycle of a *run*, not by chains of device
    # status transitions. The model:
    #
    #   1. The first time we observe the device in an ACTIVE state (running/
    #      recording/streaming) with a run_id X, we set ``_active_run_id = X``
    #      and ``addRun(X)`` if it isn't already in the DB.
    #
    #   2. While ``_active_run_id == X`` and the device keeps reporting an
    #      active state with the same run_id, nothing happens.
    #
    #   3. The moment the device reports a non-active state (stopped/offline),
    #      OR has been unreached/busy for longer than the configured timeout,
    #      we finalise X. The termination_reason is ``user_stop`` if a recent
    #      ``device_interventions`` row exists for this device, otherwise
    #      ``crash`` (for an immediate stop) or ``unreached_timeout`` (for the
    #      timeout path). Alerts fire only for the latter two reasons.
    #
    #   4. If the device begins reporting an active state with a DIFFERENT
    #      run_id, the old one is finalised as ``superseded`` (no alert) and
    #      the new one starts the cycle.
    #
    # Key non-properties of this model that the previous implementation got
    # wrong:
    #   - A device that was never observed active (e.g. idle the whole time
    #     and momentarily unreachable during a firmware update) has
    #     ``_active_run_id == None`` and therefore CANNOT fire an alert.
    #     This is the regression case behind the 11 false-positive emails on
    #     2026-05-15 — the old "any system-triggered transition to stopped"
    #     branch fired without ever needing to see the device run.
    #   - Run state is tied to a specific scanner session. A run that was
    #     active when the scanner shut down has its row left open in the DB;
    #     when the scanner restarts and re-observes the device active, the
    #     same run_id is reattached. If the run silently expired across the
    #     restart, ``_active_run_id`` stays ``None`` and no alert fires for
    #     events we did not observe.
    #   - The grace window is a single configurable knob
    #     ``user_action_grace_seconds`` (default 600). No more separate
    #     "user_action_timeout_seconds", "graceful_shutdown_grace_minutes",
    #     and in-memory ``_last_user_action`` to keep in sync.

    def _observed_current_run_id(self, status: str) -> str | None:
        """Return the run_id the device claims to be tracking *right now*,
        only if its status genuinely puts it in an active tracking state.

        Trusting ``experimental_info.current.run_id`` while the device reports
        ``stopped`` was the source of the stale-run-id bug: the device kept
        leaking a previous run's id into ``current`` even after it stopped.
        Status is the canonical signal — if it isn't an active state, there
        is no current run.
        """
        if status not in DeviceStatus.ACTIVE_TRACKING_STATUSES:
            return None
        current = self._info.get("experimental_info", {}).get("current", {}) or {}
        return current.get("run_id") or None

    def _user_action_grace_seconds(self) -> int:
        cfg = self._config.get_custom("alerts") or {}
        # Default 10 minutes — bigger than the typical firmware-update window
        # (~2-3 min) and smaller than the unreachable timeout (20 min) so a
        # genuinely dead Pi after a reboot still alerts.
        return int(cfg.get("user_action_grace_seconds", 600))

    def _finalise_active_run(self, reason: str):
        """Close the currently active run in the DB and emit alert if needed."""
        run_id = self._active_run_id
        if run_id is None:
            return
        self._active_run_id = None

        try:
            self._edb.stopRun(run_id=run_id, termination_reason=reason)
        except Exception as e:
            self._logger.error(f"Failed to stop run {run_id}: {e}")
            return

        self._logger.info(f"Run {run_id} finalised: {reason}")
        if reason not in ("crash", "unreached_timeout"):
            return

        # Fire the alert. ``send_device_stopped_alert`` is itself idempotent
        # (alert_logs keyed on device_id+alert_type+run_id) so a transient
        # observation we somehow processed twice can't double-send.
        try:
            device_name = self._info.get("name", self._id)
            last_seen = datetime.datetime.fromtimestamp(
                self._info.get("last_seen", time.time())
            )
            self._logger.info(
                f"Sending device stopped alert for {device_name} "
                f"(run_id: {run_id}, reason: {reason})"
            )
            self._notification_manager.send_device_stopped_alert(
                device_id=self._id,
                device_name=device_name,
                run_id=run_id,
                last_seen=last_seen,
            )
        except Exception as e:
            self._logger.error(f"Error dispatching stopped alert for {run_id}: {e}")

    def _reconcile_run_state(
        self, status: str, current_run_id: str | None, previous_status: str
    ):
        """Drive the run lifecycle from a poll observation.

        Called every poll. Cheap when nothing changes.
        """
        is_active = status in DeviceStatus.ACTIVE_TRACKING_STATUSES

        if is_active and current_run_id:
            # Reset unreached timer; we have a fresh successful contact.
            self._unreached_since = None

            if self._active_run_id != current_run_id:
                if self._active_run_id is not None:
                    # Different run started without us seeing the old one stop.
                    # Close the orphan, then attach to the new run.
                    self._logger.info(
                        f"Active run changed: {self._active_run_id} -> {current_run_id}"
                    )
                    self._finalise_active_run("superseded")
                self._active_run_id = current_run_id
                self._ensure_run_in_db(current_run_id, previous_status)
            return

        if status == "stopped":
            # The device explicitly says it's idle. If we had an active run,
            # decide whether the stop was user-initiated.
            self._unreached_since = None
            if self._active_run_id is not None:
                grace = self._user_action_grace_seconds()
                if self._edb.recent_intervention(self._id, within_seconds=grace):
                    self._finalise_active_run("user_stop")
                else:
                    self._finalise_active_run("crash")
            return

        if status in ("unreached", "offline", "busy"):
            # Start (or continue) the unreachable timer. Only finalise once we
            # have been unreached for longer than the configured timeout —
            # transient blips do not close a live run.
            if self._unreached_since is None:
                self._unreached_since = time.time()
            if self._active_run_id is not None:
                cfg = self._config.get_custom("alerts") or {}
                timeout_minutes = int(cfg.get("unreachable_timeout_minutes", 20))
                if time.time() - self._unreached_since > timeout_minutes * 60:
                    grace = self._user_action_grace_seconds()
                    if self._edb.recent_intervention(self._id, within_seconds=grace):
                        self._finalise_active_run("user_stop")
                    else:
                        self._finalise_active_run("unreached_timeout")
            return

        # initialising / stopping / online — no run lifecycle event.

    def _ensure_run_in_db(self, run_id: str, previous_status: str):
        """Insert a runs row for ``run_id`` if it isn't already there.

        Idempotent: re-attaching to a run we started in a previous scanner
        session is a no-op.
        """
        try:
            existing = self._edb.getRun(run_id)
        except Exception:
            existing = []
        if existing:
            return

        current = self._info.get("experimental_info", {}).get("current", {}) or {}
        user_name = current.get("name", "")
        location = current.get("location", "")
        self._logger.info(
            f"Recording new run {run_id} for device {self._id} "
            f"(was {previous_status})"
        )
        try:
            self._edb.addRun(
                run_id=run_id,
                experiment_type="tracking",
                ethoscope_name=self._info.get("name", ""),
                ethoscope_id=self._id,
                username=user_name,
                user_id="",
                location=location,
                alert=True,
                comments="",
                experimental_data=self._info.get("backup_path", ""),
            )
        except Exception as e:
            self._logger.error(f"Failed to addRun({run_id}): {e}")

    def _check_storage_warnings(self):
        """Check for storage warnings and send alerts if necessary."""
        try:
            # Get storage information from device
            machine_info = self._info.get("machine_info", {})

            # Check for disk usage information
            disk_usage = machine_info.get("disk_usage", {})
            if not disk_usage:
                return

            # Get alert threshold from configuration
            alert_config = self._config.get_custom("alerts") or {}
            threshold = alert_config.get("storage_warning_threshold", 80)

            # Check each mounted filesystem
            for _mount_point, usage_info in disk_usage.items():
                if isinstance(usage_info, dict):
                    used_percent = usage_info.get("used_percent", 0)
                    available_space = usage_info.get("available", "unknown")

                    if used_percent >= threshold:
                        device_name = self._info.get("name", self._id)

                        # Format available space for display
                        if isinstance(available_space, (int, float)):
                            available_space = f"{available_space / (1024**3):.1f} GB"

                        # Send storage warning alert
                        success = self._notification_manager.send_storage_warning_alert(
                            device_id=self._id,
                            device_name=device_name,
                            storage_percent=used_percent,
                            available_space=str(available_space),
                        )
                        if not success:
                            self._logger.error(
                                f"Failed to send storage warning alert for {device_name}"
                            )

        except Exception as e:
            self._logger.error(f"Error checking storage warnings: {e}")

    def _make_backup_path(
        self, force_recalculate: bool = False, service_type: str = "auto"
    ):
        """
        Creates the full path for the backup file, gathering info from the ethoscope.
        Now supports service-type awareness to prevent backup collisions.

        Args:
            timeout: Request timeout
            force_recalculate: Force recalculation of backup path
            service_type: Type of backup service ('mariadb', 'sqlite', 'auto')

        The full backup_path will look something like:
        /ethoscope_data/results/0256424ac3f545b6b3c687723085ffcb/ETHOSCOPE_025/2025-06-13_16-05-37/2025-06-13_16-05-37_0256424ac3f545b6b3c687723085ffcb.db
        """
        try:
            # Skip if backup path is already set and valid (unless forced)
            if self._info.get("backup_path") is not None and not force_recalculate:
                return

            output_db_file = None
            backup_filename = None

            # Determine which backup filename to use based on service type
            if service_type == "mariadb":
                backup_filename = self._get_backup_filename_for_db_type("MariaDB")
            elif service_type == "sqlite":
                backup_filename = self._get_backup_filename_for_db_type("SQLite")
            else:
                # Auto mode: use the appropriate backup filename based on database type
                backup_filename = self._get_appropriate_backup_filename()

            if backup_filename:
                try:
                    fname, _ = os.path.splitext(backup_filename)
                    parts = fname.split("_")
                    if len(parts) >= 3:
                        backup_date = parts[0]
                        backup_time = parts[1]
                        etho_id = "_".join(parts[2:])

                        output_db_file = os.path.join(
                            self._results_dir,
                            etho_id,
                            self._info["name"],
                            f"{backup_date}_{backup_time}",
                            backup_filename,
                        )
                        self._logger.info(
                            f"Created {service_type} backup path: {output_db_file}"
                        )
                    else:
                        self._logger.error(
                            f"Invalid backup filename format: {backup_filename}"
                        )
                        output_db_file = None
                except Exception as e:
                    self._logger.error(
                        f"Error parsing backup filename '{backup_filename}': {e}"
                    )
                    output_db_file = None
            else:
                # self._logger.warning(f"No backup filename available for {service_type} backup")
                output_db_file = None

            self._info["backup_path"] = output_db_file

        except Exception as e:
            self._logger.error(f"Error creating backup path: {e}")
            self._info["backup_path"] = None

    def _get_backup_filename_for_db_type(self, db_type: str) -> str:
        """Get backup filename for a specific database type.

        Args:
            db_type: Database type ("MariaDB" or "SQLite")

        Returns:
            str: Backup filename or None if not found
        """
        try:
            # Check new nested databases structure first
            databases = self._info.get("databases", {})
            db_type_databases = databases.get(db_type, {})

            if db_type_databases:
                # Pick the most recent database by date timestamp
                best = max(
                    db_type_databases.values(),
                    key=lambda info: info.get("date", 0),
                )
                backup_filename = best.get("backup_filename")
                if backup_filename:
                    return backup_filename

            # Fallback to old structure for backward compatibility
            database_info = self.databases_info()
            db_type_key = db_type.lower()  # Convert to lowercase for old structure
            db_type_info = database_info.get(db_type_key, {})
            if db_type_info.get("exists", False):
                db_type_current = db_type_info.get("current", {})
                return db_type_current.get("backup_filename")

            return None
        except Exception as e:
            self._logger.error(f"Error getting {db_type} backup filename: {e}")
            return None

    def _get_appropriate_backup_filename(self) -> str:
        """Get the appropriate backup filename based on the active database type."""
        try:
            # FIRST PRIORITY: Use the backup_filename from the ethoscope API response
            # This field contains the current experiment's backup filename
            # Note: _reorganize_experimental_info moves this to latest_cache
            backup_filename = self._info.get("backup_filename") or self._info.get(
                "latest_cache", {}
            ).get("backup_filename")
            if backup_filename:
                self._logger.debug(
                    f"Device {self._ip}: Using current backup_filename from API: {backup_filename}"
                )
                return backup_filename

            # SECOND PRIORITY: Try to determine the active database type from experimental_info
            experimental_info_nested = self._info.get("experimental_info", {})
            current_experimental_info = experimental_info_nested.get("current", {})
            if "selected_options" in current_experimental_info:
                try:
                    selected_options_str = current_experimental_info["selected_options"]
                    if "SQLiteResultWriter" in selected_options_str:
                        self._logger.debug(
                            f"Device {self._ip}: Determined active database type: SQLite from experimental_info"
                        )
                        sqlite_filename = self._get_backup_filename_for_db_type(
                            "SQLite"
                        )
                        if sqlite_filename:
                            return sqlite_filename
                    elif "ResultWriter" in selected_options_str:
                        self._logger.debug(
                            f"Device {self._ip}: Determined active database type: MariaDB from experimental_info"
                        )
                        mariadb_filename = self._get_backup_filename_for_db_type(
                            "MariaDB"
                        )
                        if mariadb_filename:
                            return mariadb_filename
                except (KeyError, TypeError) as e:
                    self._logger.debug(
                        f"Device {self._ip}: Could not parse selected_options from experimental_info: {e}"
                    )

            # THIRD PRIORITY: Fallback to old structure for backward compatibility
            database_info = self.databases_info()
            active_type = database_info.get("active_type", "none")

            if active_type == "mariadb":
                self._logger.debug(
                    f"Device {self._ip}: Using active_type MariaDB from database_info"
                )
                return self._get_backup_filename_for_db_type("MariaDB")
            elif active_type == "sqlite":
                self._logger.debug(
                    f"Device {self._ip}: Using active_type SQLite from database_info"
                )
                return self._get_backup_filename_for_db_type("SQLite")

            # FOURTH PRIORITY: Check databases structure for active database
            databases = self._info.get("databases", {})

            # Look for active databases by checking db_status = "tracking"
            # If multiple databases have "tracking" status (e.g. old unfinalised ones),
            # pick the most recent one by date timestamp in the filename
            for db_type in ["SQLite", "MariaDB"]:
                db_type_databases = databases.get(db_type, {})
                tracking_candidates = []
                for _db_name, db_info in db_type_databases.items():
                    if db_info.get("db_status") == "tracking":
                        backup_filename = db_info.get("backup_filename")
                        if backup_filename:
                            tracking_candidates.append(
                                (db_info.get("date", 0), backup_filename)
                            )
                if tracking_candidates:
                    # Sort by date descending, pick the most recent
                    tracking_candidates.sort(key=lambda x: x[0], reverse=True)
                    best_filename = tracking_candidates[0][1]
                    self._logger.debug(
                        f"Device {self._ip}: Found active {db_type} database: {best_filename}"
                        + (
                            f" (selected from {len(tracking_candidates)} tracking databases)"
                            if len(tracking_candidates) > 1
                            else ""
                        )
                    )
                    return best_filename

            # FIFTH PRIORITY: Try SQLite first in the existence check (reverse previous priority)
            # This is because SQLite is more commonly used for new experiments
            if databases.get("SQLite"):
                self._logger.debug(
                    f"Device {self._ip}: Found SQLite database, using as fallback"
                )
                sqlite_filename = self._get_backup_filename_for_db_type("SQLite")
                if sqlite_filename:
                    return sqlite_filename

            # Try MariaDB as last resort
            if databases.get("MariaDB"):
                self._logger.debug(
                    f"Device {self._ip}: Found MariaDB database, using as fallback"
                )
                mariadb_filename = self._get_backup_filename_for_db_type("MariaDB")
                if mariadb_filename:
                    return mariadb_filename

            # FINAL FALLBACK: Use previous_backup_filename for stopped devices
            if (
                self._device_status.status_name == "stopped"
                and "previous_backup_filename" in self._info
                and self._info["previous_backup_filename"]
            ):
                self._logger.debug(
                    f"Device {self._ip}: Using previous_backup_filename for stopped device"
                )
                return self._info["previous_backup_filename"]

            self._logger.warning(
                f"Device {self._ip}: No backup filename could be determined"
            )
            return None
        except Exception as e:
            self._logger.error(f"Error getting appropriate backup filename: {e}")
            return None

    def setup_ssh_authentication(self) -> bool:
        """
        Setup SSH key authentication for passwordless connection to ethoscope.

        Uses sshpass to copy the node's SSH public key to the ethoscope device
        using the ethoscope user with password 'ethoscope'.

        Returns:
            bool: True if SSH key setup was successful, False otherwise
        """
        try:
            # Get SSH key paths
            keys_dir = os.path.join(self._config_dir, "keys")
            private_key_path, public_key_path = get_ssh_key_paths(keys_dir)

            # Use sshpass with ssh-copy-id to setup passwordless authentication
            cmd = [
                "sshpass",
                "-p",
                "ethoscope",
                "ssh-copy-id",
                "-i",
                public_key_path,
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",  # Avoid stale host key issues
                "-o",
                "ConnectTimeout=10",
                f"ethoscope@{self._ip}",
            ]

            self._logger.info(
                f"Setting up SSH key authentication for ethoscope@{self._ip}"
            )

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                self._logger.info(
                    f"SSH key authentication setup successful for {self._ip}"
                )
                return True
            else:
                self._logger.error(
                    f"SSH key setup failed for {self._ip}: {result.stderr}"
                )
                return False

        except subprocess.TimeoutExpired:
            self._logger.error(f"SSH key setup timed out for {self._ip}")
            return False
        except FileNotFoundError:
            self._logger.error(
                "sshpass command not found. Please install sshpass package"
            )
            return False
        except Exception as e:
            self._logger.error(
                f"Failed to setup SSH key authentication for {self._ip}: {e}"
            )
            return False

    def check_ssh_key_installed(self) -> bool:
        """
        Check if node's SSH key is installed on ethoscope for passwordless access.

        Tests SSH connection using BatchMode to disable password prompts.
        If the connection succeeds, passwordless SSH is configured correctly.

        Returns:
            bool: True if passwordless SSH works, False otherwise
        """
        try:
            # Get the private key path to explicitly test with the correct key
            keys_dir = os.path.join(self._config_dir, "keys")
            private_key_path = os.path.join(keys_dir, "id_rsa")

            # Test SSH connection without password using BatchMode
            cmd = [
                "ssh",
                "-i",
                private_key_path,  # Use the ethoscope key explicitly
                "-o",
                "BatchMode=yes",  # Disable password prompts
                "-o",
                "StrictHostKeyChecking=no",  # Auto-accept host keys
                "-o",
                "UserKnownHostsFile=/dev/null",  # Avoid stale host key issues
                "-o",
                "ConnectTimeout=5",  # 5 second timeout
                f"ethoscope@{self._ip}",
                "echo test",  # Simple command to test connection
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                self._logger.debug(
                    f"SSH key authentication working for ethoscope@{self._ip}"
                )
                return True
            else:
                self._logger.debug(
                    f"SSH key authentication not working for ethoscope@{self._ip}: {result.stderr.strip()}"
                )
                return False

        except subprocess.TimeoutExpired:
            self._logger.debug(f"SSH key check timed out for {self._ip}")
            return False
        except Exception as e:
            self._logger.debug(f"Error checking SSH key for {self._ip}: {e}")
            return False


class EthoscopeScanner(DeviceScanner):
    """Ethoscope-specific scanner with database integration."""

    SERVICE_TYPE = "_ethoscope._tcp.local."
    DEVICE_TYPE = "ethoscope"

    def __init__(
        self,
        device_refresh_period: float = 5,
        results_dir: str = "/ethoscope_data/results",
        device_class=Ethoscope,
        config_dir: str | None = None,
        config: EthoscopeConfiguration | None = None,
    ):
        super().__init__(device_refresh_period, device_class)
        self.results_dir = results_dir
        self.config_dir = config_dir or resolve_config_dir()
        self.config = config  # Store config to pass to devices
        self._edb = ExperimentalDB(self.config_dir)
        self.timestarted = (
            datetime.datetime.now()
        )  # Keep original name for compatibility

    def get_all_devices_info(
        self, include_inactive: bool = False
    ) -> dict[str, dict[str, Any]]:
        """Get device info including offline devices from database."""
        # Start with database devices
        try:
            db_devices = self._edb.getEthoscope("all", asdict=True)
            devices_info = {}

            for device_id, device_data in db_devices.items():
                # Skip devices with empty or invalid IDs
                if not device_id or device_id.strip() == "":
                    self._logger.debug("Skipping device with empty ID from database")
                    continue

                # Skip devices with no name or empty names unless they have valid IPs
                device_name = device_data.get("ethoscope_name", "").strip()
                device_ip = device_data.get("last_ip", "").strip()

                # Skip devices that have no meaningful identifying information
                if (not device_name or device_name.lower() in ["none", ""]) and (
                    not device_ip or device_ip.lower() in ["none", ""]
                ):
                    self._logger.debug(
                        f"Skipping device {device_id} with no name and no IP from database"
                    )
                    continue

                # Include device if it's active, or if include_inactive is True
                if device_data.get("active") == 1 or include_inactive:
                    devices_info[device_id] = {
                        "name": device_name,
                        "id": device_id,
                        # Reason: a stored NULL status would otherwise leak
                        # through .get()'s default; treat any falsy value as
                        # offline for DB-only devices.
                        "status": device_data.get("status") or "offline",
                        "ip": device_ip,
                        "last_ip": device_ip,
                        "time": device_data.get("last_seen", 0),
                        "active": device_data.get("active", 1),
                    }
        except Exception as e:
            self._logger.error(f"Error getting devices from database: {e}")
            devices_info = {}

        # Update with devices from scanner (includes offline)
        with self._lock:
            for device in self.devices:
                device_id = device.id()
                device_name = getattr(device, "name", "N/A")

                # Skip devices with empty or invalid IDs from scanner
                if not device_id or device_id.strip() == "":
                    self._logger.debug("Skipping scanner device with empty ID")
                    continue

                if device_name != "ETHOSCOPE_000":
                    info = device.info()

                    # Skip devices with no meaningful identifying information
                    scanner_name = info.get("name", "").strip()
                    scanner_ip = info.get("ip", "").strip()

                    if (
                        not scanner_name
                        or scanner_name.lower() in ["none", "", "n/a", "unknown_name"]
                    ) and (not scanner_ip or scanner_ip.lower() in ["none", ""]):
                        self._logger.debug(
                            f"Skipping scanner device {device_id} with no name and no IP"
                        )
                        continue

                    # Preserve name from database if device doesn't have a proper name
                    if device_id in devices_info:
                        db_name = devices_info[device_id].get("name", "")

                        # If scanner has no name or unknown name, preserve database name
                        if not scanner_name or scanner_name in [
                            "",
                            "unknown_name",
                            "N/A",
                        ]:
                            if db_name:
                                info["name"] = db_name

                        # Merge with existing database info, scanner info takes precedence except for name preservation above
                        devices_info[device_id].update(info)
                    else:
                        devices_info[device_id] = info
                else:
                    # Special case for ETHOSCOPE_000
                    devices_info[device_name] = device.info()

        return devices_info

    def add(
        self,
        ip: str,
        port: int = ETHOSCOPE_PORT,
        name: str | None = None,
        device_id: str | None = None,
        zcinfo: dict | None = None,
    ):
        """Add ethoscope with enhanced error handling and non-blocking initialization."""
        if not self._is_running:
            self._logger.warning(f"Cannot add device {ip}:{port} - scanner not running")
            return

        try:
            # Extract name and ID from zeroconf info
            if zcinfo:
                try:
                    name = zcinfo.get(b"MACHINE_NAME", b"").decode("utf-8") or name
                    device_id = (
                        zcinfo.get(b"MACHINE_ID", b"").decode("utf-8") or device_id
                    )
                except (AttributeError, UnicodeDecodeError):
                    if name:
                        try:
                            name_parts = name.split(".")[0].split("-")
                            if len(name_parts) == 2:
                                name, device_id = name_parts
                        except (IndexError, ValueError):
                            pass

            # Reason: mDNS service name embeds the device ID and is stable
            # across DHCP IP changes — match by it first so a re-announced
            # device updates its existing entry instead of being treated as
            # new (which would orphan the old entry at the stale IP).
            with self._lock:
                existing_device = self._find_device_by_zeroconf_name(name)
                if existing_device is not None and existing_device.ip() != ip:
                    self._logger.info(
                        f"Ethoscope {name} re-announced at new address "
                        f"{ip}:{port} (was {existing_device.ip()}:{existing_device._port})"
                    )
                    existing_device._update_address(ip, port)
                    with existing_device._lock:
                        existing_device._update_device_status("offline")
                        existing_device._info.update({"last_seen": time.time()})
                    return

            # Check if device already exists by IP (more immediate than waiting for ID)
            with self._lock:
                for existing_device in self.devices:
                    if existing_device.ip() == ip:
                        device_status = existing_device._device_status.status_name
                        prev_errors = existing_device._consecutive_errors

                        self._logger.info(
                            f"Ethoscope at {ip} already exists "
                            f"(status: {device_status}, errors: {prev_errors}), "
                            f"updating zeroconf info"
                        )

                        if hasattr(existing_device, "zeroconf_name"):
                            existing_device.zeroconf_name = name

                        # Reset error state so the next poll fires immediately
                        existing_device.reset_error_state()

                        # Force ID update to handle device renaming (ETHOSCOPE_000 -> new name)
                        # This is critical when devices are renamed via webUI
                        try:
                            old_id = existing_device.id()
                            existing_device._update_id()
                            new_id = existing_device.id()

                            if old_id != new_id:
                                self._logger.info(
                                    f"Device at {ip} ID changed from '{old_id}' to '{new_id}' (device was renamed)"
                                )
                                # Update database entry for the new device ID
                                self._handle_device_id_change(
                                    existing_device, old_id, new_id
                                )
                            else:
                                self._logger.debug(
                                    f"Device at {ip} ID unchanged: {new_id}"
                                )

                        except Exception as e:
                            self._logger.warning(
                                f"Failed to update ID for device at {ip}: {e}"
                            )

                        # Explicitly reset status to allow device info to be updated
                        with existing_device._lock:
                            existing_device._update_device_status("offline")
                            existing_device._info.update({"last_seen": time.time()})

                        return

            # Create device with minimal blocking
            with self._lock:
                try:
                    device_kwargs = {
                        "ip": ip,
                        "port": port,
                        "refresh_period": self.device_refresh_period,
                        "results_dir": self.results_dir,
                    }

                    # Only add config_dir if the device class supports it
                    if hasattr(self, "config_dir"):
                        import inspect

                        sig = inspect.signature(self._device_class.__init__)
                        if "config_dir" in sig.parameters:
                            device_kwargs["config_dir"] = self.config_dir

                    # Add config parameter if supported to avoid duplicate configuration loading
                    if hasattr(self, "config") and self.config is not None:
                        import inspect

                        sig = inspect.signature(self._device_class.__init__)
                        if "config" in sig.parameters:
                            device_kwargs["config"] = self.config

                    device = self._device_class(**device_kwargs)

                    if hasattr(device, "zeroconf_name"):
                        device.zeroconf_name = name

                    # Start the device thread immediately (don't wait for ID)
                    device.start()
                    self.devices.append(device)

                    # Log with available information
                    display_id = device_id or "pending"
                    self._logger.info(
                        f"Added ethoscope {name} (ID: {display_id}) at {ip}:{port}"
                    )

                except Exception as e:
                    self._logger.error(
                        f"Error creating ethoscope device at {ip}:{port}: {e}"
                    )
                    # Don't re-raise, just log the error to avoid blocking other discoveries

        except Exception as e:
            self._logger.error(f"Error in add method for {ip}:{port}: {e}")

    def _handle_device_id_change(self, device: "Ethoscope", old_id: str, new_id: str):
        """Handle database updates when a device ID changes (e.g., ETHOSCOPE_000 -> new name)."""
        try:
            device_name = device.info().get("name", "")
            device_ip = device.ip()

            # Log the device renaming
            self._logger.info(
                f"Handling device ID change: {old_id} -> {new_id} (name: {device_name}, IP: {device_ip})"
            )

            # If old device was ETHOSCOPE_000, it might not be in database yet
            if old_id == "ETHOSCOPE_000" or not old_id:
                self._logger.info(
                    f"Device {new_id} was previously ETHOSCOPE_000 or had empty ID, creating new database entry"
                )
                # Just update/create entry for new ID
                self._edb.updateEthoscopes(
                    ethoscope_id=new_id,
                    ethoscope_name=device_name,
                    last_ip=device_ip,
                    status="offline",  # Will be updated by normal scanning
                )
            else:
                # Handle actual ID change from one real ID to another
                try:
                    # Check if old device exists in database
                    old_device_data = self._edb.getEthoscope(old_id, asdict=True)
                    if old_device_data and old_id in old_device_data:
                        self._logger.info(
                            f"Retiring old device entry {old_id} and creating new entry {new_id}"
                        )
                        # Retire old device
                        self._edb.updateEthoscopes(ethoscope_id=old_id, active=0)

                        # Create new device entry, preserving relevant info from old entry
                        old_device_data[old_id]
                        self._edb.updateEthoscopes(
                            ethoscope_id=new_id,
                            ethoscope_name=device_name,
                            last_ip=device_ip,
                            status="offline",
                            comments=f"Renamed from {old_id}",
                        )
                    else:
                        # Old device not in database, just create new entry
                        self._logger.info(
                            f"Old device {old_id} not found in database, creating new entry for {new_id}"
                        )
                        self._edb.updateEthoscopes(
                            ethoscope_id=new_id,
                            ethoscope_name=device_name,
                            last_ip=device_ip,
                            status="offline",
                        )
                except Exception as db_error:
                    self._logger.warning(
                        f"Error handling old device {old_id} in database: {db_error}"
                    )
                    # Still create entry for new device
                    self._edb.updateEthoscopes(
                        ethoscope_id=new_id,
                        ethoscope_name=device_name,
                        last_ip=device_ip,
                        status="offline",
                    )

        except Exception as e:
            self._logger.error(
                f"Error handling device ID change from {old_id} to {new_id}: {e}"
            )

    def retire_device(self, device_id: str, active: int = 0) -> dict[str, Any]:
        """Retire device by updating database status."""
        try:
            self._edb.updateEthoscopes(ethoscope_id=device_id, active=active)
            updated_data = self._edb.getEthoscope(device_id, asdict=True)[device_id]
            return {
                "id": updated_data["ethoscope_id"],
                "active": updated_data["active"],
            }
        except Exception as e:
            self._logger.error(f"Error retiring device {device_id}: {e}")
            raise
