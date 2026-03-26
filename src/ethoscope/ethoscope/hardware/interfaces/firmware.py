"""
Firmware management module for Arduino-based ethoscope modules.

Provides functionality to check firmware versions, compile, and upload
firmware to connected Arduino modules using arduino-cli.

Requires arduino-cli to be pre-installed on the system (SD image build-time).
All functions gracefully handle missing arduino-cli by returning appropriate
status dicts rather than raising exceptions.
"""

import logging
import os
import re
import shutil
import subprocess
import time

import serial
from serial.tools import list_ports

from ethoscope.hardware.interfaces.interfaces import connectedUSB

logger = logging.getLogger(__name__)

# FQBN mapping from Arduino model names (as reported by connectedUSB) to
# Fully Qualified Board Names used by arduino-cli
FQBN_MAP = {
    "micro": "arduino:avr:micro",
    "nano": "arduino:avr:nano",
    "uno": "arduino:avr:uno",
    "leonardo": "arduino:avr:leonardo",
}

# Default firmware source path (relative to repo root)
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
)
DEFAULT_INO_PATH = os.path.join(
    _REPO_ROOT,
    "accessories",
    "hardware",
    "ethoscope_multimodule",
    "ethoscope_multimodule.ino",
)

BUILD_DIR = "/tmp/arduino_build"


def is_arduino_cli_available():
    """Check if arduino-cli binary exists on the system.

    Returns:
        bool: True if arduino-cli is available and executable.
    """
    return shutil.which("arduino-cli") is not None


def get_source_firmware_version(ino_path=None):
    """Parse firmware version from the .ino source file.

    Looks for ``const float VERSION = X.Y;`` in the source.

    Args:
        ino_path (str, optional): Path to .ino file. Defaults to repo copy.

    Returns:
        float or None: Parsed version number, or None if not found.
    """
    if ino_path is None:
        ino_path = DEFAULT_INO_PATH

    if not os.path.exists(ino_path):
        logger.warning("Firmware source not found: %s", ino_path)
        return None

    with open(ino_path) as f:
        content = f.read()

    match = re.search(r"const\s+float\s+VERSION\s*=\s*([0-9]+\.?[0-9]*)\s*;", content)
    if match:
        return float(match.group(1))

    logger.warning("Could not parse VERSION from %s", ino_path)
    return None


def parse_running_firmware(version_str):
    """Parse a firmware version string from the Arduino teach response.

    Args:
        version_str (str): Version string like ``"FW-1.3;HW-10"``

    Returns:
        dict: ``{"fw": float, "hw": int}`` or ``{}`` on parse failure.
    """
    if not version_str or not isinstance(version_str, str):
        return {}

    result = {}
    match = re.match(r"FW-([0-9]+\.?[0-9]*);HW-(\d+)", version_str)
    if match:
        result["fw"] = float(match.group(1))
        result["hw"] = int(match.group(2))
    return result


def _get_fqbn(model):
    """Map Arduino model name to FQBN.

    Args:
        model (str): Model name from connectedUSB (e.g. "micro", "nano").

    Returns:
        str or None: FQBN string or None if unknown model.
    """
    return FQBN_MAP.get(model.lower() if model else "")


def _find_serial_port():
    """Find the first available serial port for an Arduino.

    Returns:
        str or None: Port path (e.g. "/dev/ttyACM0") or None.
    """
    for port_info in list_ports.comports():
        basename = os.path.basename(port_info.device)
        if basename.startswith("ttyUSB") or basename.startswith("ttyACM"):
            return port_info.device
    return None


def _interrogate_arduino(port, timeout=5):
    """Send teach command to Arduino and parse response.

    Args:
        port (str): Serial port path.
        timeout (int): Serial timeout in seconds.

    Returns:
        dict: Parsed teach response or empty dict on failure.
    """
    try:
        ser = serial.Serial(port, 115200, timeout=timeout)
        time.sleep(2)  # Wait for Arduino reset after serial connection
        ser.write(b"T\r\n")
        time.sleep(0.5)
        response = ser.read_all()
        ser.close()
        if response:
            return eval(response)
    except Exception as e:
        logger.error("Failed to interrogate Arduino on %s: %s", port, e)
    return {}


