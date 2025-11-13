#!/usr/bin/env python

import datetime
import logging
import time
from typing import Any, Dict, List, Optional

import requests

from ..utils.configuration import EthoscopeConfiguration
from ..utils.etho_db import ExperimentalDB


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
        config: Optional[EthoscopeConfiguration] = None,
        db: Optional[ExperimentalDB] = None,
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

    def analyze_device_failure(self, device_id: str) -> Dict[str, Any]:
        """
        Analyze a device failure and gather comprehensive information.

        Args:
            device_id: Device identifier

        Returns:
            Dictionary with device failure analysis
        """
        try:
            # Get device information
            device_info = self.db.getEthoscope(device_id, asdict=True)
            if not device_info:
                self.logger.warning(f"No device info found for {device_id}")
                return {
                    "device_id": device_id,
                    "device_name": f"Unknown device {device_id}",
                    "error": "Device not found in database",
                }

            # Get all runs for this device
            all_runs = self.db.getRun("all", asdict=True)
            device_runs = [
                run for run in all_runs.values() if run.get("ethoscope_id") == device_id
            ]

            if not device_runs:
                return {
                    "device_id": device_id,
                    "device_name": device_info.get(
                        "ethoscope_name", f"Device {device_id}"
                    ),
                    "last_seen": device_info.get("last_seen"),
                    "error": "No runs found for device",
                }

            # Filter out orphaned "running" sessions that are clearly stale
            # These are runs with status='running' and end_time='0' that are older than 24 hours
            current_time = time.time()
            orphan_threshold = 24 * 3600  # 24 hours in seconds

            filtered_runs = []
            for run in device_runs:
                start_time = self._parse_timestamp(run.get("start_time", 0))
                end_time_raw = run.get("end_time")

                # Check if this is an orphaned running session
                is_orphaned = (
                    run.get("status") == "running"
                    and (
                        end_time_raw == "0" or end_time_raw == 0 or end_time_raw is None
                    )
                    and start_time > 0
                    and (current_time - start_time) > orphan_threshold
                )

                if is_orphaned:
                    age_hours = (current_time - start_time) / 3600
                    self.logger.debug(
                        f"Filtering out orphaned running session {run.get('run_id')} "
                        f"(age: {age_hours:.1f} hours, started: {datetime.datetime.fromtimestamp(start_time)})"
                    )
                else:
                    filtered_runs.append(run)

            if not filtered_runs:
                # All runs were orphaned, log a warning
                self.logger.warning(
                    f"All {len(device_runs)} runs for device {device_id} were orphaned sessions. "
                    "No recent valid runs found."
                )
                return {
                    "device_id": device_id,
                    "device_name": device_info.get(
                        "ethoscope_name", f"Device {device_id}"
                    ),
                    "last_seen": device_info.get("last_seen"),
                    "error": "No recent valid runs found (all runs were orphaned)",
                    "orphaned_count": len(device_runs),
                }

            # Find last run (need to parse timestamps for comparison)
            def get_run_start_time(run):
                start_time_raw = run.get("start_time", 0)
                return self._parse_timestamp(start_time_raw)

            last_run = max(filtered_runs, key=get_run_start_time)

            # Determine failure type and duration
            current_time = time.time()
            start_time_raw = last_run.get("start_time", 0)
            end_time_raw = last_run.get("end_time")

            # Convert datetime strings to timestamps
            start_time = self._parse_timestamp(start_time_raw)
            end_time = self._parse_timestamp(end_time_raw) if end_time_raw else None

            if end_time is None:
                failure_type = "crashed_during_tracking"
                duration = current_time - start_time
                status = "Failed while running"
            else:
                # Check if ended recently (within last hour)
                if current_time - end_time < 3600:
                    failure_type = "stopped_recently"
                    status = "Stopped recently"
                else:
                    failure_type = "completed_normally"
                    status = "Completed normally"
                duration = end_time - start_time

            # Get experiment type from experimental_data
            experimental_data = last_run.get("experimental_data", {})
            if isinstance(experimental_data, str):
                try:
                    import json

                    experimental_data = json.loads(experimental_data)
                except Exception:
                    experimental_data = {}

            return {
                "device_id": device_id,
                "device_name": device_info.get("ethoscope_name", f"Device {device_id}"),
                "last_seen": device_info.get("last_seen"),
                "failure_type": failure_type,
                "status": status,
                "experiment_duration": duration,
                "experiment_duration_str": self._format_duration(duration),
                "user": last_run.get("user_name", "Unknown"),
                "location": last_run.get("location", "Unknown"),
                "run_id": last_run.get("run_id"),
                "problems": last_run.get("problems", ""),
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

    def _parse_timestamp(self, timestamp_value):
        """
        Parse timestamp value which could be a string, float, or datetime object.

        Args:
            timestamp_value: The timestamp value from database

        Returns:
            float: Unix timestamp, or 0 if parsing fails
        """
        if timestamp_value is None:
            return 0

        try:
            # If it's already a number, check for special case of 0 (which means no end_time)
            if isinstance(timestamp_value, (int, float)):
                value = float(timestamp_value)
                # Treat 0 as None/null for end_time fields
                return 0 if value == 0 else value

            # If it's a string, check for special values first
            if isinstance(timestamp_value, str):
                # Treat '0' as None/null (common for end_time when not set)
                if timestamp_value == "0" or timestamp_value == "":
                    return 0

                # Try different datetime formats that might be stored in database
                for fmt in [
                    "%Y-%m-%d %H:%M:%S.%f",  # 2023-01-01 12:34:56.789123
                    "%Y-%m-%d %H:%M:%S",  # 2023-01-01 12:34:56
                    "%Y-%m-%d_%H-%M-%S",  # 2023-01-01_12-34-56
                    "%Y%m%d_%H%M%S",  # 20230101_123456
                ]:
                    try:
                        dt = datetime.datetime.strptime(timestamp_value, fmt)
                        return dt.timestamp()
                    except ValueError:
                        continue

                # If no format worked, try parsing as float
                try:
                    value = float(timestamp_value)
                    # Treat 0 as None/null
                    return 0 if value == 0 else value
                except ValueError:
                    pass

            # If it's a datetime object
            if hasattr(timestamp_value, "timestamp"):
                return timestamp_value.timestamp()

            self.logger.warning(
                f"Could not parse timestamp: {timestamp_value} (type: {type(timestamp_value)})"
            )
            return 0

        except Exception as e:
            self.logger.error(f"Error parsing timestamp '{timestamp_value}': {e}")
            return 0

    def get_device_logs(self, device_id: str, max_lines: int = 1000) -> Optional[str]:
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

    def get_device_status_info(self, device_id: str) -> Dict[str, Any]:
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

    def get_device_users(self, device_id: str) -> List[str]:
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

    def get_admin_emails(self) -> List[str]:
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

    def get_stopped_experiment_user(self, run_id: str) -> List[str]:
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
