#!/usr/bin/env python3
"""
Unit tests for the configuration a start command is allowed to carry.

The dispatch guard tested ``not data``, which rejects an empty configuration as
well as a missing one. Those are not the same thing:
``ControlThread._parse_user_options()`` fills in the default class for every
field it does not find, so ``{}`` is a complete request for a fully defaulted
run - and it is exactly what ``--run`` without ``--json`` produces.

That mattered because ``__main__`` never passed ``ethoscope_info["DATA"]`` on at
all. ``--run`` therefore always hit the guard, and the reply was discarded, so
the flag silently did nothing.
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../scripts"))

ETHOSCOPE_INFO = {
    "MACHINE_ID": "abc123",
    "MACHINE_NAME": "ETHOSCOPE_001",
    "GIT_VERSION": "deadbeef",
    "ETHOSCOPE_DIR": "/ethoscope_data",
    "ETHOSCOPE_VIDEOS_DIR": "/ethoscope_data/videos",
    "DATA": {},
}


class IdleControl:
    """A control thread that has finished, so the device counts as free."""

    def __init__(self, *args, **kwargs):
        self.info = {"status": "stopped"}
        self.kwargs = kwargs
        self.started = False

    def is_alive(self):
        return self.started

    def start(self):
        self.started = True


@pytest.fixture
def listener():
    """A commandingThread with no socket bound, so only its dispatch runs."""
    from device_listener import commandingThread

    def _build():
        thread = commandingThread.__new__(commandingThread)
        thread.control = IdleControl()
        thread.ethoscope_info = ETHOSCOPE_INFO
        return thread

    return _build


class TestStartDataGuard:
    def test_an_empty_config_means_use_the_defaults(self, listener):
        """Regression: {} was refused, so --run without --json did nothing."""
        import device_listener

        thread = listener()
        with patch.object(device_listener, "ControlThread", IdleControl):
            result = thread.action("start", {})

        assert result == "Starting tracking activity"
        assert thread.control.started

    def test_no_config_at_all_is_still_refused(self, listener):
        """ethoclient sends None when the operator passes no -d; that is a slip."""
        thread = listener()

        assert thread.action("start", None) == "This action requires JSON data"

    def test_the_same_holds_for_recording(self, listener):
        import device_listener

        thread = listener()
        with patch.object(device_listener, "ControlThreadVideoRecording", IdleControl):
            result = thread.action("start_record", {})

        assert result == "Starting recording or streaming activity"
        assert thread.control.started

    def test_a_real_config_still_reaches_the_control_thread(self, listener):
        """The normal path from the node must be unaffected."""
        import device_listener

        options = {"roi_builder": {"name": "FileBasedROIBuilder", "arguments": {}}}
        thread = listener()
        with patch.object(device_listener, "ControlThread", IdleControl):
            thread.action("start", options)

        assert thread.control.kwargs["data"] == options
