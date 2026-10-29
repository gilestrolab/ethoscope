"""Unit tests for the firmware management module."""

import os
import shutil
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from ethoscope.hardware.interfaces.firmware import (
    FQBN_MAP,
    _get_fqbn,
    get_source_firmware_version,
    is_arduino_cli_available,
    parse_running_firmware,
)


class TestIsArduinoCliAvailable:
    """Tests for arduino-cli availability check."""

    @patch("shutil.which", return_value="/usr/local/bin/arduino-cli")
    def test_available(self, mock_which):
        assert is_arduino_cli_available() is True
        mock_which.assert_called_once_with("arduino-cli")

    @patch("shutil.which", return_value=None)
    def test_not_available(self, mock_which):
        assert is_arduino_cli_available() is False


class TestGetSourceFirmwareVersion:
    """Tests for parsing firmware version from .ino source."""

    def test_parses_version(self, tmp_path):
        ino = tmp_path / "test.ino"
        ino.write_text("const float VERSION = 1.3;\n#define MODULE 0\n")
        assert get_source_firmware_version(str(ino)) == 1.3

    def test_integer_version(self, tmp_path):
        ino = tmp_path / "test.ino"
        ino.write_text("const float VERSION = 2;\n")
        assert get_source_firmware_version(str(ino)) == 2.0

    def test_missing_file(self):
        assert get_source_firmware_version("/nonexistent/path.ino") is None

    def test_no_version_line(self, tmp_path):
        ino = tmp_path / "test.ino"
        ino.write_text("// no version here\nvoid setup() {}\n")
        assert get_source_firmware_version(str(ino)) is None

    def test_version_with_spaces(self, tmp_path):
        ino = tmp_path / "test.ino"
        ino.write_text("const  float  VERSION  =  2.5 ;\n")
        assert get_source_firmware_version(str(ino)) == 2.5


class TestParseRunningFirmware:
    """Tests for parsing firmware version string from teach response."""

    def test_standard_format(self):
        result = parse_running_firmware("FW-1.3;HW-10")
        assert result == {"fw": 1.3, "hw": 10}

    def test_different_version(self):
        result = parse_running_firmware("FW-2.0;HW-11")
        assert result == {"fw": 2.0, "hw": 11}

    def test_empty_string(self):
        assert parse_running_firmware("") == {}

    def test_none_input(self):
        assert parse_running_firmware(None) == {}

    def test_non_string_input(self):
        assert parse_running_firmware(123) == {}

    def test_malformed_input(self):
        assert parse_running_firmware("garbage") == {}

    def test_partial_match(self):
        assert parse_running_firmware("FW-1.3") == {}


class TestGetFqbn:
    """Tests for FQBN mapping."""

    def test_micro(self):
        assert _get_fqbn("micro") == "arduino:avr:micro"

    def test_nano(self):
        # "nano" is the Nano Every (2341:0058), a megaavr board.
        assert _get_fqbn("nano") == "arduino:megaavr:nona4809"

    def test_uno(self):
        assert _get_fqbn("uno") == "arduino:avr:uno"

    def test_leonardo(self):
        assert _get_fqbn("leonardo") == "arduino:avr:leonardo"

    def test_case_insensitive(self):
        assert _get_fqbn("MICRO") == "arduino:avr:micro"
        assert _get_fqbn("Nano") == "arduino:megaavr:nona4809"

    def test_unknown_model(self):
        assert _get_fqbn("unknown_board") is None

    def test_none_model(self):
        assert _get_fqbn(None) is None

    def test_empty_model(self):
        assert _get_fqbn("") is None


