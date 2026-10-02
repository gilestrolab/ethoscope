"""
Tests for ``/device/update/<id>?then=reboot``: update the software, then reboot.

A fresh card renamed with "software update" ticked must reboot renamed and
updated. The plain update restarts the device's services when the commit
changes, which would bring the new identity up before the reboot the rename
needs (and the node's reboot request would then miss). With then=reboot the
reboot replaces that restart and follows the attempt, whatever its outcome.
"""

import os
import sys
from unittest.mock import Mock

import bottle
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import update_server  # noqa: E402

DEVICE = "000abc"


@pytest.fixture
def server(monkeypatch):
    calls = {"reboot": 0, "restart": 0}
    monkeypatch.setattr(update_server, "device_id", DEVICE)
    monkeypatch.setattr(update_server, "is_node", False)
    monkeypatch.setattr(update_server, "get_commit_version", str)
    monkeypatch.setattr(
        update_server,
        "_schedule_reboot",
        lambda *a, **k: calls.__setitem__("reboot", calls["reboot"] + 1),
    )
    monkeypatch.setattr(
        update_server,
        "_schedule_restart",
        lambda *a, **k: calls.__setitem__("restart", calls["restart"] + 1),
    )
    updater = Mock()
    monkeypatch.setattr(update_server, "ethoscope_updater", updater)
    return updater, calls


def call(query=""):
    bottle.request.bind(
        {"QUERY_STRING": query, "REQUEST_METHOD": "GET", "PATH_INFO": "/"}
    )
    return update_server.device("update", DEVICE)


def test_then_reboot_reboots_instead_of_restarting(server):
    updater, calls = server
    updater.get_local_and_origin_commits.side_effect = [("old", "new"), ("new", "new")]
    result = call("then=reboot")
    assert calls == {"reboot": 1, "restart": 0}
    assert result["then"] == "reboot" and result["new_commit"] == "new"


def test_then_reboot_reboots_even_when_the_update_fails(server):
    updater, calls = server
    updater.get_local_and_origin_commits.return_value = ("old", "new")
    updater.update_active_branch.side_effect = RuntimeError("node.local unreachable")
    result = call("then=reboot")
    assert calls == {"reboot": 1, "restart": 0}
    assert "error" in result


def test_a_plain_update_restarts_only_when_the_commit_changed(server):
    updater, calls = server
    updater.get_local_and_origin_commits.side_effect = [("old", "new"), ("new", "new")]
    call()
    assert calls == {"reboot": 0, "restart": 1}
    updater.get_local_and_origin_commits.side_effect = [
        ("same", "same"),
        ("same", "same"),
    ]
    call()
    assert calls == {"reboot": 0, "restart": 1}


def test_the_node_never_reboots_on_request(server, monkeypatch):
    updater, calls = server
    monkeypatch.setattr(update_server, "is_node", True)
    updater.get_local_and_origin_commits.side_effect = [("old", "new"), ("new", "new")]
    call("then=reboot")
    assert calls == {"reboot": 0, "restart": 1}
