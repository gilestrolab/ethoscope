"""
Unit tests for the GPIO button listener (hardware/interfaces/GPIO.py).

The listener runs for the whole life of a device, so its poll loop must pause
between reads: without one it pinned a core at 100% on every ethoscope. RPi.GPIO
only exists on a Pi, so a fake module stands in for it here.
"""

import importlib
import sys
import time
import types
from unittest.mock import patch

import pytest


class _FakeGPIO(types.ModuleType):
    """Minimal RPi.GPIO: one pin per channel, high (released) unless set low."""

    BOARD = IN = OUT = PUD_UP = 0

    def __init__(self):
        super().__init__("RPi.GPIO")
        self.level = {}
        self.reads = 0

    def setmode(self, mode):
        pass

    def setup(self, channel, direction, pull_up_down=None):
        self.level.setdefault(channel, 1)

    def input(self, channel):
        self.reads += 1
        return self.level[channel]

    def output(self, channel, state):
        pass

    def cleanup(self):
        pass


@pytest.fixture
def gpio():
    """Import GPIO.py against a fake RPi.GPIO; yield (module, fake)."""
    fake = _FakeGPIO()
    rpi = types.ModuleType("RPi")
    rpi.GPIO = fake
    with patch.dict(sys.modules, {"RPi": rpi, "RPi.GPIO": fake}):
        sys.modules.pop("ethoscope.hardware.interfaces.GPIO", None)
        module = importlib.import_module("ethoscope.hardware.interfaces.GPIO")
        yield module, fake
    sys.modules.pop("ethoscope.hardware.interfaces.GPIO", None)


def _button(module, commands, channel=33):
    """Start a Button whose commands are recorded instead of executed."""
    fired = []
    button = module.Button(channel, commands)
    button.action = fired.append
    return button, fired


def test_poll_loop_pauses_between_reads(gpio):
    """An idle button is read about once per POLL_INTERVAL, not in a busy loop."""
    module, fake = gpio
    button, _ = _button(module, {"0": "short"})
    try:
        time.sleep(0.3)
    finally:
        button.stop()
        button.join(timeout=1)

    expected = 0.3 / module.POLL_INTERVAL
    assert fake.reads <= 2 * expected


def test_press_runs_the_command_for_its_duration(gpio):
    """A short press runs the 0-s command, a long one the longest threshold met."""
    module, fake = gpio
    button, fired = _button(module, {"0": "short", "1": "long"})
    try:
        fake.level[33] = 0
        time.sleep(0.1)
        fake.level[33] = 1
        time.sleep(0.1)
        fake.level[33] = 0
        time.sleep(1.1)
        fake.level[33] = 1
        time.sleep(0.1)
    finally:
        button.stop()
        button.join(timeout=1)

    assert fired == ["short", "long"]


def test_stop_ends_the_thread(gpio):
    """stop() is honoured within one poll, so the listener can be reloaded."""
    module, _ = gpio
    button, _ = _button(module, {"0": ""})
    button.stop()
    button.join(timeout=1)
    assert not button.is_alive()


def test_button_threads_are_daemons(gpio):
    """The attribute is daemon; the old 'deamon' spelling did nothing."""
    module, _ = gpio
    button, _ = _button(module, {"0": ""})
    try:
        assert button.daemon is True
        assert not hasattr(button, "deamon")
    finally:
        button.stop()
        button.join(timeout=1)
