"""
Bug Report API Module

Generates comprehensive bug reports for debugging by collecting system
information from the node and all connected ethoscope devices.
"""

import datetime
import platform
import shutil
import socket
import subprocess
import sys
from typing import Any

import bottle
import netifaces

from .base import BaseAPI, error_decorator

# Report version for tracking schema changes
REPORT_VERSION = "1.1"

# Default and maximum log lines
DEFAULT_LOG_LINES = 500
MAX_LOG_LINES = 5000

# Device request timeout in seconds
DEVICE_TIMEOUT = 5

# Units whose systemd state goes into node.services
SERVICE_NAMES = [
    "ethoscope_node",
    "ethoscope_backup_mysql",
    "ethoscope_backup_unified",
    "ethoscope_backup_sqlite",
    "ethoscope_backup_video",
    "ethoscope_update_node",
    "ethoscope_tunnel",
    "ethoscope_virtuascope",
]

# systemd's own lines per backup unit (Started, Stopping, Failed with result...).
# Reason: a few per start or stop, so these reach back days, where the unit's own
# output reaches back minutes and loses the event once the unit is running again.
EVENT_LINES = 100

# Units whose journal goes into backup_services.logs and .events
BACKUP_UNITS = [
    "ethoscope_backup_unified",
    "ethoscope_backup_sqlite",
    "ethoscope_backup_video",
    "ethoscope_backup_mysql",
]

# Reason: is-active says "failed" but not why. Result (timeout, exit-code, signal,
# start-limit-hit) with the exit status and the time the unit went down tells a stop
# that hung from a crash, and UnitFileState shows conflicting units enabled together.
SERVICE_PROPERTIES = [
    "LoadState",
    "ActiveState",
    "SubState",
    "Result",
    "ExecMainCode",
    "ExecMainStatus",
    "NRestarts",
    "UnitFileState",
    "ActiveEnterTimestamp",
    "InactiveEnterTimestamp",
]


