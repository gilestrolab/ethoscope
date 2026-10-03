"""
Unit tests for keeping one backup job per device at a time.

A job can outlive the wait in a backup cycle: a recording crossing a weak WiFi link
takes hours. The next cycle used to start another job for the same device regardless,
so several rsyncs copied the same chunks over the same link at once (four from
ETHOSCOPE_361 on 2026-10-03), and a job still running was reported as failed.
"""

import concurrent.futures
from unittest.mock import Mock, patch

from ethoscope_node.backup.helpers import GenericBackupWrapper


class FakeExecutor:
    """Hands out futures that stay running until a test completes them."""

    def __init__(self):
        self.submitted = []

    def submit(self, fn, device):
        future = concurrent.futures.Future()
        self.submitted.append((device["id"], future))
        return future


class StillRunning:
    """A future whose wait always times out, as a job copying for hours would."""

    def result(self, timeout=None):
        raise concurrent.futures.TimeoutError()


DEVICES = [
    {"id": "aaa", "name": "ETHOSCOPE_361"},
    {"id": "bbb", "name": "ETHOSCOPE_354"},
]


def wrapper(tmp_path):
    w = GenericBackupWrapper(str(tmp_path), "localhost", video=True)
    w._validate_device_for_backup = Mock(return_value=True)
    w._handle_backup_failure = Mock()
    return w


class TestOneJobPerDevice:
    def test_a_device_still_being_backed_up_gets_no_second_job(self, tmp_path):
        w, executor = wrapper(tmp_path), FakeExecutor()
        w._submit_backup_jobs_safely(executor, DEVICES)
        executor.submitted[1][1].set_result(True)  # ETHOSCOPE_354 finished

        futures = w._submit_backup_jobs_safely(executor, DEVICES)

        assert [device_id for _, device_id, _ in futures] == ["bbb"]
        assert [device_id for device_id, _ in executor.submitted] == [
            "aaa",
            "bbb",
            "bbb",
        ]

    def test_a_new_job_starts_once_the_previous_one_ends(self, tmp_path):
        w, executor = wrapper(tmp_path), FakeExecutor()
        w._submit_backup_jobs_safely(executor, DEVICES[:1])
        executor.submitted[0][1].set_result(False)  # ended, even unsuccessfully

        futures = w._submit_backup_jobs_safely(executor, DEVICES[:1])

        assert len(futures) == 1

    def test_a_job_still_running_is_not_reported_as_failed(self, tmp_path):
        w = wrapper(tmp_path)
        with patch.object(w._logger, "error") as logged_error:
            w._wait_for_backup_completion_safely(
                [(StillRunning(), "aaa", "ETHOSCOPE_361")]
            )

        w._handle_backup_failure.assert_not_called()
        logged_error.assert_not_called()
