#!/usr/bin/env python3
"""
Unit tests for the listener's guard against overlapping activities.

``start``, ``start_record`` and ``stream`` used to overwrite ``self.control``
whatever the device was doing. The previous control thread stayed alive - still
holding the camera, still writing to its database - but nothing referenced it
any more, so it could never be stopped. The replacement thread then failed to
acquire the camera ("Device or resource busy"), sat in ``initialising``, and two
minutes later ``ControlThread``'s initialisation watchdog SIGKILLed the whole
listener, taking the healthy experiment with it.

``stop`` made that unrecoverable: it was gated on a status of running /
recording / streaming, so a thread stuck in ``initialising`` could not be
stopped at all and the Pi had to be rebooted.

These tests pin both halves: a busy device refuses to start something new, and
anything alive can always be stopped.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../scripts"))

BUSY_ACTIONS = ["start", "start_record", "stream"]


class FakeControl:
    """The parts of a control thread the listener's dispatch touches."""

    def __init__(self, status="running", alive=True, dies_on_stop=True):
        self.info = {"status": status}
        self.alive = alive
        self.dies_on_stop = dies_on_stop
        self.stop_calls = 0
        self.join_calls = []

    def is_alive(self):
        return self.alive

    def stop(self):
        self.stop_calls += 1
        if self.dies_on_stop:
            self.alive = False
            self.info["status"] = "stopped"

    def join(self, timeout=None):
        self.join_calls.append(timeout)


@pytest.fixture
def listener():
    """A commandingThread with no socket bound, so only its dispatch is exercised."""
    from device_listener import commandingThread

    def _build(control):
        thread = commandingThread.__new__(commandingThread)
        thread.control = control
        return thread

    return _build


class TestBusyDeviceRefusesToStart:
    @pytest.mark.parametrize("action", BUSY_ACTIONS)
    @pytest.mark.parametrize("status", ["running", "initialising", "recording"])
    def test_a_live_thread_blocks_a_new_activity(self, listener, action, status):
        """The running experiment is data; it is not replaced by accident."""
        control = FakeControl(status=status, alive=True)
        thread = listener(control)

        result = thread.action(action, {"roi_builder": {}})

        assert result.startswith("ERROR:")
        assert status in result
        assert thread.control is control, "the live thread was orphaned"

    @pytest.mark.parametrize("action", BUSY_ACTIONS)
    def test_initialising_counts_as_busy(self, listener, action):
        """It is the state a camera that will not open leaves the device in.

        The thread already holds the camera even though it does not yet call
        itself "running", which is exactly the case that used to wedge.
        """
        control = FakeControl(status="initialising", alive=True)
        thread = listener(control)

        assert thread.action(action, {"roi_builder": {}}).startswith("ERROR:")

    def test_an_idle_device_is_not_blocked(self, listener):
        """A dead thread must not stop the device being used again."""
        control = FakeControl(status="stopped", alive=False)
        thread = listener(control)

        assert thread._busy_with() is None


class TestStopIsAlwaysAvailable:
    @pytest.mark.parametrize(
        "status", ["running", "recording", "streaming", "initialising", "stopping"]
    )
    def test_anything_alive_can_be_stopped(self, listener, status):
        """Regression: "initialising" used to be unstoppable, needing a reboot."""
        control = FakeControl(status=status, alive=True)
        thread = listener(control)

        result = thread.action("stop")

        assert control.stop_calls == 1
        assert result == "Stopping ethoscope activity"

    def test_the_join_is_bounded(self, listener):
        """An unbounded join would hang the client on a wedged thread."""
        control = FakeControl(alive=True)
        thread = listener(control)

        thread.action("stop")

        assert control.join_calls == [thread._STOP_JOIN_TIMEOUT]

    def test_stopping_an_idle_device_says_so(self, listener):
        control = FakeControl(status="stopped", alive=False)
        thread = listener(control)

        result = thread.action("stop")

        assert control.stop_calls == 0
        assert result == "There is no activity to stop."

    def test_a_thread_that_will_not_die_is_reported(self, listener, caplog):
        """Answering "stopped" when it is not would be a lie the next start pays for."""
        control = FakeControl(alive=True, dies_on_stop=False)
        thread = listener(control)

        thread.action("stop")

        assert "still holding the camera" in caplog.text
        # And the device correctly still refuses to start something new.
        assert thread.action("start", {"roi_builder": {}}).startswith("ERROR:")


class TestMaintenanceActionsRespectABusyDevice:
    @pytest.mark.parametrize("action", ["remove", "restart"])
    def test_they_are_refused_while_an_experiment_is_alive(self, listener, action):
        """Both used to look only at the status, so they fired mid-initialisation."""
        control = FakeControl(status="initialising", alive=True)
        thread = listener(control)

        assert thread.action(action) == "This ethoscope action is not available."
