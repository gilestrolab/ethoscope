"""
Unit tests for devices the node asked to go away, and for entries it should forget.

A reboot, restart or shutdown sent from the node is an expected disappearance:
the device is shown as rebooting or shut down, not as an accident. An entry
that will not return is forgotten, so the next card is identified without
restarting the node: a renamed device, which comes back under a new machine
id, or a fresh ETHOSCOPE_000 card, whose id every fresh card shares
(2026-10-02, SD card replacements).
"""

import json
import time
from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest

from ethoscope_node.scanner.base_scanner import DeviceStatus, ScanException
from ethoscope_node.scanner.ethoscope_scanner import Ethoscope, EthoscopeScanner


@pytest.fixture
def db():
    with patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB") as cls:
        cls.return_value = Mock()
        yield cls.return_value


@pytest.fixture
def scanner(db):
    config = Mock()
    config.get_custom.return_value = {}
    s = EthoscopeScanner(device_refresh_period=1, config=config)
    s._is_running = True
    return s


def make_device(scanner, name="ETHOSCOPE_123", device_id="123abc", ip="192.168.1.10"):
    """A stopped Ethoscope entry registered with ``scanner`` (thread not started)."""
    with patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration"):
        device = Ethoscope(ip)
    device._config = Mock()
    device._config.get_custom.return_value = {"graceful_shutdown_grace_minutes": 5}
    device._id = device_id
    device._info.update({"name": name, "id": device_id, "status": "stopped"})
    device._device_status = DeviceStatus("stopped")
    device._registry = scanner
    scanner.devices.append(device)
    return device


@contextmanager
def quiet(device):
    """Skip what a real device coming back triggers: run reconciliation, SSH checks."""
    with (
        patch.object(device, "_reconcile_run_state", create=True),
        patch.object(device, "_handle_device_coming_online"),
        patch.object(device, "check_ssh_key_installed", return_value=True),
        patch.object(device, "setup_ssh_authentication", return_value=True),
        patch.object(device, "_check_storage_warnings", create=True),
        patch.object(device, "_make_backup_path"),
        patch.object(device, "databases_info", return_value={}),
    ):
        yield


def poll(device, answers, status="stopped"):
    """Run one ``_update_info`` with the device answering or not."""

    def fetch():
        if answers:
            device._info["status"] = status
        return answers

    with patch.object(device, "_fetch_device_info", side_effect=fetch), quiet(device):
        try:
            device._update_info()
        except ScanException:
            pass


def ask(device, instruction):
    """Send a power instruction: the device answers the status check, then goes."""
    answers = iter([True])

    def fetch():
        alive = next(answers, False)
        if alive:
            device._info["status"] = "stopped"
        return alive

    with (
        patch.object(device, "_get_json", side_effect=ScanException("gone")),
        patch.object(device, "_fetch_device_info", side_effect=fetch),
        quiet(device),
    ):
        device.send_instruction(instruction)


class TestReboot:
    def test_a_reboot_is_shown_as_rebooting_not_unreachable(self, scanner):
        device = make_device(scanner)
        ask(device, "reboot")
        assert device.get_device_status().status_name == "rebooting"
        poll(device, answers=False)
        assert device.get_device_status().status_name == "rebooting"
        assert device in scanner.devices

    def test_the_device_coming_back_ends_the_departure(self, scanner):
        device = make_device(scanner)
        ask(device, "reboot")
        poll(device, answers=True)
        assert device._departure is None
        assert device.get_device_status().status_name == "stopped"

    def test_a_reboot_that_never_ends_becomes_unreachable(self, scanner):
        device = make_device(scanner)
        ask(device, "reboot")
        device._departure["since"] -= 6 * 60  # past the 5-min grace
        poll(device, answers=False)
        assert device._departure is None
        assert device.get_device_status().status_name == "unreached"

    def test_a_request_the_device_ignored_is_dropped(self, scanner):
        device = make_device(scanner)
        with (
            patch.object(device, "_get_json", return_value={}),
            patch.object(device, "_fetch_device_info", return_value=True),
            quiet(device),
        ):
            device.send_instruction("reboot")
        device._departure["since"] -= Ethoscope._DEPARTURE_NOT_TAKEN_S + 1
        poll(device, answers=True)
        assert device._departure is None


