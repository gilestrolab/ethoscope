"""
Unit tests for stopping the backup service promptly.

A backup cycle queues every device at once, and the interpreter's exit waits for that
queue to drain. On 2026-11-13 the unified service, sent SIGTERM mid-cycle, logged
"Shutdown complete." and then started backups of 13 more devices until systemd killed
it 90 s later. The unit was left failed, and the node had no results backup for days.
"""

import json
import subprocess
import time
from unittest.mock import Mock, patch

from ethoscope_node.backup.helpers import (
    BaseBackupClass,
    GenericBackupWrapper,
    UnifiedRsyncBackupClass,
)

DEVICE = {"id": "aaa", "name": "ETHOSCOPE_012", "ip": "10.0.0.12", "status": "running"}


def wrapper(tmp_path, **kwargs):
    """A wrapper that never touches the network."""
    w = GenericBackupWrapper(str(tmp_path), "localhost", **kwargs)
    w._handle_backup_failure = Mock()
    return w


def sleeper(seconds: int = 30) -> subprocess.Popen:
    """A child process that stands in for a long rsync."""
    return subprocess.Popen(["sleep", str(seconds)])


class StepwiseJob:
    """A backup of three steps, each announced before it starts, as real ones are."""

    def __init__(self, on_step=None):
        self.started = []
        self.closed = False
        self._on_step = on_step or (lambda step: None)

    def backup(self):
        try:
            for step in ("checkpoint", "results", "videos"):
                yield json.dumps({"status": "info", "message": f"Starting {step}"})
                self.started.append(step)
                self._on_step(step)
        finally:
            self.closed = True


class SleepingJob(BaseBackupClass):
    """A backup whose one step is a child process that runs for 30 s."""

    def backup(self):
        yield self._yield_status("info", "Starting the copy")
        self._process = sleeper()
        self._process.wait()
        yield self._yield_status("info", "Copy ended")


class SlowFleet(GenericBackupWrapper):
    """The real backup loop, with devices whose backups take 30 s each."""

    def __init__(self, tmp_path, devices, max_threads):
        super().__init__(str(tmp_path), "localhost", max_threads=max_threads)
        self.devices = devices
        self.started = []

    def find_devices(self, only_active: bool = True) -> list[dict]:
        return self.devices

    def initiate_backup_job(self, device_info: dict) -> bool:
        job = SleepingJob(device_info, self._results_dir)
        self._backup_instances[device_info["id"]] = job
        self._initialize_backup_status(device_info["id"], device_info)
        self.started.append(device_info["id"])
        return self._execute_backup_job(device_info["id"], job)


class TestNoNewWorkAfterStop:
    def test_a_job_still_queued_at_the_stop_does_nothing(self, tmp_path):
        w = wrapper(tmp_path)
        w.initiate_backup_job = Mock(return_value=True)

        w.stop()

        assert w._execute_backup_job_safely(DEVICE) is False
        w.initiate_backup_job.assert_not_called()

    def test_a_running_backup_starts_no_further_step(self, tmp_path):
        w = wrapper(tmp_path)
        w._initialize_backup_status(DEVICE["id"], DEVICE)
        # SIGTERM arrives while the first step runs
        job = StepwiseJob(on_step=lambda step: w.stop())

        assert w._execute_backup_job(DEVICE["id"], job) is False

        assert job.started == ["checkpoint"]
        assert job.closed

    def test_without_a_stop_every_step_runs(self, tmp_path):
        w = wrapper(tmp_path)
        w._initialize_backup_status(DEVICE["id"], DEVICE)
        job = StepwiseJob()

        assert w._execute_backup_job(DEVICE["id"], job) is True

        assert job.started == ["checkpoint", "results", "videos"]

    def test_the_cycle_stops_waiting_once_stopped(self, tmp_path):
        w = wrapper(tmp_path)
        never_asked = Mock()
        w.stop()

        w._wait_for_backup_completion_safely([(never_asked, "aaa", "ETHOSCOPE_012")])

        never_asked.result.assert_not_called()


class TestRunningRsyncsEnd:
    def test_stop_ends_the_child_process_of_a_running_job(self, tmp_path):
        w = wrapper(tmp_path)
        job = UnifiedRsyncBackupClass(DEVICE, str(tmp_path), str(tmp_path))
        job._process = sleeper()
        w._backup_instances[DEVICE["id"]] = job

        w.stop()

        assert job._process.wait(timeout=5) is not None

    def test_terminate_without_a_child_process_is_harmless(self, tmp_path):
        job = UnifiedRsyncBackupClass(DEVICE, str(tmp_path), str(tmp_path))
        job.terminate()

        job._process = sleeper(0)
        job._process.wait()
        job.terminate()  # already ended

    def test_closing_the_rsync_step_ends_its_rsync(self, tmp_path):
        """A step closed mid-transfer (service stopping) must not leave rsync behind."""
        job = UnifiedRsyncBackupClass(DEVICE, str(tmp_path), str(tmp_path))
        real_popen = subprocess.Popen
        fake_rsync = "echo '>f+++++++++ ETHOSCOPE_012/run/a.db'; exec sleep 30"

        def popen(cmd, **kwargs):
            return real_popen(["sh", "-c", fake_rsync], **kwargs)

        with patch("subprocess.Popen", side_effect=popen):
            step = job._rsync_directory(
                source_dir="/ethoscope_data/results/",
                destination_dir=str(tmp_path / "results"),
                private_key_path="/nonexistent",
                operation_name="results",
            )
            for message in step:
                if "Processing a.db" in message:
                    break
            rsync = job._process
            assert rsync.poll() is None

            step.close()

        assert rsync.wait(timeout=5) is not None
        assert job._process is None


class TestTheServiceStopsWithinSeconds:
    def test_the_loop_ends_promptly_with_jobs_running_and_queued(self, tmp_path):
        devices = [
            {"id": f"d{i}", "name": f"ETHOSCOPE_{i:03d}", "ip": f"10.0.0.{i}"}
            for i in range(6)
        ]
        w = SlowFleet(tmp_path, devices, max_threads=2)
        w.start()
        deadline = time.time() + 10
        while len(w.started) < 2 or any(
            getattr(w._backup_instances.get(d), "_process", None) is None
            for d in w.started
        ):
            assert time.time() < deadline, "the first two backups never started"
            time.sleep(0.05)

        stopped_at = time.time()
        w.stop()
        w.join(timeout=10)

        # Reason: the loop owns the thread pool; once it returns, every worker has
        # ended, so the interpreter's exit has nothing left to wait for.
        assert not w.is_alive()
        assert time.time() - stopped_at < 5
        assert len(w.started) == 2  # none of the four queued backups began