def get_firmware_status(ino_path=None):
    """Read-only check: compare source firmware with running Arduino firmware.

    Returns a status dict suitable for the API. If arduino-cli is not
    available, returns ``{"arduino_cli_available": false}`` so the UI can
    hide the firmware section entirely.

    Args:
        ino_path (str, optional): Path to .ino source file.

    Returns:
        dict: Firmware status information.
    """
    if not is_arduino_cli_available():
        return {"arduino_cli_available": False}

    result = {
        "arduino_cli_available": True,
        "update_available": False,
        "source_version": None,
        "running_version": None,
        "running_fw": None,
        "running_hw": None,
        "module_type": None,
        "pcb_version": None,
        "model": None,
        "port": None,
    }

    # Check source version
    source_ver = get_source_firmware_version(ino_path)
    result["source_version"] = source_ver

    # Check for connected Arduino
    _, found = connectedUSB()
    if not found:
        result["error"] = "No Arduino connected"
        return result

    # Get model from first found Arduino
    for _dev_key, dev_info in found.items():
        if dev_info.get("family") == "arduino":
            result["model"] = dev_info.get("model")
            break

    # Find serial port and interrogate
    port = _find_serial_port()
    if not port:
        result["error"] = "No serial port found"
        return result
    result["port"] = port

    teach_info = _interrogate_arduino(port)
    if not teach_info:
        result["error"] = "Could not interrogate Arduino"
        return result

    # Parse running firmware version
    version_str = teach_info.get("version", "")
    parsed = parse_running_firmware(version_str)
    result["running_version"] = version_str
    result["running_fw"] = parsed.get("fw")
    result["running_hw"] = parsed.get("hw")
    result["module_type"] = teach_info.get("module", {}).get("type")
    result["pcb_version"] = parsed.get("hw")

    # Compare versions
    if source_ver is not None and parsed.get("fw") is not None:
        result["update_available"] = source_ver > parsed["fw"]

    return result