class BugReportAPI(BaseAPI):
    """API endpoints for generating bug reports."""

    def register_routes(self):
        """Register bug report routes."""
        self.app.route("/bugreport/generate", method=["GET", "POST"])(
            self._generate_bug_report
        )

    @error_decorator
    def _generate_bug_report(self):
        """Generate a comprehensive bug report."""
        # Parse request for optional parameters
        log_lines = DEFAULT_LOG_LINES
        try:
            request_data = self.get_request_json()
            if request_data:
                log_lines = min(
                    request_data.get("log_lines", DEFAULT_LOG_LINES), MAX_LOG_LINES
                )
        except Exception:
            pass

        report = {
            "report_metadata": self._get_report_metadata(),
            "node": {},
            "devices": {},
            "backup_services": {},
            "configuration": {},
            "errors": [],
        }

        # Collect node information
        report["node"] = self._collect_node_info(report["errors"], log_lines)

        # Collect device information
        report["devices"] = self._collect_devices_info(report["errors"], log_lines)

        # Collect backup service status
        report["backup_services"] = self._collect_backup_status(
            report["errors"], log_lines
        )

        # Collect configuration
        report["configuration"] = self._collect_configuration(report["errors"])

        # Generate summary
        report["_summary"] = self._generate_summary(report)

        # Set response headers for download
        bottle.response.content_type = "application/json"
        bottle.response.headers["Content-Disposition"] = (
            f'attachment; filename="ethoscope-bugreport-'
            f'{datetime.datetime.now().strftime("%Y%m%d-%H%M%S")}.json"'
        )

        return report

    def _get_report_metadata(self) -> dict[str, Any]:
        """Get report metadata."""
        hostname = "unknown"
        try:
            hostname = socket.gethostname()
        except Exception:
            pass

        return {
            "version": REPORT_VERSION,
            "generated_at": datetime.datetime.now().isoformat(),
            "hostname": hostname,
        }

    def _collect_node_info(self, errors: list[str], log_lines: int) -> dict[str, Any]:
        """Collect comprehensive node system information."""
        node_info = {}

        # System info
        node_info["system"] = self._get_system_info(errors)

        # Disk usage
        node_info["disk"] = self._get_disk_info(errors)

        # Memory info
        node_info["memory"] = self._get_memory_info(errors)

        # Network interfaces
        node_info["network"] = self._get_network_info(errors)

        # Git version
        node_info["git_version"] = self._get_git_info(errors)

        # Python version
        node_info["python_version"] = sys.version

        # Services status
        node_info["services"] = self._get_services_status(errors)

        # Node logs
        node_info["log"] = self._get_unit_log("ethoscope_node", errors, log_lines)

        return node_info

    def _get_system_info(self, errors: list[str]) -> dict[str, Any]:
        """Get system platform information."""
        try:
            # Get uptime
            uptime = "unknown"
            try:
                with open("/proc/uptime") as f:
                    uptime_seconds = float(f.readline().split()[0])
                    days = int(uptime_seconds // 86400)
                    hours = int((uptime_seconds % 86400) // 3600)
                    minutes = int((uptime_seconds % 3600) // 60)
                    uptime = f"{days}d {hours}h {minutes}m"
            except Exception:
                pass

            return {
                "platform": platform.platform(),
                "kernel": platform.release(),
                "architecture": platform.machine(),
                "processor": platform.processor(),
                "uptime": uptime,
            }
        except Exception as e:
            errors.append(f"Failed to get system info: {e}")
            return {}

    def _get_disk_info(self, errors: list[str]) -> dict[str, Any]:
        """Get disk usage information."""
        try:
            # Check results directory
            check_path = self.results_dir if self.results_dir else "/"
            total, used, free = shutil.disk_usage(check_path)
            percent = (used / total) * 100 if total > 0 else 0

            return {
                "path": check_path,
                "total_gb": round(total / (1024**3), 2),
                "used_gb": round(used / (1024**3), 2),
                "available_gb": round(free / (1024**3), 2),
                "percent_used": round(percent, 1),
            }
        except Exception as e:
            errors.append(f"Failed to get disk info: {e}")
            return {}

    def _get_memory_info(self, errors: list[str]) -> dict[str, Any]:
        """Get memory usage information."""
        try:
            with open("/proc/meminfo") as f:
                meminfo = {}
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        key = parts[0].rstrip(":")
                        value = int(parts[1])
                        meminfo[key] = value

            total = meminfo.get("MemTotal", 0)
            available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
            percent = ((total - available) / total) * 100 if total > 0 else 0

            return {
                "total_mb": round(total / 1024, 0),
                "available_mb": round(available / 1024, 0),
                "percent_used": round(percent, 1),
            }
        except Exception as e:
            errors.append(f"Failed to get memory info: {e}")
            return {}

    def _get_network_info(self, errors: list[str]) -> dict[str, Any]:
        """Get network interface information."""
        try:
            interfaces = {}
            for iface in netifaces.interfaces():
                try:
                    addrs = netifaces.ifaddresses(iface)
                    iface_info = {}

                    # Get MAC address (AF_LINK = 17)
                    if 17 in addrs and addrs[17]:
                        mac = addrs[17][0].get("addr")
                        if mac and mac != "00:00:00:00:00:00":
                            iface_info["MAC"] = mac

                    # Get IPv4 address (AF_INET = 2)
                    if 2 in addrs and addrs[2]:
                        iface_info["IP"] = addrs[2][0].get("addr")
                        iface_info["netmask"] = addrs[2][0].get("netmask")

                    if iface_info:
                        interfaces[iface] = iface_info
                except Exception:
                    continue

            return {"interfaces": interfaces}
        except Exception as e:
            errors.append(f"Failed to get network info: {e}")
            return {}

    def _get_git_info(self, errors: list[str]) -> dict[str, Any]:
        """Get git repository information."""
        try:
            git_info = {}

            # Branch
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            git_info["branch"] = (
                result.stdout.strip() if result.returncode == 0 else "unknown"
            )

            # Commit hash
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            git_info["commit"] = (
                result.stdout.strip() if result.returncode == 0 else "unknown"
            )

            # Commit date
            result = subprocess.run(
                ["git", "show", "-s", "--format=%ci", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            git_info["date"] = (
                result.stdout.strip() if result.returncode == 0 else "unknown"
            )

            # Check for local changes
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            git_info["has_local_changes"] = (
                bool(result.stdout.strip()) if result.returncode == 0 else None
            )

            return git_info
        except Exception as e:
            errors.append(f"Failed to get git info: {e}")
            return {}

    def _get_services_status(self, errors: list[str]) -> dict[str, Any]:
        """
        Get the systemd state of the ethoscope services.

        Args:
            errors (list[str]): Collection errors (unused; a unit that cannot be
                queried is reported as ``"unknown"`` instead).

        Returns:
            dict[str, Any]: Per unit, ``active`` (the ActiveState), ``since`` when
                active, and ``systemd`` with the raw SERVICE_PROPERTIES values.
        """
        services = {}
        systemctl = getattr(self.server, "systemctl", "/usr/bin/systemctl")

        for service_name in SERVICE_NAMES:
            try:
                result = subprocess.run(
                    [
                        systemctl,
                        "show",
                        service_name,
                        f"--property={','.join(SERVICE_PROPERTIES)}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                props = dict(
                    line.split("=", 1)
                    for line in result.stdout.splitlines()
                    if "=" in line
                )
                service_info = {"active": props.get("ActiveState", "unknown")}
                if service_info["active"] == "active":
                    service_info["since"] = props.get("ActiveEnterTimestamp", "")
                service_info["systemd"] = props
                services[service_name] = service_info
            except Exception:
                services[service_name] = {"active": "unknown"}

        return services

    @staticmethod
    def _device_log_lines(log_data: dict[str, Any] | None, log_lines: int) -> list[str]:
        """
        Trim a device's ``/data/log`` answer to the report's line budget.

        The device returns every journal line since each service last started,
        newest first, so a device up for weeks sends far more than a report can
        carry. Keeping the head keeps the most recent lines.

        Args:
            log_data (dict | None): What ``Ethoscope.get_log()`` returned.
            log_lines (int): Maximum number of lines to keep.

        Returns:
            list[str]: The newest ``log_lines`` lines.

        Raises:
            RuntimeError: If the device could not be reached or reported an error.
        """
        if not log_data:
            raise RuntimeError("device did not answer /data/log")
        if "error" in log_data:
            raise RuntimeError(str(log_data["error"]).strip().splitlines()[-1])
        return log_data.get("message", "").splitlines()[:log_lines]

    def _get_unit_log(
        self,
        unit: str,
        errors: list[str],
        log_lines: int,
        systemd_only: bool = False,
    ) -> list[str]:
        """
        Get the last journal lines of a systemd unit.

        With ``-u``, journalctl also returns systemd's own lines about the unit
        ("Failed with result 'timeout'", "Main process exited, status=1"), which say
        why a unit stopped when its own output does not.

        Args:
            unit (str): The systemd unit name.
            errors (list[str]): Collection errors; a failure is appended here.
            log_lines (int): Maximum number of lines to return.
            systemd_only (bool): Keep only systemd's own lines about the unit.

        Returns:
            list[str]: The newest ``log_lines`` lines, oldest first.
        """
        cmd = ["journalctl", "-u", unit, "-n", str(log_lines), "--no-pager"]
        if systemd_only:
            cmd += ["-t", "systemd"]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return result.stdout.strip().split("\n")
            return []
        except Exception as e:
            errors.append(f"Failed to get {unit} logs: {e}")
            return []

    def _collect_devices_info(
        self, errors: list[str], log_lines: int
    ) -> dict[str, Any]:
        """Collect information from all connected devices."""
        devices_info = {}

        if not self.device_scanner:
            errors.append("Device scanner not available")
            return devices_info

        try:
            all_devices = self.device_scanner.get_all_devices_info(
                include_inactive=True
            )

            for device_id, device_summary in all_devices.items():
                device_info = {
                    "status": device_summary.get("status", "unknown"),
                    "info": device_summary,
                    "machine_info": None,
                    "log": None,
                    "error": None,
                }

                # Try to get more detailed info for online devices
                status = device_summary.get("status", "")
                if status not in ["offline", "na", "unreachable", "retired"]:
                    device = self.device_scanner.get_device(device_id)
                    if device:
                        # Get machine info
                        try:
                            machine_info = device.machine_info()
                            device_info["machine_info"] = machine_info
                        except Exception as e:
                            device_info["error"] = f"Failed to get machine info: {e}"

                        # Get device logs
                        try:
                            device_info["log"] = self._device_log_lines(
                                device.get_log(), log_lines
                            )
                        except Exception as e:
                            if not device_info.get("error"):
                                device_info["error"] = f"Failed to get logs: {e}"
                            else:
                                device_info["error"] += f"; Failed to get logs: {e}"
                else:
                    device_info["error"] = (
                        f"Device {status}, cannot retrieve detailed info"
                    )

                devices_info[device_id] = device_info

        except Exception as e:
            errors.append(f"Failed to collect device info: {e}")

        return devices_info

    def _collect_backup_status(
        self, errors: list[str], log_lines: int = DEFAULT_LOG_LINES
    ) -> dict[str, Any]:
        """
        Collect backup service status and the backup units' journals.

        Args:
            errors (list[str]): Collection errors; failures are appended here.
            log_lines (int): Maximum journal lines per backup unit.

        Returns:
            dict[str, Any]: ``mysql`` and ``rsync`` (the unified unit) status, and
                ``logs`` and ``events`` keyed by BACKUP_UNITS.
        """
        backup_status = {}

        systemctl = getattr(self.server, "systemctl", "/usr/bin/systemctl")

        # MySQL backup service
        try:
            result = subprocess.run(
                [systemctl, "is-active", "ethoscope_backup_mysql"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            backup_status["mysql"] = {
                "available": result.returncode == 0,
                "status": result.stdout.strip(),
            }
        except Exception as e:
            backup_status["mysql"] = {"available": False, "error": str(e)}

        # Unified backup service (rsync-based)
        try:
            result = subprocess.run(
                [systemctl, "is-active", "ethoscope_backup_unified"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            backup_status["rsync"] = {
                "available": result.returncode == 0,
                "status": result.stdout.strip(),
            }
        except Exception as e:
            backup_status["rsync"] = {"available": False, "error": str(e)}

        # Reason: node.log is ethoscope_node's journal alone, and a backup unit that
        # fails leaves the reason only in its own (2026-11-16: a report showed
        # ethoscope_backup_unified "failed" and nothing that said why).
        backup_status["logs"] = {
            unit: self._get_unit_log(unit, errors, log_lines) for unit in BACKUP_UNITS
        }
        backup_status["events"] = {
            unit: self._get_unit_log(unit, errors, EVENT_LINES, systemd_only=True)
            for unit in BACKUP_UNITS
        }

        return backup_status

    def _collect_configuration(self, errors: list[str]) -> dict[str, Any]:
        """Collect configuration information."""
        config_info = {}

        try:
            if self.config:
                # Folders configuration
                config_info["folders"] = self.config.content.get("folders", {})

                # Device options
                try:
                    config_info["device_options"] = self.config.get_device_options()
                except Exception:
                    config_info["device_options"] = {}

                # Setup status
                try:
                    config_info["setup_required"] = self.config.is_setup_required()
                except Exception:
                    config_info["setup_required"] = None

        except Exception as e:
            errors.append(f"Failed to collect configuration: {e}")

        return config_info

    def _generate_summary(self, report: dict[str, Any]) -> str:
        """Generate a human-readable summary of the bug report."""
        lines = []
        lines.append(
            f"Bug Report generated at {report['report_metadata']['generated_at']}"
        )
        lines.append(f"Node hostname: {report['report_metadata']['hostname']}")

        # Node summary
        node = report.get("node", {})
        if node:
            disk = node.get("disk", {})
            if disk:
                lines.append(
                    f"Disk: {disk.get('percent_used', '?')}% used "
                    f"({disk.get('available_gb', '?')} GB available)"
                )

            memory = node.get("memory", {})
            if memory:
                lines.append(
                    f"Memory: {memory.get('percent_used', '?')}% used "
                    f"({memory.get('available_mb', '?')} MB available)"
                )

            git = node.get("git_version", {})
            if git:
                lines.append(
                    f"Git: {git.get('branch', '?')} @ {git.get('commit', '?')}"
                )

            failed = [
                f"{name} ({svc.get('systemd', {}).get('Result', '?')})"
                for name, svc in node.get("services", {}).items()
                if svc.get("active") == "failed"
            ]
            if failed:
                lines.append(f"Failed services: {', '.join(failed)}")

        # Device summary
        devices = report.get("devices", {})
        if devices:
            total = len(devices)
            online = sum(
                1
                for d in devices.values()
                if d.get("status") not in ["offline", "na", "unreachable", "retired"]
            )
            lines.append(f"Devices: {online}/{total} online")

        # Errors summary
        errors = report.get("errors", [])
        if errors:
            lines.append(f"Collection errors: {len(errors)}")

        return "\n".join(lines)
