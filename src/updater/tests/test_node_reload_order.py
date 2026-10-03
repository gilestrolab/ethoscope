"""
Tests for the order in which a node update restarts its services.

reload_node_daemon() runs inside ethoscope_update_node, so restarting that service
ends the process doing the restarting. It used to come before the backup services,
which were therefore never restarted: after every update the node's backup kept
running the old code (found on 2026-10-03, when a backup fix stayed inactive).
"""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import helpers  # noqa: E402


def restarts(active):
    """Run the reload with *active* backup services; return the services restarted."""
    calls = []
    with (
        mock.patch.object(helpers, "_reload_daemon", side_effect=calls.append),
        mock.patch.object(helpers, "_get_active_backup_services", return_value=active),
        mock.patch.object(helpers.subprocess, "call"),
    ):
        helpers.reload_node_daemon()
    return calls


def test_the_updater_restarts_itself_last():
    calls = restarts(["ethoscope_backup_unified"])
    assert calls[-1] == "ethoscope_update_node"


def test_active_backup_services_are_restarted_before_it():
    calls = restarts(["ethoscope_backup_unified", "ethoscope_backup_mysql"])
    assert calls == [
        "ethoscope_node",
        "ethoscope_backup_unified",
        "ethoscope_backup_mysql",
        "ethoscope_update_node",
    ]


def test_without_backup_services_the_order_is_unchanged():
    assert restarts([]) == ["ethoscope_node", "ethoscope_update_node"]
