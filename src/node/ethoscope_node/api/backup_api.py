"""
Backup API Module

Handles backup system management by aggregating basic status information
from MySQL (port 8090) and rsync (port 8093) backup services.
"""

import json
import time
import urllib.request

from .base import BaseAPI, error_decorator


class BackupAPI(BaseAPI):
    """API endpoints for backup system management."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Simple cache for backup status with longer TTL for production
        self._backup_cache = {
            "data": None,
            "timestamp": 0,
            "ttl": 300,  # Cache for 5 minutes (was 60 seconds)
        }

    def register_routes(self):
        """Register backup-related routes."""
        self.app.route("/backup/status", method="GET")(self._get_backup_status)

    @error_decorator
    def _get_backup_status(self):
        """Get basic backup status aggregated from backup services."""
        self.set_json_response()

        # Check cache first
        current_time = time.time()
        if (
            self._backup_cache["data"] is not None
            and current_time - self._backup_cache["timestamp"]
            < self._backup_cache["ttl"]
        ):
            return self._backup_cache["data"]

        # Fetch basic status from both backup services
        mysql_status = self._fetch_backup_service_status(8090, "MySQL")
        rsync_status = self._fetch_backup_service_status(8093, "Rsync")

        # Determine which devices are currently being processed
        processing_devices = self._get_processing_devices(mysql_status, rsync_status)

        # Determine service availability
        mysql_available = "error" not in mysql_status
        rsync_available = "error" not in rsync_status

        # Each daemon's record of every device it has backed up, keyed by id. Reason:
        # rsync nests them under "devices"; the MySQL daemon returns them flat.
        rsync_devices = rsync_status.get("devices", {}) if rsync_available else {}
        mysql_devices = (
            {k: v for k, v in mysql_status.items() if isinstance(v, dict)}
            if mysql_available
            else {}
        )

        # Get device-level backup information for home page icons
        devices_backup_info = self._get_devices_backup_summary(
            processing_devices, rsync_devices, mysql_devices
        )

        # Create aggregated response with device-level data and summary
        aggregated_status = {
            "services": {
                "mysql_backup": {
                    "available": mysql_available,
                    "current_device": self._extract_current_device(mysql_status),
                    "current_file": self._extract_current_file(mysql_status),
                },
                "rsync_backup": {
                    "available": rsync_available,
                    "current_device": self._extract_current_device(rsync_status),
                    "current_file": self._extract_current_file(rsync_status),
                },
            },
            "summary": {
                "mysql_backup_available": mysql_available,
                "rsync_backup_available": rsync_available,
                "services": {
                    "mysql_service_available": mysql_available,
                    "rsync_service_available": rsync_available,
                },
            },
            "devices": devices_backup_info,
            "processing_devices": processing_devices,
            # The rsync daemon's sweep: interval, last start, next start (epochs).
            # None when the daemon is down or too old to report it.
            "cycle": rsync_status.get("cycle") if rsync_available else None,
            "timestamp": current_time,
        }

        # Cache the result
        result = json.dumps(aggregated_status, indent=2)
        self._backup_cache = {"data": result, "timestamp": current_time, "ttl": 60}

        return result

    def _fetch_backup_service_status(self, port: int, service_name: str):
        """Fetch basic status from a backup daemon."""
        try:
            backup_url = f"http://localhost:{port}/status"
            with urllib.request.urlopen(backup_url, timeout=5) as response:
                data = response.read().decode("utf-8")
                return json.loads(data)
        except Exception as e:
            self.logger.debug(
                f"Failed to get {service_name} backup status from port {port}: {e}"
            )
            return {"error": f"{service_name} backup service unavailable"}

    def _extract_current_device(self, service_status):
        """Extract currently processing device from service status."""
        if "error" in service_status:
            return None

        # Check if this is the simplified format (from reverted backup tools)
        if "current_device" in service_status:
            return service_status["current_device"]

        # Check for processing devices in the array format
        if "processing_devices" in service_status:
            processing = service_status["processing_devices"]
            if processing and len(processing) > 0:
                return processing[0].get("device_name")

        # Legacy format - look for processing devices in full status
        if isinstance(service_status, dict):
            for device_id, device_data in service_status.items():
                if isinstance(device_data, dict) and device_data.get(
                    "processing", False
                ):
                    return device_data.get("name", device_id)

        return None

    def _extract_current_file(self, service_status):
        """Extract currently processing file from service status."""
        if "error" in service_status:
            return None

        # Check if this is the simplified format (from reverted backup tools)
        if "current_file" in service_status:
            return service_status["current_file"]

        # Check for processing devices in the array format
        if "processing_devices" in service_status:
            processing = service_status["processing_devices"]
            if processing and len(processing) > 0:
                return processing[0].get("current_file")

        # Legacy format - look for current file in progress data
        if isinstance(service_status, dict):
            for _device_id, device_data in service_status.items():
                if isinstance(device_data, dict) and device_data.get(
                    "processing", False
                ):
                    progress = device_data.get("progress", {})
                    return progress.get("current_file", progress.get("backup_filename"))

        return None

    def _get_processing_devices(self, mysql_status, rsync_status):
        """Get list of all currently processing devices from backup services."""
        processing = []

        # Extract all processing devices from rsync service
        # The rsync status nests device data under a "devices" key
        if isinstance(rsync_status, dict) and "error" not in rsync_status:
            rsync_devices = rsync_status.get("devices", {})
            for _dev_id, dev_data in rsync_devices.items():
                if isinstance(dev_data, dict) and dev_data.get("processing", False):
                    processing.append(
                        {"service": "rsync", "device": dev_data.get("name", _dev_id)}
                    )

        return processing

    @staticmethod
    def _job_summary(job: dict | None) -> dict:
        """
        Reduce a backup daemon's record of one device to what the pages show.

        Args:
            job (dict | None): The daemon's serialised BackupStatus for the device.

        Returns:
            dict: ``last_success``, ``started`` and ``ended`` as epochs (0 when
            unknown), the latest job's ``result`` ("completed", "error", or its
            progress status while running) and its ``message``.
        """
        job = job or {}
        progress = job.get("progress") or {}
        ended = job.get("ended") or 0
        # Reason: a job that crashed is recorded with ended = -1; its time is kept
        # in the progress record instead.
        if ended < 0:
            ended = progress.get("completion_time", 0)
        result = progress.get("status", "")
        # Reason: a daemon older than last_success still says when its latest job
        # ended, and a job that completed is by definition the last success.
        last_success = job.get("last_success") or (
            ended if result == "completed" else 0
        )
        return {
            "last_success": last_success,
            "started": job.get("started") or 0,
            "ended": ended,
            "result": result,
            "message": progress.get("message", ""),
        }

    @staticmethod
    def _type_status(available: bool, job: dict) -> str:
        """
        Status of one backup type: whether the node holds data, and the last job.

        Args:
            available (bool): The node holds backed-up data of this type.
            job (dict): The device's job summary from the daemon handling the type.

        Returns:
            str: "not_available", "error" when the latest job failed, else "success".
        """
        if not available:
            return "not_available"
        return "error" if job["result"] == "error" else "success"

    @staticmethod
    def _unavailable_backup_types(status: str) -> dict:
        """
        Backup types of a device the node cannot describe (offline, or an error).

        Args:
            status (str): Status to give every type, e.g. "offline" or "unknown".

        Returns:
            dict: The ``backup_types`` structure with nothing available.
        """
        common = {"available": False, "status": status, "processing": False}
        return {
            "mysql": {
                **common,
                "size": 0,
                "last_backup": 0,
                "records": 0,
                "directory": "",
                "message": "",
            },
            "sqlite": {
                **common,
                "size": 0,
                "last_backup": 0,
                "files": 0,
                "directory": "",
            },
            "video": {
                **common,
                "size": 0,
                "last_backup": 0,
                "files": 0,
                "directory": "",
                "size_human": "",
            },
        }

    def _get_devices_backup_summary(
        self, processing_devices=None, rsync_devices=None, mysql_devices=None
    ):
        """
        Get backup summary for all devices for home page display.

        Args:
            processing_devices (list | None): Devices a daemon is backing up now.
            rsync_devices (dict | None): The rsync daemon's records, keyed by id.
            mysql_devices (dict | None): The MySQL daemon's records, keyed by id.

        Returns:
            dict: Per device id, ``backup_types``, ``overall_status`` and
            ``last_job`` (the latest job's summary, or None if no daemon knows it).
        """
        devices_backup = {}
        rsync_devices = rsync_devices or {}
        mysql_devices = mysql_devices or {}

        # Build a lookup of which device names are currently being processed
        # and by which service (mysql or rsync)
        processing_by_name = {}
        for proc in processing_devices or []:
            name = proc.get("device")
            service = proc.get("service")
            if name:
                processing_by_name.setdefault(name, set()).add(service)

        try:
            # Get list of all devices from the device scanner
            if not self.device_scanner:
                return devices_backup

            devices = self.device_scanner.get_all_devices_info()

            # For each device, get basic backup information
            for device_id, device_info in devices.items():
                # Reason: one unified rsync job copies both results and videos, so
                # SQLite and video share its record; MySQL has a daemon of its own.
                rsync_job = self._job_summary(rsync_devices.get(device_id))
                mysql_job = self._job_summary(mysql_devices.get(device_id))
                try:
                    # For summary endpoint, use a more efficient approach
                    # Check if device is online and has database information
                    device_status = device_info.get("status", "offline")
                    has_databases = (
                        "databases" in device_info and device_info["databases"]
                    )

                    if device_status != "offline" and has_databases:
                        # Get backup info for online devices with database info
                        from ethoscope_node.backup.helpers import get_device_backup_info

                        device_databases = device_info.get("databases", {})
                        backup_info = get_device_backup_info(
                            device_id, device_databases
                        )
                        backup_status = backup_info.get("backup_status", {})

                        # Extract detailed backup information for home page display
                        mysql_info = backup_status.get("mysql", {})
                        sqlite_info = backup_status.get("sqlite", {})
                        video_info = backup_status.get("video", {})

                        # Check if this device is currently being processed
                        device_name = device_info.get("name", "")
                        active_services = processing_by_name.get(device_name, set())

                        # Calculate overall status
                        available_count = sum(
                            [
                                mysql_info.get("available", False),
                                sqlite_info.get("available", False),
                                video_info.get("available", False),
                            ]
                        )

                        if available_count == 3:
                            overall_status = "success"
                        elif available_count > 0:
                            overall_status = "partial"
                        else:
                            overall_status = "no_backups"

                        # Create structure for home page with required fields
                        device_backup_data = {
                            "backup_types": {
                                "mysql": {
                                    "available": mysql_info.get("available", False),
                                    "status": self._type_status(
                                        mysql_info.get("available", False), mysql_job
                                    ),
                                    "processing": "mysql" in active_services,
                                    "size": mysql_info.get("total_size_bytes", 0),
                                    "records": mysql_info.get("database_count", 0),
                                    "directory": mysql_info.get("directory", ""),
                                    "message": mysql_info.get("message", ""),
                                },
                                "sqlite": {
                                    "available": sqlite_info.get("available", False),
                                    "status": self._type_status(
                                        sqlite_info.get("available", False), rsync_job
                                    ),
                                    "processing": "rsync" in active_services,
                                    "size": sqlite_info.get("total_size_bytes", 0),
                                    "files": sqlite_info.get("database_count", 0),
                                    "directory": sqlite_info.get("directory", ""),
                                },
                                "video": {
                                    "available": video_info.get("available", False),
                                    "status": self._type_status(
                                        video_info.get("available", False), rsync_job
                                    ),
                                    "processing": "rsync" in active_services,
                                    "size": video_info.get("total_size_bytes", 0),
                                    "files": video_info.get("file_count", 0),
                                    "directory": video_info.get("directory", ""),
                                    "size_human": video_info.get("size_human", ""),
                                },
                            },
                            "overall_status": overall_status,
                        }
                    else:
                        # For offline devices or devices without database info, show as not available
                        device_backup_data = {
                            "backup_types": self._unavailable_backup_types("offline"),
                            "overall_status": "no_backups",
                        }

                except Exception:
                    # If we can't get backup info for this device, mark as unknown
                    device_backup_data = {
                        "backup_types": self._unavailable_backup_types("unknown"),
                        "overall_status": "unknown",
                    }

                # Reason: when a device was last backed up is known to the daemon
                # whether or not the device is reachable now.
                types = device_backup_data["backup_types"]
                types["mysql"]["last_backup"] = mysql_job["last_success"]
                types["sqlite"]["last_backup"] = rsync_job["last_success"]
                types["video"]["last_backup"] = rsync_job["last_success"]
                device_backup_data["last_job"] = next(
                    (job for job in (rsync_job, mysql_job) if job["started"]), None
                )
                devices_backup[device_id] = device_backup_data

        except Exception:
            # If we can't get device list, return empty dict
            pass

        return devices_backup
