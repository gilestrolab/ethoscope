#!/usr/bin/env python3
"""
Unit tests for caching the detected camera model.

``_save_camera_info`` writes what libcamera reported to
``/etc/ethoscope/picamera-version`` so other processes can read the camera model
without opening the camera. It is a cache, not part of acquiring frames.

It used to write unguarded from inside the frame grabber's try block, so any
unwritable path - an unprivileged process, a read-only filesystem, a full disk -
raised OSError out of the grabber. The handler there matches on the substring
"camera", which that path contains, so the failure was reported as::

    Camera hardware not available ... Check the camera ribbon cable and sensor.

A failed cache write must not stop acquisition, and must not produce a hardware
diagnosis that sends someone to inspect a perfectly good ribbon cable.
"""

import logging
from unittest.mock import mock_open, patch

import pytest

from ethoscope.hardware.input import cameras
from ethoscope.hardware.input.cameras import PiFrameGrabber

CAMERA_INFO = {"Model": "imx219", "Location": 2, "Num": 0}


@pytest.fixture
def grabber():
    """A grabber instance without touching hardware."""
    return PiFrameGrabber.__new__(PiFrameGrabber)


@pytest.mark.parametrize(
    "error",
    [PermissionError(13, "Permission denied"), OSError(28, "No space left on device")],
    ids=["unwritable", "disk-full"],
)
def test_an_unwritable_cache_does_not_raise(grabber, error, caplog):
    """Regression: this surfaced as a camera hardware fault."""
    with patch.object(cameras.pi, "ensure_dir_exists"):
        with patch("builtins.open", side_effect=error):
            with caplog.at_level(logging.WARNING):
                grabber._save_camera_info(dict(CAMERA_INFO), save_path="/nope/x")

    assert "Could not cache the detected camera" in caplog.text
    assert "Acquisition is unaffected" in caplog.text


def test_a_failed_write_is_not_reported_as_a_hardware_fault(grabber, caplog):
    """The message must not send anyone to check the ribbon cable."""
    with patch.object(cameras.pi, "ensure_dir_exists"):
        with patch("builtins.open", side_effect=PermissionError(13, "denied")):
            with caplog.at_level(logging.WARNING):
                grabber._save_camera_info(dict(CAMERA_INFO), save_path="/nope/x")

    assert "ribbon" not in caplog.text.lower()
    assert "hardware not available" not in caplog.text.lower()


def test_a_writable_cache_still_records_the_camera(grabber):
    """The happy path must keep working, including the compatibility key."""
    handle = mock_open()
    info = dict(CAMERA_INFO)
    with patch.object(cameras.pi, "ensure_dir_exists"):
        with patch("builtins.open", handle):
            grabber._save_camera_info(info, save_path="/tmp/x")

    handle.assert_called_once_with("/tmp/x", "w")
    written = "".join(c.args[0] for c in handle().write.call_args_list)
    assert "imx219" in written
    # picamera and picamera2 are read through the same key downstream
    assert info["IFD0.Model"] == "imx219"
