#!/usr/bin/env python3
"""
Unit tests for the "software update" settings option: update, then reboot.

A fresh card renamed for the first time should come back renamed and up to
date, so the option is on by default for ETHOSCOPE_000, like expand_rootfs.
The device runs the sequence itself (update through its local update server,
which reboots afterwards), because a node-driven update would restart the
services and bring the new identity up before the reboot the rename needs.
"""

import io
import json
import os
import sys
import urllib.error
from unittest.mock import patch

import bottle
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../scripts"))

MACHINE_ID = "0" * 32


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


def _option(device_server, number):
    with (
        patch.object(device_server, "_MACHINE_ID", MACHINE_ID, create=True),
        patch.object(
            device_server, "get_machine_info", return_value=_machine_info(number)
        ),
        patch.object(
            device_server, "_inject_roi_template_options", side_effect=lambda o: o
        ),
    ):
        options = device_server.user_options(MACHINE_ID)
    arguments = options["update_machine"]["machine_options"][0]["arguments"]
    (argument,) = [a for a in arguments if a["name"] == "software_update"]
    return argument


class TestTheOption:
    def test_a_fresh_card_offers_the_update_ticked(self, device_server):
        assert _option(device_server, 0)["default"] is True

    def test_a_named_device_leaves_it_unticked(self, device_server):
        assert _option(device_server, 107)["default"] is False

    def test_it_is_an_action_that_needs_the_reboot(self, device_server):
        option = _option(device_server, 0)
        assert option["is_action"] is True and option["requires_reboot"] is True


class TestTheRequest:
    def _post(self, device_server, arguments):
        body = json.dumps({"machine_options": {"arguments": arguments}}).encode()
        bottle.request.bind(
            {
                "REQUEST_METHOD": "POST",
                "PATH_INFO": f"/update/{MACHINE_ID}",
                "CONTENT_TYPE": "application/json",
                "CONTENT_LENGTH": str(len(body)),
                "wsgi.input": io.BytesIO(body),
                "REMOTE_ADDR": "192.168.1.2",
            }
        )
        with (
            patch.object(device_server, "_MACHINE_ID", MACHINE_ID, create=True),
            patch.object(
                device_server, "get_machine_info", return_value=_machine_info(0)
            ),
            patch.object(device_server.threading, "Thread") as thread,
        ):
            answer = device_server.update_machine_info(MACHINE_ID)
        return answer, thread

    def test_ticked_it_starts_the_sequence_and_says_the_device_reboots(
        self, device_server
    ):
        answer, thread = self._post(device_server, {"software_update": True})
        assert answer == {"haschanged": True, "self_reboot": "after_update"}
        assert thread.call_args.kwargs["target"] is device_server._update_then_reboot
        assert thread.call_args.kwargs["args"] == ("192.168.1.2",)
        thread.return_value.start.assert_called_once()

    def test_unticked_nothing_starts(self, device_server):
        answer, thread = self._post(device_server, {"software_update": False})
        assert "self_reboot" not in answer
        thread.assert_not_called()


class TestTheSequence:
    def run(self, device_server, answers):
        """Run _update_then_reboot with each URL answered from ``answers``."""
        calls = []

        def http(url, timeout):
            calls.append(url)
            for fragment, answer in answers.items():
                if fragment in url:
                    if isinstance(answer, Exception):
                        raise answer
                    return answer
            raise AssertionError(url)

        with (
            patch.object(device_server, "_http_json", side_effect=http),
            patch.object(device_server.subprocess, "call") as call,
        ):
            device_server._update_then_reboot("192.168.1.2")
        return calls, call

    def test_refresh_then_update_through_the_local_server(self, device_server):
        calls, reboot = self.run(
            device_server,
            {
                "bare/update": {"dev": True},
                ":8888/id": {"id": "000abc"},
                "device/update": {"old_commit": "a", "new_commit": "b"},
            },
        )
        assert calls == [
            "http://192.168.1.2:8888/bare/update",
            "http://127.0.0.1:8888/id",
            "http://127.0.0.1:8888/device/update/000abc?then=reboot",
        ]
        reboot.assert_not_called()  # the update server reboots

    def test_a_failed_mirror_refresh_does_not_stop_the_update(self, device_server):
        calls, reboot = self.run(
            device_server,
            {
                "bare/update": OSError("no route"),
                ":8888/id": {"id": "000abc"},
                "device/update": {"old_commit": "a", "new_commit": "a"},
            },
        )
        assert calls[-1].endswith("?then=reboot")
        reboot.assert_not_called()

    @pytest.mark.parametrize(
        "failure",
        [
            urllib.error.HTTPError("u", 500, "WrongMachineID", None, None),
            urllib.error.URLError(ConnectionRefusedError()),
        ],
    )
    def test_when_the_update_never_starts_the_device_reboots_itself(
        self, device_server, failure
    ):
        _, reboot = self.run(
            device_server,
            {"bare/update": {}, ":8888/id": {"id": "000abc"}, "device/update": failure},
        )
        reboot.assert_called_once_with("reboot")

    def test_without_an_update_server_the_device_reboots_itself(self, device_server):
        _, reboot = self.run(
            device_server, {"bare/update": {}, ":8888/id": OSError("refused")}
        )
        reboot.assert_called_once_with("reboot")

    def test_a_slow_update_is_left_to_reboot_when_it_ends(self, device_server):
        _, reboot = self.run(
            device_server,
            {
                "bare/update": {},
                ":8888/id": {"id": "000abc"},
                "device/update": urllib.error.URLError(TimeoutError()),
            },
        )
        reboot.assert_not_called()