class TestShutdown:
    def test_a_shutdown_is_shown_and_no_longer_polled(self, scanner):
        device = make_device(scanner)
        ask(device, "poweroff")
        assert device.get_device_status().status_name == "shutdown"
        assert device._polling_suspended
        assert device in scanner.devices

    def test_announcing_itself_brings_it_back(self, scanner):
        device = make_device(scanner)
        ask(device, "poweroff")
        device.on_announced()
        assert not device._polling_suspended and device._departure is None


class TestForgetting:
    def test_a_renamed_device_is_forgotten_when_it_reboots(self, scanner, db):
        device = make_device(scanner, name="ETHOSCOPE_123")
        with (
            patch.object(device, "_get_json_once", return_value={"haschanged": True}),
            patch.object(device, "_update_info"),
        ):
            device.send_settings({"etho_number": 124})
        assert device._identity_changes
        ask(device, "reboot")
        assert device not in scanner.devices
        assert not device._is_online
        db.updateEthoscopes.assert_any_call(
            ethoscope_id="123abc", active=0, status="offline"
        )

    def test_a_fresh_card_is_forgotten_when_it_reboots(self, scanner, db):
        device = make_device(scanner, name="ETHOSCOPE_000", device_id="b14bdd6b")
        ask(device, "reboot")
        assert device not in scanner.devices
        retired = [
            c for c in db.updateEthoscopes.call_args_list if c.kwargs.get("active") == 0
        ]
        assert retired == []  # ETHOSCOPE_000 has no row to retire

    def test_a_fresh_card_that_goes_offline_is_forgotten(self, scanner):
        device = make_device(scanner, name="ETHOSCOPE_000", device_id="b14bdd6b")
        for _ in range(device._max_consecutive_errors + 2):
            poll(device, answers=False)
            device._consecutive_errors += 1  # what run() does after each failure
        assert device not in scanner.devices

    def test_a_named_device_that_goes_offline_is_kept(self, scanner):
        device = make_device(scanner, name="ETHOSCOPE_123")
        for _ in range(device._max_consecutive_errors + 2):
            poll(device, answers=False)
            device._consecutive_errors += 1
        assert device.get_device_status().status_name == "offline"
        assert device in scanner.devices

    def test_a_stale_copy_of_a_live_entry_is_forgotten(self, scanner):
        stale = make_device(
            scanner, name="ETHOSCOPE_000", device_id="b14bdd6b", ip="192.168.1.74"
        )
        live = make_device(
            scanner, name="ETHOSCOPE_000", device_id="b14bdd6b", ip="192.168.1.81"
        )
        stale._last_successful_contact = time.time() - 3600
        live._last_successful_contact = time.time()
        assert scanner.get_device("b14bdd6b") is live  # actions go where it answers
        poll(stale, answers=False)
        assert stale not in scanner.devices and live in scanner.devices


class TestRenameRequest:
    @pytest.mark.parametrize(
        "number,answer,renames",
        [
            (124, {"haschanged": True}, True),
            (123, {"haschanged": True}, False),
            (124, {"haschanged": False}, False),
        ],
    )
    def test_only_an_accepted_new_number_marks_a_rename(
        self, scanner, number, answer, renames
    ):
        device = make_device(scanner, name="ETHOSCOPE_123")
        with (
            patch.object(device, "_get_json_once", return_value=answer) as once,
            patch.object(device, "_get_json") as retried,
            patch.object(device, "_update_info"),
        ):
            device.send_settings({"etho_number": number})
        assert device._identity_changes is renames
        retried.assert_not_called()
        assert once.call_args.kwargs["timeout"] == 30
        assert json.loads(once.call_args.kwargs["post_data"]) == {"etho_number": number}

    @pytest.mark.parametrize("number,renames", [(124, True), (123, False)])
    def test_the_dialogs_nested_payload_is_read(self, scanner, number, renames):
        """The settings dialog sends {"machine_options": {"arguments": {...}}}.

        Only the flat form was read before, so a rename from the UI never marked
        the old entry for retirement.
        """
        device = make_device(scanner, name="ETHOSCOPE_123")
        payload = {
            "machine_options": {
                "name": "Ethoscope Options",
                "arguments": {"etho_number": number, "node_ip": "192.168.1.2"},
            }
        }
        with (
            patch.object(device, "_get_json_once", return_value={"haschanged": True}),
            patch.object(device, "_update_info"),
        ):
            device.send_settings(payload)
        assert device._identity_changes is renames

    def test_a_power_request_does_not_fail_because_the_device_left(self, scanner):
        device = make_device(scanner)
        ask(device, "poweroff")  # would raise if the vanished device were an error
        assert device._departure["away"]
