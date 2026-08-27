#!/usr/bin/env python3
"""
Unit tests for camera presence and sensor detection.

Both used to dispatch on the Pi model, assuming Pi 2/3 ran the legacy MMAL
firmware camera and Pi 4 ran libcamera. One image now boots every model on
KMS + ``camera_auto_detect=1``, so that assumption inverted:

* a Pi 3 on that image has no ``bcm2835-camera`` device and ``vcgencmd`` reports
  ``detected=0``, so the model-keyed ``hasPiCamera()`` called a working camera
  missing - and the deployed fleet is Pi 3;
* ``_get_camera_sensor_info()``'s fallback was gated on ``isMachinePI(4)``,
  an equality test, so a Pi 3 or Pi 5 had one detection method and no backup;
* a Pi 5 fell off the end of ``hasPiCamera()`` and got an unconditional False.

Separately the fallback named ``libcamera-hello``, which Raspberry Pi OS renamed
to ``rpicam-hello`` and dropped in Trixie. Shelled out through ``os.popen()``
that rotted silently: the shell wrote "command not found" to stderr, ``read()``
returned "", the regex matched nothing, and the caller concluded "no camera".
"""

from unittest.mock import MagicMock, patch

import pytest

from ethoscope.utils import pi

LIST_CAMERAS_OUTPUT = (
    "Available cameras\n-----------------\n"
    "0 : imx219 [3280x2464 10-bit RGGB] (/base/soc/i2c0mux/i2c@1/imx219@10)\n"
)


def _on_pi(model):
    """Pretend to be running on the given Pi generation."""
    return patch.object(
        pi, "pi_version", return_value={"model_number": model, "model_type": "Model B"}
    )


def _popen_returning(text):
    """Patch os.popen so the probed command yields `text`."""
    fake = MagicMock()
    fake.return_value.__enter__.return_value.read.return_value = text
    return patch("os.popen", fake)


class TestCameraCliName:
    """Which binary the libcamera probe actually calls."""

    def test_rpicam_is_preferred(self):
        """The current name on Bookworm and later."""
        with patch.object(
            pi.shutil, "which", side_effect=lambda n: n == "rpicam-hello"
        ):
            assert pi._camera_cli() == "rpicam-hello"

    def test_libcamera_is_accepted_on_older_images(self):
        """Older cards still carry only the pre-rename tool."""
        with patch.object(
            pi.shutil, "which", side_effect=lambda n: n == "libcamera-hello"
        ):
            assert pi._camera_cli() == "libcamera-hello"

    def test_neither_installed_is_reported_not_guessed(self):
        """Regression: the hardcoded name failed invisibly through os.popen."""
        with patch.object(pi.shutil, "which", return_value=None):
            assert pi._camera_cli() is None

    def test_a_missing_cli_is_not_shelled_out(self):
        """Nothing should be executed when the tool is known to be absent."""
        with patch.object(pi, "_camera_cli", return_value=None):
            with patch("os.popen") as popen:
                assert pi._detect_camera_via_libcamera_cli() is None
        popen.assert_not_called()

    def test_the_sensor_name_is_parsed_from_the_listing(self):
        with patch.object(pi, "_camera_cli", return_value="rpicam-hello"):
            with _popen_returning(LIST_CAMERAS_OUTPUT):
                assert pi._detect_camera_via_libcamera_cli() == "imx219"


class TestSensorInfoIsNotPi4Only:
    @pytest.mark.parametrize("model", [3, 4, 5])
    def test_the_cli_fallback_runs_on_every_model(self, model):
        """Regression: gated on isMachinePI(4), so Pi 3 and Pi 5 had no backup."""
        with _on_pi(model):
            with patch.object(pi, "_detect_camera_via_i2c", return_value=None):
                with patch.object(pi, "_camera_cli", return_value="rpicam-hello"):
                    with _popen_returning(LIST_CAMERAS_OUTPUT):
                        assert pi._get_camera_sensor_info() == "imx219"

    def test_i2c_wins_and_the_cli_is_not_started(self):
        """The CLI starts the camera stack; don't pay for it when I2C answered."""
        with _on_pi(4):
            with patch.object(pi, "_detect_camera_via_i2c", return_value="imx477"):
                with patch.object(pi, "_detect_camera_via_libcamera_cli") as cli:
                    assert pi._get_camera_sensor_info() == "imx477"
        cli.assert_not_called()

    def test_total_failure_is_said_out_loud(self, caplog):
        """Silence here becomes a silently untuned, dim run (issue #222)."""
        with _on_pi(3):
            with patch.object(pi, "_detect_camera_via_i2c", return_value=None):
                with patch.object(
                    pi, "_detect_camera_via_libcamera_cli", return_value=None
                ):
                    assert pi._get_camera_sensor_info() is None

        assert "could not determine the camera sensor" in caplog.text.lower()


class TestHasPiCameraIsStackNotModel:
    def test_a_pi3_on_the_kms_image_is_detected(self):
        """The core regression: the whole fleet is Pi 3 and moving to that image.

        Under KMS there is no bcm2835-camera device and vcgencmd says
        detected=0, so the I2C binding is the only positive evidence.
        """
        with _on_pi(3):
            with patch.object(pi, "_detect_camera_via_i2c", return_value="imx219"):
                assert pi.hasPiCamera() is True

    def test_a_pi5_is_no_longer_unconditionally_false(self):
        """Pi 5 matched no model branch and fell off the end."""
        with _on_pi(5):
            with patch.object(pi, "_detect_camera_via_i2c", return_value="imx708"):
                assert pi.hasPiCamera() is True

    def test_a_legacy_pi3_still_works(self):
        """Cards still on the MMAL stack must not regress."""
        with _on_pi(3):
            with patch.object(pi, "_detect_camera_via_i2c", return_value=None):
                with patch.object(
                    pi, "_detect_camera_via_v4l2_subdev", return_value=False
                ):
                    with patch.object(
                        pi, "_detect_camera_via_bcm2835_platform", return_value=True
                    ):
                        assert pi.hasPiCamera() is True

    def test_a_failing_probe_does_not_end_the_chain(self):
        """A probe that cannot run is not evidence of absence."""
        with _on_pi(4):
            with patch.object(
                pi, "_detect_camera_via_i2c", side_effect=OSError("boom")
            ):
                with patch.object(
                    pi, "_detect_camera_via_v4l2_subdev", return_value=True
                ):
                    assert pi.hasPiCamera() is True

    def test_no_evidence_at_all_is_still_false(self, caplog):
        with _on_pi(4):
            with patch.object(pi, "_detect_camera_via_i2c", return_value=None):
                with patch.object(
                    pi, "_detect_camera_via_v4l2_subdev", return_value=False
                ):
                    with patch.object(
                        pi, "_detect_camera_via_bcm2835_platform", return_value=False
                    ):
                        with patch.object(
                            pi, "_legacy_camera_detection", return_value=False
                        ):
                            with patch.object(
                                pi,
                                "_detect_camera_via_libcamera_cli",
                                return_value=None,
                            ):
                                assert pi.hasPiCamera() is False

        assert "no camera detected by any probe" in caplog.text.lower()

    def test_a_non_pi_is_short_circuited(self):
        """No probing at all off a Pi."""
        with _on_pi(0):
            with patch.object(pi, "_detect_camera_via_i2c") as i2c:
                assert pi.hasPiCamera() is False
        i2c.assert_not_called()