class TestGetFirmwareStatus:
    """Tests for firmware status checking."""

    @patch(
        "ethoscope.hardware.interfaces.firmware.is_arduino_cli_available",
        return_value=False,
    )
    def test_no_arduino_cli(self, mock_available):
        from ethoscope.hardware.interfaces.firmware import get_firmware_status

        result = get_firmware_status()
        assert result["arduino_cli_available"] is False

    @patch(
        "ethoscope.hardware.interfaces.firmware.is_arduino_cli_available",
        return_value=True,
    )
    @patch("ethoscope.hardware.interfaces.firmware.connectedUSB", return_value=({}, {}))
    @patch(
        "ethoscope.hardware.interfaces.firmware.get_source_firmware_version",
        return_value=1.3,
    )
    def test_no_arduino_connected(self, mock_ver, mock_usb, mock_available):
        from ethoscope.hardware.interfaces.firmware import get_firmware_status

        result = get_firmware_status()
        assert result["arduino_cli_available"] is True
        assert result["error"] == "No Arduino connected"

    @patch(
        "ethoscope.hardware.interfaces.firmware.is_arduino_cli_available",
        return_value=True,
    )
    @patch(
        "ethoscope.hardware.interfaces.firmware.connectedUSB",
        return_value=({}, {"arduino_micro": {"family": "arduino", "model": "micro"}}),
    )
    @patch(
        "ethoscope.hardware.interfaces.firmware.get_source_firmware_version",
        return_value=1.4,
    )
    @patch(
        "ethoscope.hardware.interfaces.firmware._find_serial_port",
        return_value="/dev/ttyACM0",
    )
    @patch(
        "ethoscope.hardware.interfaces.firmware._interrogate_arduino",
        return_value={
            "version": "FW-1.3;HW-10",
            "module": {"type": 0, "name": "N20 Sleep Deprivation Module"},
        },
    )
    def test_update_available(
        self, mock_interr, mock_port, mock_ver, mock_usb, mock_available
    ):
        from ethoscope.hardware.interfaces.firmware import get_firmware_status

        result = get_firmware_status()
        assert result["arduino_cli_available"] is True
        assert result["update_available"] is True
        assert result["source_version"] == 1.4
        assert result["running_fw"] == 1.3
        assert result["model"] == "micro"

    @patch(
        "ethoscope.hardware.interfaces.firmware.is_arduino_cli_available",
        return_value=True,
    )
    @patch(
        "ethoscope.hardware.interfaces.firmware.connectedUSB",
        return_value=({}, {"arduino_micro": {"family": "arduino", "model": "micro"}}),
    )
    @patch(
        "ethoscope.hardware.interfaces.firmware.get_source_firmware_version",
        return_value=1.3,
    )
    @patch(
        "ethoscope.hardware.interfaces.firmware._find_serial_port",
        return_value="/dev/ttyACM0",
    )
    @patch(
        "ethoscope.hardware.interfaces.firmware._interrogate_arduino",
        return_value={
            "version": "FW-1.3;HW-10",
            "module": {"type": 0},
        },
    )
    def test_up_to_date(
        self, mock_interr, mock_port, mock_ver, mock_usb, mock_available
    ):
        from ethoscope.hardware.interfaces.firmware import get_firmware_status

        result = get_firmware_status()
        assert result["update_available"] is False


class TestCompileFirmware:
    """Tests for firmware compilation."""

    @patch(
        "ethoscope.hardware.interfaces.firmware.is_arduino_cli_available",
        return_value=False,
    )
    def test_no_arduino_cli(self, mock_available):
        from ethoscope.hardware.interfaces.firmware import compile_firmware

        result = compile_firmware(fqbn="arduino:avr:micro")
        assert result["success"] is False
        assert "not available" in result["error"]

    @patch(
        "ethoscope.hardware.interfaces.firmware.is_arduino_cli_available",
        return_value=True,
    )
    def test_missing_fqbn(self, mock_available, tmp_path):
        ino = tmp_path / "test.ino"
        ino.write_text("const float VERSION = 1.0;\n")
        from ethoscope.hardware.interfaces.firmware import compile_firmware

        result = compile_firmware(ino_path=str(ino))
        assert result["success"] is False
        assert "FQBN" in result["error"]

    @patch(
        "ethoscope.hardware.interfaces.firmware.is_arduino_cli_available",
        return_value=True,
    )
    def test_missing_source(self, mock_available):
        from ethoscope.hardware.interfaces.firmware import compile_firmware

        result = compile_firmware(ino_path="/nonexistent.ino", fqbn="arduino:avr:micro")
        assert result["success"] is False
        assert "not found" in result["error"]


