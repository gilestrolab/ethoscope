#!/usr/bin/env python3
"""
Unit tests for the acquisition context recorded in the METADATA table.

Sleep scoring depends on the sampling rate and on image noise, which in turn
depend on the FPS cap, the analogue gain, the camera tuning and the Pi
generation. None of that used to be recorded, so a results database could not
be audited after the fact and two experiments could not be shown to be
comparable (issue #222).

Two properties are tested here:

* every field is present and stored as a string (or None), since METADATA is a
  field/value table of TEXT;
* collection is defensive - a probe that raises must degrade to None rather
  than prevent an experiment from starting. Diagnostics must never be the
  reason a run fails.
"""

from unittest.mock import patch

from ethoscope.control.tracking import ControlThread

EXPECTED_FIELDS = {
    "maxfps_setting",
    "target_fps",
    "gain_setting",
    "exposure_decoupled",
    "camera_tuning_expected",
    "camera_tuning_loaded",
    "camera_sensor",
    "pi_version",
    "picamera2_version",
    "tracker_class",
}


class _FakeCam:
    width = 1280
    height = 960
    _target_fps = 5.0
    _exposure_decoupled = True


class _FakeTracker:
    pass


def test_records_every_acquisition_field():
    """All context fields are present, whatever the platform."""
    metadata = ControlThread._acquisition_metadata(_FakeCam(), _FakeTracker)

    assert set(metadata) == EXPECTED_FIELDS


def test_values_are_text_or_none():
    """METADATA is a field/value table of TEXT; values must survive that."""
    metadata = ControlThread._acquisition_metadata(_FakeCam(), _FakeTracker)

    for key, value in metadata.items():
        assert value is None or isinstance(value, str), f"{key} is {type(value)}"


def test_reads_the_acquisition_regime_from_the_camera():
    """The FPS asked for and the exposure regime come from the live camera."""
    metadata = ControlThread._acquisition_metadata(_FakeCam(), _FakeTracker)

    assert metadata["target_fps"] == "5.0"
    assert metadata["exposure_decoupled"] == "True"
    assert metadata["tracker_class"] == "_FakeTracker"


def test_a_failing_probe_does_not_break_the_experiment():
    """A probe that raises degrades to None instead of propagating.

    This is the important one: an experiment must never fail to start because
    a diagnostic could not be collected.
    """
    with patch(
        "ethoscope.control.tracking.pi.get_maxfps_setting",
        side_effect=OSError("boom"),
    ):
        metadata = ControlThread._acquisition_metadata(_FakeCam(), _FakeTracker)

    assert metadata["maxfps_setting"] is None
    # The rest is still collected.
    assert metadata["target_fps"] == "5.0"


def test_camera_without_the_expected_attributes_is_tolerated():
    """Older or virtual cameras may not expose the tracking attributes."""

    class _Bare:
        pass

    metadata = ControlThread._acquisition_metadata(_Bare(), None)

    assert metadata["target_fps"] is None
    assert metadata["exposure_decoupled"] is None
    assert metadata["tracker_class"] is None


def test_records_the_tuning_actually_loaded():
    """The loaded tuning is recorded so a fallback is visible in the data."""
    with patch(
        "ethoscope.control.tracking.pi.get_camera_tuning_status",
        return_value="DEFAULT",
    ):
        metadata = ControlThread._acquisition_metadata(_FakeCam(), _FakeTracker)

    assert metadata["camera_tuning_loaded"] == "DEFAULT"
