#!/usr/bin/env python3
"""
Unit tests for what the device reports about its LED: whether it can dim, and whether it is lit.

The node used to read "LED on" from the schedule file alone. On an SD image without
PWM the daemon can only switch the LED fully on, at 50 % or more, so a schedule
asking for 40 % left the LED dark while the node showed it on, and nobody was told
the SD card needed updating (ETHOSCOPE_354, 2026-10-02).
"""

import os
import sys
from unittest.mock import patch

import pytest

from ethoscope.hardware.interfaces import light_daemon

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../scripts"))


@pytest.fixture
def device_server():
    import device_server

    return device_server


def daemon_says(**status):
    """A LightDaemonClient whose status() returns the given fields."""

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def status(self):
            return status

    return Client


@pytest.mark.parametrize(
    "backend,pwm,level,lit",
    [
        ("pinctrl", False, 40, False),  # 40 % on an on/off LED stays dark
        ("pinctrl", False, 100, True),
        ("pinctrl", False, 50, True),
        ("pigpio", True, 40, True),  # dimmed, but lit
        ("pigpio", True, 0, False),
    ],
)
def test_the_led_state_is_what_the_daemon_drives(
    device_server, backend, pwm, level, lit
):
    client = daemon_says(backend=backend, fade_supported=pwm, led=level)
    with patch.object(light_daemon, "LightDaemonClient", client):
        state = device_server._light_daemon_state()
    assert state == {"pwm": pwm, "backend": backend, "level": level, "led_on": lit}


def test_without_an_answer_the_schedule_values_stand(device_server):
    class Silent:
        def __init__(self, *args, **kwargs):
            pass

        def status(self):
            raise light_daemon.LightDaemonUnavailable("no socket")

    with patch.object(light_daemon, "LightDaemonClient", Silent):
        assert device_server._light_daemon_state() == {}


def test_the_on_off_threshold_is_the_backends_own():
    """The device server reports lit/unlit with the number the backend switches at."""
    assert light_daemon.PinctrlBackend.ON_AT_PCT == 50
    assert light_daemon.PinctrlBackend.supports_fade is False
