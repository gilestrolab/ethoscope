#!/usr/bin/env python3
"""
Unit tests for the default state of the "expand root filesystem" toggle.

A device straight off the SD image is called ETHOSCOPE_000 and its root
partition still has the size the image had, so the first thing anyone does to
it - give it a number - is also the moment it has to be expanded. The toggle
used to default to off, so the expansion was silently skipped and the card was
found to be full weeks later. It now defaults to on for an unnamed device, and
back to off once the device has a number, so a later settings change never
re-runs it unasked.
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../scripts"))


@pytest.fixture
def device_server():
    import device_server

    return device_server


def _machine_info(number):
    """A machine_info stub carrying only the keys the option list reads."""
    return {
        "machine-number": number,
        "isExperimental": False,
        "remoteLogging": False,
        "useSTATIC": False,
        "node_ip": "192.168.1.2",
        "WIFI_SSID": "ETHOSCOPE_WIFI",
        "WIFI_PASSWORD": "ETHOSCOPE_1234",
        "has_light_hardware": False,
    }


def _expand_rootfs_default(device_server, number):
    # _MACHINE_ID is only assigned when the server is actually started, so the
    # id the handler checks against has to be planted here.
    with (
        patch.object(device_server, "_MACHINE_ID", "0" * 32, create=True),
        patch.object(
            device_server, "get_machine_info", return_value=_machine_info(number)
        ),
        # Reads the ROI template directory under /ethoscope_data, which does not
        # exist off a device and has nothing to do with the machine options.
        patch.object(
            device_server, "_inject_roi_template_options", side_effect=lambda o: o
        ),
    ):
        options = device_server.user_options("0" * 32)

    arguments = options["update_machine"]["machine_options"][0]["arguments"]
    (argument,) = [a for a in arguments if a["name"] == "expand_rootfs"]
    return argument["default"]


def test_an_unnamed_device_offers_the_expansion_ticked(device_server):
    """ETHOSCOPE_000 has never been expanded: the toggle starts on."""
    assert _expand_rootfs_default(device_server, 0) is True


def test_a_named_device_leaves_the_expansion_alone(device_server):
    """A device with a number is opt-in, so routine settings edits cannot re-run it."""
    assert _expand_rootfs_default(device_server, 107) is False
