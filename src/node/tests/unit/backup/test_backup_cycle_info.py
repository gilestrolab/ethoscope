"""
Unit tests for what the backup daemon records about time: when each device was last
backed up successfully, and when the next cycle will start.

A job's started/ended describe the latest attempt, so one failed job used to erase when
the device's data was last secured. The next cycle's start was computed and slept on,
but never recorded, so no page could say when the next sweep would run.
"""

from unittest.mock import Mock, patch

from ethoscope_node.backup.helpers import BackupStatus, GenericBackupWrapper


def wrapper(tmp_path):
    return GenericBackupWrapper(str(tmp_path), "localhost")


def finish(w, device_id, success, at):
    """End a job for the device at the given epoch, as the daemon does."""
    w.backup_status.setdefault(device_id, BackupStatus(name="ETHOSCOPE_265"))
    job = Mock()
    job.check_sync_status.return_value = {}
    with patch("ethoscope_node.backup.helpers.time.time", return_value=at):
        w._finalize_backup_status(device_id, job, success)


class TestLastSuccess:
    def test_a_successful_job_records_when_it_ended(self, tmp_path):
        w = wrapper(tmp_path)
        finish(w, "dev265", True, 1000)

        assert w.backup_status["dev265"].last_success == 1000

    def test_a_failed_job_keeps_the_previous_success(self, tmp_path):
        w = wrapper(tmp_path)
        finish(w, "dev265", True, 1000)
        finish(w, "dev265", False, 1300)

        assert w.backup_status["dev265"].ended == 1300
        assert w.backup_status["dev265"].last_success == 1000

    def test_a_crashed_job_keeps_the_previous_success(self, tmp_path):
        w = wrapper(tmp_path)
        finish(w, "dev265", True, 1000)
        w._handle_backup_failure("dev265", "rsync died")

        assert w.backup_status["dev265"].ended == -1
        assert w.backup_status["dev265"].last_success == 1000

    def test_a_device_never_backed_up_has_no_last_success(self, tmp_path):
        w = wrapper(tmp_path)
        finish(w, "dev265", False, 1300)

        assert w.backup_status["dev265"].last_success == 0


class TestNextCycle:
    def test_the_next_cycle_is_recorded_before_the_wait(self, tmp_path):
        w = wrapper(tmp_path)
        with patch("ethoscope_node.backup.helpers.time.time", return_value=1000):
            wait = w._schedule_next_cycle(consecutive_failures=0)

        assert wait == w.DEFAULT_BACKUP_INTERVAL
        assert w.get_cycle_info()["next_at"] == 1000 + wait

    def test_failures_push_the_next_cycle_back(self, tmp_path):
        w = wrapper(tmp_path)
        with patch("ethoscope_node.backup.helpers.time.time", return_value=1000):
            wait = w._schedule_next_cycle(consecutive_failures=3)

        assert wait > w.DEFAULT_BACKUP_INTERVAL
        assert w.get_cycle_info()["next_at"] == 1000 + wait

    def test_no_next_cycle_is_reported_while_one_runs(self, tmp_path):
        w = wrapper(tmp_path)
        w._next_cycle_at = 1330  # left over from the previous wait
        seen = {}

        def cycle(executor):
            seen.update(w.get_cycle_info())
            w.stop()

        w._execute_backup_cycle_with_recovery = cycle
        w.run()

        assert seen["next_at"] == 0
        assert seen["count"] == 1
        assert seen["last_started"] > 0

    def test_a_daemon_that_has_not_run_reports_an_empty_cycle(self, tmp_path):
        info = wrapper(tmp_path).get_cycle_info()

        assert info == {
            "interval": GenericBackupWrapper.DEFAULT_BACKUP_INTERVAL,
            "count": 0,
            "last_started": 0,
            "next_at": 0,
        }
