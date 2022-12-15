"""
Code from https://github.com/shenxn/rpi-bad-power

A library reading under voltage bit from the official Raspberry Pi Kernel.
Minimal Kernel needed is 4.14+
"""
import logging
import os
from typing import Optional, Text

_LOGGER = logging.getLogger(__name__)

HWMON_NAME = "rpi_volt"

SYSFILE_HWMON_DIR = "/sys/class/hwmon"
SYSFILE_HWMON_FILE = "in0_lcrit_alarm"
SYSFILE_LEGACY = "/sys/devices/platform/soc/soc:firmware/get_throttled"

UNDERVOLTAGE_STICKY_BIT = 1 << 16


def get_rpi_volt_hwmon() -> Optional[Text]:
    """Find rpi_volt hwmon device."""
    try:
        hwmons = os.listdir(SYSFILE_HWMON_DIR)
    except FileNotFoundError:
        return None

    for hwmon in hwmons:
        name_file = os.path.join(SYSFILE_HWMON_DIR, hwmon, "name")
        if os.path.isfile(name_file):
            with open(name_file) as file:
                hwmon_name = file.read().strip()
            if hwmon_name == HWMON_NAME:
                return os.path.join(SYSFILE_HWMON_DIR, hwmon)

    return None


class UnderVoltage:
    """Read under voltage status."""

    def get(self) -> bool:
        """Get under voltage status."""


class UnderVoltageNew(UnderVoltage):
    """Read under voltage status from new entry."""

    def __init__(self, hwmon: Text, debug = False):
        """Initialize the under voltage class."""
        self._hwmon = hwmon

    def get(self) -> bool:
        """Get under voltage status."""
        # Use new hwmon entry
        with open(os.path.join(self._hwmon, SYSFILE_HWMON_FILE)) as file:
            bit = file.read()[:-1]
        if debug:
            _LOGGER.debug("Get under voltage status: %s", bit)
        return bit == "1"


class UnderVoltageLegacy(UnderVoltage):
    """Read under voltage status from legacy entry."""

    def get(self) -> bool:
        """Get under voltage status."""
        # Using legacy get_throttled entry
        with open(SYSFILE_LEGACY) as file:
            throttled = file.read()[:-1]
        _LOGGER.debug("Get throttled value: %s", throttled)
        return (
            int(throttled, base=16) & UNDERVOLTAGE_STICKY_BIT == UNDERVOLTAGE_STICKY_BIT
        )


def new_under_voltage() -> Optional[UnderVoltage]:
    """Create new UnderVoltage object."""
    hwmon = get_rpi_volt_hwmon()
    if hwmon:
        return UnderVoltageNew(hwmon)
    if os.path.isfile(SYSFILE_LEGACY):  # support older kernel
        return UnderVoltageLegacy()
    return None