class TestCompileCommand:
    """The arduino-cli command a device runs for "Update Firmware"."""

    def _command(self, module=4, pcbversion=12):
        from ethoscope.hardware.interfaces.firmware import compile_firmware

        with (
            patch(
                "ethoscope.hardware.interfaces.firmware.is_arduino_cli_available",
                return_value=True,
            ),
            patch("ethoscope.hardware.interfaces.firmware.os.makedirs"),
            patch("ethoscope.hardware.interfaces.firmware.subprocess.run") as run,
        ):
            run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = compile_firmware(
                fqbn="arduino:avr:micro", module=module, pcbversion=pcbversion
            )
        assert result["success"] is True
        return run.call_args[0][0]

    def test_defines_go_through_the_user_flags_hook(self):
        cmd = self._command()
        assert "compiler.cpp.extra_flags=-DMODULE=4 -DPCBVERSION=12" in cmd

    def test_board_flags_are_left_alone(self):
        # build.extra_flags holds the board's own flags (the Micro's USB IDs);
        # setting it replaced them and the core failed with 'USB_VID' undeclared.
        cmd = self._command()
        assert not any(arg.startswith("build.extra_flags") for arg in cmd)

    def test_module_zero_is_passed(self):
        cmd = self._command(module=0, pcbversion=10)
        assert "compiler.cpp.extra_flags=-DMODULE=0 -DPCBVERSION=10" in cmd


def _core_installed(core):
    """Whether arduino-cli and the given core (e.g. "arduino:avr") are installed."""
    if shutil.which("arduino-cli") is None:
        return False
    listing = subprocess.run(
        ["arduino-cli", "core", "list"], capture_output=True, text=True
    )
    return f"{core} " in listing.stdout


def _sketch_copy(tmp_path, versions_h=None):
    """Copy the repository's sketch, as a device checkout has it (no versions.h)."""
    from ethoscope.hardware.interfaces.firmware import DEFAULT_INO_PATH

    sketch_dir = tmp_path / "ethoscope_multimodule"
    sketch_dir.mkdir()
    ino = sketch_dir / "ethoscope_multimodule.ino"
    shutil.copy(DEFAULT_INO_PATH, ino)
    if versions_h is not None:
        (sketch_dir / "versions.h").write_text(versions_h)
    return str(ino)


@pytest.mark.slow
class TestCompileFromCheckout:
    """Compile the real sketch with the real arduino-cli, as a device does."""

    @pytest.mark.parametrize(
        "fqbn,core",
        [
            ("arduino:avr:micro", "arduino:avr"),
            ("arduino:megaavr:nona4809", "arduino:megaavr"),
        ],
    )
    def test_compiles_without_versions_h(self, tmp_path, monkeypatch, fqbn, core):
        if not _core_installed(core):
            pytest.skip(f"arduino-cli with {core} not installed")
        from ethoscope.hardware.interfaces import firmware

        monkeypatch.setattr(firmware, "BUILD_DIR", str(tmp_path / "build"))
        result = firmware.compile_firmware(
            ino_path=_sketch_copy(tmp_path), fqbn=fqbn, module=4, pcbversion=12
        )
        assert result["success"], result.get("error")

    def test_values_read_from_the_board_win_over_versions_h(
        self, tmp_path, monkeypatch
    ):
        if not _core_installed("arduino:avr"):
            pytest.skip("arduino-cli with arduino:avr not installed")
        from ethoscope.hardware.interfaces import firmware

        build = tmp_path / "build"
        monkeypatch.setattr(firmware, "BUILD_DIR", str(build))
        stale = "#define PCBVERSION 10\n#define MODULE 0\n"
        result = firmware.compile_firmware(
            ino_path=_sketch_copy(tmp_path, versions_h=stale),
            fqbn="arduino:avr:micro",
            module=4,
            pcbversion=12,
        )
        assert result["success"], result.get("error")
        binary = (build / "ethoscope_multimodule.ino.elf").read_bytes()
        assert b"LED Optogenetic Module" in binary
        assert b"N20 Sleep Deprivation Module" not in binary