def compile_firmware(ino_path=None, fqbn=None, module=None, pcbversion=None):
    """Compile Arduino firmware using arduino-cli.

    Args:
        ino_path (str, optional): Path to .ino source file.
        fqbn (str, optional): Fully Qualified Board Name.
        module (int, optional): MODULE define value (0-4).
        pcbversion (int, optional): PCBVERSION define value (10 or 11).

    Returns:
        dict: ``{"success": bool, "output": str, "error": str}``
    """
    if not is_arduino_cli_available():
        return {"success": False, "error": "arduino-cli not available"}

    if ino_path is None:
        ino_path = DEFAULT_INO_PATH

    if not os.path.exists(ino_path):
        return {"success": False, "error": f"Firmware source not found: {ino_path}"}

    if fqbn is None:
        return {"success": False, "error": "No FQBN specified"}

    # Build extra flags for MODULE and PCBVERSION defines
    extra_flags = []
    if module is not None:
        extra_flags.append(f"-DMODULE={module}")
    if pcbversion is not None:
        extra_flags.append(f"-DPCBVERSION={pcbversion}")

    # Clean and create build directory
    os.makedirs(BUILD_DIR, exist_ok=True)

    cmd = [
        "arduino-cli",
        "compile",
        "--fqbn",
        fqbn,
        "--build-path",
        BUILD_DIR,
    ]

    if extra_flags:
        cmd.extend(["--build-property", f"build.extra_flags={' '.join(extra_flags)}"])

    cmd.append(ino_path)

    logger.info("Compiling firmware: %s", " ".join(cmd))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            return {"success": True, "output": proc.stdout}
        else:
            return {"success": False, "error": proc.stderr, "output": proc.stdout}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Compilation timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def upload_firmware(ino_path=None, fqbn=None, port=None):
    """Upload compiled firmware to Arduino using arduino-cli.

    Args:
        ino_path (str, optional): Path to .ino source file.
        fqbn (str, optional): Fully Qualified Board Name.
        port (str, optional): Serial port path.

    Returns:
        dict: ``{"success": bool, "output": str, "error": str}``
    """
    if not is_arduino_cli_available():
        return {"success": False, "error": "arduino-cli not available"}

    if ino_path is None:
        ino_path = DEFAULT_INO_PATH
    if port is None:
        port = _find_serial_port()
        if not port:
            return {"success": False, "error": "No serial port found"}
    if fqbn is None:
        return {"success": False, "error": "No FQBN specified"}

    cmd = [
        "arduino-cli",
        "upload",
        "--fqbn",
        fqbn,
        "--port",
        port,
        "--input-dir",
        BUILD_DIR,
    ]

    logger.info("Uploading firmware to %s: %s", port, " ".join(cmd))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            return {"success": True, "output": proc.stdout}
        else:
            return {"success": False, "error": proc.stderr, "output": proc.stdout}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Upload timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_firmware(ino_path=None):
    """Full firmware update orchestration: detect, compare, compile, upload, verify.

    Refuses to run if tracking is active (serial port in use by stimulator).

    Args:
        ino_path (str, optional): Path to .ino source file.

    Returns:
        dict: Update result with status and details.
    """
    if ino_path is None:
        ino_path = DEFAULT_INO_PATH

    # Step 1: Get current status
    status = get_firmware_status(ino_path)

    if not status.get("arduino_cli_available"):
        return {"status": "failed", "error": "arduino-cli not available on this device"}

    if status.get("error"):
        return {"status": "failed", "error": status["error"]}

    if not status.get("update_available"):
        return {
            "status": "up_to_date",
            "source_version": status["source_version"],
            "running_fw": status["running_fw"],
        }

    # Step 2: Determine compile parameters from running Arduino
    model = status.get("model")
    fqbn = _get_fqbn(model) if model else None
    if not fqbn:
        return {"status": "failed", "error": f"Unknown Arduino model: {model}"}

    module_type = status.get("module_type")
    pcb_version = status.get("pcb_version")
    port = status.get("port")

    if module_type is None:
        return {
            "status": "failed",
            "error": "Could not determine module type from running firmware",
        }

    # Step 3: Compile
    compile_result = compile_firmware(ino_path, fqbn, module_type, pcb_version)
    if not compile_result["success"]:
        return {
            "status": "failed",
            "step": "compile",
            "error": compile_result.get("error", "Unknown compile error"),
        }

    # Step 4: Upload
    upload_result = upload_firmware(ino_path, fqbn, port)
    if not upload_result["success"]:
        return {
            "status": "failed",
            "step": "upload",
            "error": upload_result.get("error", "Unknown upload error"),
        }

    # Step 5: Wait for Arduino reboot and re-verify
    logger.info("Waiting for Arduino to reboot after upload...")
    time.sleep(5)

    # Re-scan port (may change for USB-bootloader boards like Micro/Leonardo)
    new_port = _find_serial_port()
    if not new_port:
        return {
            "status": "updated",
            "warning": "Upload succeeded but could not verify — no serial port found after reboot",
            "source_version": status["source_version"],
        }

    verify_info = _interrogate_arduino(new_port)
    if verify_info:
        new_parsed = parse_running_firmware(verify_info.get("version", ""))
        new_fw = new_parsed.get("fw")
        if new_fw == status["source_version"]:
            logger.info("Firmware update verified: v%s", new_fw)
        else:
            logger.warning(
                "Firmware version mismatch after update: expected %s, got %s",
                status["source_version"],
                new_fw,
            )

        # Clean up build directory
        _cleanup_build()

        return {
            "status": "updated",
            "previous_fw": status["running_fw"],
            "new_fw": new_fw,
            "source_version": status["source_version"],
        }

    _cleanup_build()
    return {
        "status": "updated",
        "warning": "Upload succeeded but could not verify — Arduino did not respond",
        "source_version": status["source_version"],
    }


def _cleanup_build():
    """Remove temporary build directory."""
    try:
        if os.path.exists(BUILD_DIR):
            shutil.rmtree(BUILD_DIR)
    except Exception as e:
        logger.warning("Failed to clean up build directory: %s", e)
