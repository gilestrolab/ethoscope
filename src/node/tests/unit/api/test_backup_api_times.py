"""
Unit tests for when each device was last backed up, as /backup/status reports it.

The home page's "Time since backup" column never showed a time: /backup/status
hardcoded last_backup to 0 although the rsync daemon records every job. Icons were
green whenever the node held data, so ETHOSCOPE_265 and 359, whose jobs failed every
sweep (2026-10-09), looked healthy. Nor did anything say when the next sweep would run.
"""

import json
from unittest.mock import Mock, patch

import pytest

from ethoscope_node.api.backup_api import BackupAPI

ONLINE_INFO = {
    "backup_status": {
        "mysql": {"available": False},
        "sqlite": {"available": True, "total_size_bytes": 2048, "database_count": 2},
        "video": {"available": True, "total_size_bytes": 4096, "file_count": 5},
    }
}

CYCLE = {"interval": 300, "count": 12, "last_started": 1000, "next_at": 1330}


def rsync_record(started, ended, result, last_success, message=""):
    """A device as the rsync daemon's /status reports it (a serialised BackupStatus)."""
    return {
        "name": "ETHOSCOPE_265",
        "started": started,
        "ended": ended,
        "processing": False,
        "progress": {"status": result, "message": message},
        "last_success": last_success,
    }


@pytest.fixture
def api():
    server = Mock()
    server.device_scanner = Mock()
    return BackupAPI(server)


def summary(api, status, rsync_devices):
    """Summarise one device, ETHOSCOPE_265, with the given scanner status."""
    api.device_scanner.get_all_devices_info.return_value = {
        "dev265": {"name": "ETHOSCOPE_265", "status": status, "databases": {"x": 1}}
    }
    with patch(
        "ethoscope_node.backup.helpers.get_device_backup_info",
        return_value=ONLINE_INFO,
    ):
        return api._get_devices_backup_summary([], rsync_devices)["dev265"]


class TestLastBackup:
    def test_a_successful_job_gives_the_time_of_the_last_backup(self, api):
        device = summary(
            api, "running", {"dev265": rsync_record(900, 960, "completed", 960)}
        )

        assert device["backup_types"]["sqlite"]["last_backup"] == 960
        assert device["backup_types"]["video"]["last_backup"] == 960
        assert device["backup_types"]["sqlite"]["status"] == "success"
        assert device["last_job"] == {
            "last_success": 960,
            "started": 900,
            "ended": 960,
            "result": "completed",
            "message": "",
        }

    def test_a_failed_job_turns_the_icons_red_and_keeps_the_last_success(self, api):
        record = rsync_record(1200, 1210, "error", 960, "Backup failed")
        device = summary(api, "stopped", {"dev265": record})

        assert device["backup_types"]["sqlite"]["status"] == "error"
        assert device["backup_types"]["video"]["status"] == "error"
        assert device["backup_types"]["sqlite"]["last_backup"] == 960
        assert device["last_job"]["result"] == "error"
        assert device["last_job"]["message"] == "Backup failed"

    def test_a_crashed_job_reports_when_it_crashed(self, api):
        # Reason: the daemon records a crash as ended = -1, the time in progress.
        record = rsync_record(1200, -1, "error", 0)
        record["progress"]["completion_time"] = 1234
        device = summary(api, "stopped", {"dev265": record})

        assert device["last_job"]["ended"] == 1234
        assert device["backup_types"]["sqlite"]["last_backup"] == 0

    def test_a_daemon_older_than_last_success_still_gives_a_time(self, api):
        record = rsync_record(900, 960, "completed", 0)
        del record["last_success"]
        device = summary(api, "running", {"dev265": record})

        assert device["last_job"]["last_success"] == 960

    def test_an_offline_device_still_reports_its_last_backup(self, api):
        device = summary(
            api, "offline", {"dev265": rsync_record(900, 960, "completed", 960)}
        )

        assert device["backup_types"]["sqlite"]["status"] == "offline"
        assert device["backup_types"]["sqlite"]["last_backup"] == 960
        assert device["last_job"]["last_success"] == 960

    def test_a_device_no_daemon_knows_has_no_last_job(self, api):
        device = summary(api, "running", {})

        assert device["last_job"] is None
        assert device["backup_types"]["sqlite"]["last_backup"] == 0
        # Without a job to go by, the node's data decides, as before.
        assert device["backup_types"]["sqlite"]["status"] == "success"


class TestCycle:
    def status(self, api, rsync_status):
        """GET /backup/status with the MySQL daemon down and the given rsync status."""
        api.device_scanner.get_all_devices_info.return_value = {}
        api.set_json_response = Mock()
        with patch.object(
            api,
            "_fetch_backup_service_status",
            side_effect=[{"error": "down"}, rsync_status],
        ):
            return json.loads(api._get_backup_status())

    def test_the_next_sweep_comes_from_the_rsync_daemon(self, api):
        result = self.status(api, {"devices": {}, "cycle": CYCLE})

        assert result["cycle"] == CYCLE

    def test_a_daemon_too_old_to_report_its_cycle_gives_none(self, api):
        result = self.status(api, {"devices": {}})

        assert result["cycle"] is None

    def test_a_daemon_that_is_down_gives_none(self, api):
        result = self.status(api, {"error": "Rsync backup service unavailable"})

        assert result["cycle"] is None

    def test_the_rsync_records_reach_the_device_summary(self, api):
        api.device_scanner.get_all_devices_info.return_value = {
            "dev265": {"name": "ETHOSCOPE_265", "status": "offline"}
        }
        api.set_json_response = Mock()
        rsync = {"devices": {"dev265": rsync_record(900, 960, "completed", 960)}}
        with patch.object(
            api,
            "_fetch_backup_service_status",
            side_effect=[{"error": "down"}, rsync],
        ):
            result = json.loads(api._get_backup_status())

        assert result["devices"]["dev265"]["last_job"]["last_success"] == 960
