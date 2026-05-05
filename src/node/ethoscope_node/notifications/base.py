#!/usr/bin/env python

import datetime
import json
import logging
import time
from typing import Any

import requests

from ..utils.configuration import EthoscopeConfiguration
from ..utils.etho_db import ExperimentalDB

# A run that's still active stores end_time as integer 0 in SQLite, but legacy
# rows can carry "0" or empty strings. Treat all of these as "no end time yet".
_UNSET_TIMESTAMP_VALUES = (None, 0, 0.0, "0", "")


class NotificationAnalyzer:
    """
    Base class for analyzing device failures and gathering notification data.

    Provides common functionality for all notification services including:
    - Device failure analysis
    - Activity information gathering
    - Log file collection
    - Experiment duration calculation
    """

    def __init__(
        self,
        config: EthoscopeConfiguration | None = None,
        db: ExperimentalDB | None = None,
    ):
        """
        Initialize notification analyzer.

        Args:
            config: Configuration instance, will create new one if None
            db: Database instance, will create new one if None
        """
        self.config = config or EthoscopeConfiguration()
        self.db = db or ExperimentalDB()
        self.logger = logging.getLogger(self.__class__.__name__)

    def analyze_device_failure(
        self, device_id: str, run_id: str | None = None
    ) -> dict[str, Any]:
        """
        Gather context about the run that triggered an alert, for the email body.

        The orchestration layer (scanner) is the authority on whether to alert.
        This function does not re-decide; it only assembles human-readable
        information about the run.

        Args:
            device_id: Device identifier.
            run_id: The run that triggered the alert. Always supplied by the
                alert path so the right row is analyzed. When omitted (UI
                inspection, etc.) the most recent non-orphaned run is used.

        Returns:
            Dictionary with the analysis fields, or an "error" key on failure.
        """
        try:
            device_info = self.db.getEthoscope(device_id, asdict=True)
            if not device_info:
                self.logger.warning(f"No device info found for {device_id}")
                return {
                    "device_id": device_id,
                    "device_name": f"Unknown device {device_id}",
                    "error": "Device not found in database",
                }

            device_name = device_info.get("ethoscope_name", f"Device {device_id}")
            run = self._select_run_for_analysis(device_id, run_id)
            if run is None:
                return {
                    "device_id": device_id,
                    "device_name": device_name,
                    "last_seen": device_info.get("last_seen"),
                    "error": "No runs found for device",
                }

            start_time = self._parse_timestamp(run.get("start_time"))
            end_time = self._parse_timestamp(run.get("end_time"))

            if end_time is None:
                status = "Failed while running"
                duration = time.time() - start_time if start_time else 0.0
            else:
                status = "Stopped"
                duration = end_time - start_time if start_time else 0.0

            experimental_data = run.get("experimental_data", {})
            if isinstance(experimental_data, str):
                try:
                    experimental_data = json.loads(experimental_data)
                except Exception:
                    experimental_data = {}

            return {
                "device_id": device_id,
                "device_name": device_name,
                "last_seen": device_info.get("last_seen"),
                "status": status,
                "experiment_duration": duration,
                "experiment_duration_str": self._format_duration(duration),
                "user": run.get("user_name", "Unknown"),
                "location": run.get("location", "Unknown"),
                "run_id": run.get("run_id"),
                "problems": run.get("problems", ""),
                "experimental_data": experimental_data,
                "experiment_type": experimental_data.get("type", "tracking"),
                "start_time": (
                    datetime.datetime.fromtimestamp(start_time) if start_time else None
                ),
                "end_time": (
                    datetime.datetime.fromtimestamp(end_time) if end_time else None
                ),
                "device_problems": device_info.get("problems", ""),
                "device_active": device_info.get("active", False),
            }

        except Exception as e:
            self.logger.error(f"Error analyzing device failure for {device_id}: {e}")
            return {
                "device_id": device_id,
                "device_name": f"Device {device_id}",
                "error": str(e),
            }

    def _select_run_for_analysis(
        self, device_id: str, run_id: str | None
    ) -> dict[str, Any] | None:
        """Pick the run row to describe in an alert.

        With a run_id (alert path) we look up that exact row — never guess.
        Without one (UI inspection) we fall back to the device's most recent
        run, skipping rows that look like abandoned 'running' sessions
        (status='running' with no end_time, started >24h ago).
        """
        if run_id:
            rows = self.db.getRun(run_id, asdict=True)
            run = rows.get(run_id) if rows else None
            if run and run.get("ethoscope_id") == device_id:
                return run
            self.logger.warning(
                f"run_id {run_id} not found for device {device_id}; "
                "falling back to most recent run"
            )

        all_runs = self.db.getRun("all", asdict=True)
        device_runs = [
            r for r in all_runs.values() if r.get("ethoscope_id") == device_id
        ]
        if not device_runs:
            return None

        fresh = [r for r in device_runs if not self._looks_orphaned(r)]
        pool = fresh or device_runs
        return max(pool, key=lambda r: self._parse_timestamp(r.get("start_time")) or 0)

    def _looks_orphaned(self, run: dict[str, Any]) -> bool:
        """A 'running' row with no end_time, started >24h ago — probably stale."""
        if run.get("status") != "running":
            return False
        if run.get("end_time") not in _UNSET_TIMESTAMP_VALUES:
            return False
        start = self._parse_timestamp(run.get("start_time"))
        if start is None:
            return False
        return (time.time() - start) > 24 * 3600

    def _parse_timestamp(self, timestamp_value) -> float | None:
        """Parse a stored timestamp into a Unix epoch float, or None if unset.

        SQLite holds these values as TEXT (datetime string), INTEGER (0 for
        an unstarted/unfinished end_time), or rarely a float. Returns None
        for any of the unset markers in `_UNSET_TIMESTAMP_VALUES` and on
        parse failure, so callers can use `is None` consistently.
        """
        if timestamp_value in _UNSET_TIMESTAMP_VALUES:
            return None

        try:
            if isinstance(timestamp_value, (int, float)):
                return float(timestamp_value)

            if isinstance(timestamp_value, str):
                for fmt in (
                    "%Y-%m-%d %H:%M:%S.%f",
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d_%H-%M-%S",
                    "%Y%m%d_%H%M%S",
                ):
                    try:
                        return datetime.datetime.strptime(
                            timestamp_value, fmt
                        ).timestamp()
                    except ValueError:
                        continue
                try:
                    return float(timestamp_value) or None
                except ValueError:
                    pass

            if hasattr(timestamp_value, "timestamp"):
                return timestamp_value.timestamp()

            self.logger.warning(
                f"Could not parse timestamp: {timestamp_value} "
                f"(type: {type(timestamp_value)})"
            )
            return None

        except Exception as e:
            self.logger.error(f"Error parsing timestamp '{timestamp_value}': {e}")
            return None

    def get_device_logs(self, device_id: str, max_lines: int = 1000) -> str | None:
        """
        Get log content from a device.

        Args:
            device_id: Device identifier
            max_lines: Maximum number of log lines to retrieve

        Returns:
            Log content as string, or None if not available
        """
        try:
            # Try to get logs from device via API
            device_info = self.db.getEthoscope(device_id, asdict=True)
            if not device_info:
                return None

            # Get device IP/hostname from database
            # Extract the actual device data from the nested structure
            device_data = device_info.get(device_id, {})
            ip = device_data.get("last_ip") or device_data.get("ethoscope_name")

            if not ip or ip == device_id:
                self.logger.warning(
                    f"No valid IP found for device {device_id} - cannot fetch logs"
                )
                return None

            # Try to fetch logs from device
            log_url = f"http://{ip}:9000/data/log/{device_id}"

            try:
                response = requests.get(log_url, timeout=10)
                if response.status_code == 200:
                    log_content = response.text

                    # Limit to max_lines if specified
                    if max_lines and max_lines > 0:
                        lines = log_content.split("\n")
                        if len(lines) > max_lines:
                            lines = lines[-max_lines:]  # Get last N lines
                        log_content = "\n".join(lines)

                    return log_content

            except requests.RequestException as e:
                self.logger.warning(
                    f"Could not fetch logs from device {device_id}: {e}"
                )

            # If device API fails, try to get from local cache/backup
            # (This would be implemented based on backup system)
            return None

        except Exception as e:
            self.logger.error(f"Error getting device logs for {device_id}: {e}")
            return None

    def get_device_status_info(self, device_id: str) -> dict[str, Any]:
        """
        Get current device status information.

        Args:
            device_id: Device identifier

        Returns:
            Dictionary with device status information
        """
        try:
            device_info = self.db.getEthoscope(device_id, asdict=True)
            if not device_info:
                return {"error": "Device not found"}

            # Try to get real-time status from device
            # Extract the actual device data from the nested structure
            device_data = device_info.get(device_id, {})
            ip = device_data.get("last_ip") or device_data.get("ethoscope_name")

            # Only try to connect if we have a valid IP (not the device ID)
            if not ip or ip == device_id:
                # Device is offline, return database info
                return {
                    "device_id": device_id,
                    "device_name": device_data.get("ethoscope_name"),
                    "online": False,
                    "last_seen": device_data.get("last_seen"),
                    "active": device_data.get("active", False),
                    "problems": device_data.get("problems", ""),
                    "status": "offline",
                }

            try:
                status_url = f"http://{ip}:9000/data/{device_id}"
                response = requests.get(status_url, timeout=5)

                if response.status_code == 200:
                    status_data = response.json()
                    return {
                        "device_id": device_id,
                        "device_name": device_info.get("ethoscope_name"),
                        "online": True,
                        "status": status_data.get("status", "unknown"),
                        "last_frame_time": status_data.get("monitor_info", {}).get(
                            "last_time_stamp"
                        ),
                        "fps": status_data.get("monitor_info", {}).get("fps"),
                        "experimental_info": status_data.get("experimental_info", {}),
                        "database_info": status_data.get("database_info", {}),
                        "machine_info": status_data.get("machine_info", {}),
                    }

            except requests.RequestException:
                pass

            # Device is offline, return database info
            return {
                "device_id": device_id,
                "device_name": device_data.get("ethoscope_name"),
                "online": False,
                "last_seen": device_data.get("last_seen"),
                "active": device_data.get("active", False),
                "problems": device_data.get("problems", ""),
                "status": "offline",
            }

        except Exception as e:
            self.logger.error(f"Error getting device status for {device_id}: {e}")
            return {"device_id": device_id, "error": str(e)}

    def _format_duration(self, seconds: float) -> str:
        """
        Format duration in seconds to human-readable string.

        Args:
            seconds: Duration in seconds

        Returns:
            Formatted duration string
        """
        if seconds < 60:
            return f"{seconds:.1f} seconds"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f} minutes"
        elif seconds < 86400:
            hours = seconds / 3600
            return f"{hours:.1f} hours"
        else:
            days = seconds / 86400
            return f"{days:.1f} days"

    def get_device_users(self, device_id: str) -> list[str]:
        """
        Get list of user email addresses for users with currently running experiments on a device.

        Args:
            device_id: Device identifier

        Returns:
            List of email addresses
        """
        try:
            # Get users with currently running experiments on this device
            users = self.db.getUsersForDevice(device_id, running_only=True, asdict=True)

            user_emails = []
            for user_data in users:
                email = user_data.get("email")
                if email:
                    user_emails.append(email)

            return user_emails

        except Exception as e:
            self.logger.error(f"Error getting device users for {device_id}: {e}")
            return []

    def get_admin_emails(self) -> list[str]:
        """Get list of active admin email addresses."""
        try:
            # Get all active admin users from database
            users = self.db.getAllUsers(active_only=True, admin_only=True, asdict=True)
            admin_emails = []

            for user_data in users.values():
                email = user_data.get("email")
                if email:
                    admin_emails.append(email)

            return admin_emails

        except Exception as e:
            self.logger.error(f"Error getting admin emails: {e}")
            return []

    def get_stopped_experiment_user(self, run_id: str) -> list[str]:
        """
        Get email address for the user who owns a specific experiment run.

        Args:
            run_id: Run identifier

        Returns:
            List containing the user's email address (empty list if not found or user inactive)
        """
        try:
            # Get user who owns this run
            user = self.db.getUserByRun(run_id, asdict=True)

            if user and user.get("active") == 1:
                email = user.get("email")
                if email:
                    return [email]

            return []

        except Exception as e:
            self.logger.error(f"Error getting user for run {run_id}: {e}")
            return []
