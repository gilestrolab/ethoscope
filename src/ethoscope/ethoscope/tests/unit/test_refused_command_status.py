#!/usr/bin/env python3
"""
Unit tests for what the device reports when the listener refuses a command.

The start / start_record / stream handlers used to answer a refusal with a
hardcoded ``{"status": "stopped"}``. That was near enough while the only
refusals were genuine start failures, but the listener now declines a second
start *because an experiment is already under way* - the opposite of stopped.
Left as it was, the node would have drawn a live experiment as an idle device
and offered to start it again.
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../scripts"))

BUSY = (
    "ERROR: this ethoscope is already busy (running). Stop the current "
    "activity before starting a new one."
)


@pytest.fixture
def device_server():
    import device_server

    return device_server


def test_the_real_status_is_reported_not_stopped(device_server):
    """Regression: a busy device must not be described as stopped."""
    live = {"status": "running", "id": "abc", "monitor_info": {"fps": 5.0}}

    with patch.object(device_server, "info", return_value=live):
        response = device_server._refused_command("abc", "Start", BUSY)

    assert response["status"] == "running"
    assert response["error"] == BUSY


def test_the_refusal_reaches_the_caller(device_server):
    """The reason is the whole point: the UI has to be able to show it."""
    with patch.object(device_server, "info", return_value={"status": "stopped"}):
        response = device_server._refused_command("abc", "Start", BUSY)

    assert "already busy" in response["error"]


def test_a_stale_error_is_replaced_by_the_refusal(device_server):
    """The command that just failed outranks whatever the last run left behind."""
    live = {"status": "running", "error": "an old error from the previous run"}

    with patch.object(device_server, "info", return_value=live):
        response = device_server._refused_command("abc", "Start", BUSY)

    assert response["error"] == BUSY
