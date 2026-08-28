"""
Tests for the command line platform updater in ``accessories/``.

The one rule that must never bend is that a device mid-experiment is left alone:
the web interface refuses to select it, and the CLI has to refuse just as firmly,
including when the operator reaches for --force. The rest of these tests pin the
state classification and the response parsing the summary is built from.
"""

import argparse
import json
import os
import sys

import pytest

# The accessories directory is a collection of standalone scripts rather than an
# installable package, so make it importable directly -- the same trick the other
# updater tests use for the updater package itself.
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "accessories")
    ),
)

import update_platform  # noqa: E402
import update_platform_api as api  # noqa: E402


def device(**kwargs):
    """Build a device map entry, defaulting to an idle, up to date ethoscope."""
    entry = {
        "id": "abc123",
        "name": "ETHOSCOPE_001",
        "ip": "http://192.168.1.10",
        "status": "stopped",
        "active_branch": "dev",
        "up_to_date": True,
        "local_commit": {"id": "a" * 40},
        "origin_commit": {"id": "a" * 40},
        "version": {"id": "a" * 40},
    }
    entry.update(kwargs)
    return entry


def options(**kwargs):
    """Build the subset of parsed arguments that build_plan reads."""
    defaults = {
        "only": None,
        "skip": None,
        "force": False,
        "devices_only": False,
        "restart_node": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ------------------------------------------------------------------ state classification


def test_device_state_current():
    """Disk and running process both on the origin commit."""
    assert api.device_state(device()) == "current"


def test_device_state_outdated():
    """The node says the checkout is behind origin."""
    assert api.device_state(device(up_to_date=False)) == "outdated"


def test_device_state_stale_needs_restart():
    """Pulled but never restarted: on disk current, still running the old code."""
    entry = device(local_commit={"id": "b" * 40}, version={"id": "a" * 40})
    assert api.device_state(entry) == "stale"


def test_device_state_unknown_when_check_update_did_not_answer():
    """A device whose updater never replied must not be read as up to date."""
    entry = device()
    del entry["up_to_date"]
    assert api.device_state(entry) == "unknown"


# -------------------------------------------------------------------------- eligibility


@pytest.mark.parametrize("status", api.BUSY_STATES)
def test_busy_devices_are_never_eligible(status):
    """Tracking, recording and streaming devices are off limits."""
    ok, reason = api.eligibility(device(status=status, up_to_date=False))
    assert ok is False
    assert reason == f"busy: {status}"


@pytest.mark.parametrize("status", api.BUSY_STATES)
def test_force_does_not_override_busy(status):
    """--force widens what counts as needing an update, never what may be disturbed."""
    ok, _ = api.eligibility(device(status=status, up_to_date=False), force=True)
    assert ok is False


def test_unreachable_device_is_not_eligible():
    """An unreachable device cannot be updated, so it is reported rather than tried."""
    ok, reason = api.eligibility(device(status="Unreachable", up_to_date=None))
    assert ok is False
    assert "Unreachable" in reason


def test_outdated_idle_device_is_eligible():
    """The ordinary case: idle and behind origin."""
    ok, reason = api.eligibility(device(up_to_date=False))
    assert (ok, reason) == (True, "outdated")


def test_current_device_only_eligible_with_force():
    """An up to date device is skipped unless the operator insists."""
    assert api.eligibility(device())[0] is False
    assert api.eligibility(device(), force=True)[0] is True


def test_software_broken_device_is_eligible():
    """A broken device is exactly the one an update is meant to repair."""
    ok, _ = api.eligibility(device(status="Software broken", up_to_date=False))
    assert ok is True


# ------------------------------------------------------------------------------ filters


def test_matches_on_name_and_id_globs():
    """--only/--skip accept globs against either the friendly name or the id."""
    entry = device(name="ETHOSCOPE_358", id="deadbeef")
    assert api.matches(entry, ["ethoscope_35*"])
    assert api.matches(entry, ["dead*"])
    assert not api.matches(entry, ["ETHOSCOPE_36*"])


def test_build_plan_splits_targets_from_skipped():
    """Busy devices land in the skipped list, idle outdated ones in the targets."""
    devices = [
        device(id="idle", name="A", up_to_date=False),
        device(id="busy", name="B", status="running", up_to_date=False),
        device(id="fine", name="C"),
    ]
    node = device(id="node", name="node", status="NA")

    targets, skipped, node_target = build(devices, node, options())

    assert [d["id"] for d, _ in targets] == ["idle"]
    assert {d["id"]: r for d, r in skipped} == {
        "busy": "busy: running",
        "fine": "already up to date",
        "node": "already up to date",
    }
    assert node_target is None


def test_build_plan_skip_wins_over_only():
    """A device matched by both --only and --skip is left alone."""
    devices = [
        device(id="one", name="ETHOSCOPE_350", up_to_date=False),
        device(id="two", name="ETHOSCOPE_358", up_to_date=False),
    ]
    node = device(id="node", name="node", status="NA")

    targets, skipped, _ = build(
        devices, node, options(only=["ETHOSCOPE_35*"], skip=["*_358"])
    )

    assert [d["id"] for d, _ in targets] == ["one"]
    assert ("two", "excluded by --skip") in [(d["id"], r) for d, r in skipped]


def test_build_plan_devices_only_leaves_the_node_out_entirely():
    """--devices-only must not even list the node as skipped work."""
    node = device(id="node", name="node", status="NA", up_to_date=False)
    targets, skipped, node_target = build([], node, options(devices_only=True))
    assert (targets, skipped, node_target) == ([], [], None)


def test_build_plan_restart_node_selects_a_current_node():
    """--restart-node picks the node up even when its checkout is already current."""
    node = device(id="node", name="node", status="NA")
    _, _, node_target = build([], node, options(restart_node=True))
    assert node_target is not None
    assert node_target[1] == "current"


def build(devices, node, args):
    """Shorthand for build_plan, which lives on the CLI side."""
    return update_platform.build_plan(devices, node, args)


# ------------------------------------------------------------------- response handling


class FakeServer(api.UpdateServer):
    """An UpdateServer whose transport is replaced by a canned answer."""

    def __init__(self, answer):
        super().__init__("localhost")
        self.answer = answer
        self.sent = None

    def _request(self, path, payload=None, timeout=30):
        self.sent = (path, payload)
        return self.answer


def test_group_update_extracts_attributed_failures():
    """Errors carrying a device_id are surfaced with the device they belong to."""
    server = FakeServer(
        {
            "response": [
                {"old_commit": {"id": "a" * 40}, "new_commit": {"id": "b" * 40}},
                {"status": "error", "device_id": "broken", "error": "boom\ndetail"},
            ]
        }
    )
    responses, failures = server.group_update([device(id="ok"), device(id="broken")])

    assert len(responses) == 2
    assert failures == [("broken", "detail")]
    assert server.sent[0] == "/group/update"
    assert server.sent[1] == {
        "devices": [
            {"id": "ok", "ip": "http://192.168.1.10"},
            {"id": "broken", "ip": "http://192.168.1.10"},
        ]
    }


def test_group_update_reports_unattributed_errors():
    """A device's own traceback comes back without an id; it is still reported."""
    server = FakeServer({"response": [{"error": "Traceback...\nValueError: nope"}]})
    _, failures = server.group_update([device()])
    assert failures == [("<unattributed>", "ValueError: nope")]


class FakeResponse:
    """Minimal stand-in for what urlopen yields as a context manager."""

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


def test_server_error_body_becomes_an_exception(monkeypatch):
    """Bottle returns server-side failures as a 200 with an 'error' key."""
    body = json.dumps({"error": "Traceback...\nGitCommandError: no remote"})
    monkeypatch.setattr(
        api.urllib.request, "urlopen", lambda *a, **k: FakeResponse(body.encode())
    )
    with pytest.raises(api.UpdaterError, match="GitCommandError: no remote"):
        api.UpdateServer("localhost").get("/bare/update")


def test_transport_failure_becomes_an_exception(monkeypatch):
    """A dead update server is an UpdaterError, not a bare URLError."""

    def boom(*args, **kwargs):
        raise api.urllib.error.URLError("connection refused")

    monkeypatch.setattr(api.urllib.request, "urlopen", boom)
    assert api.UpdateServer("localhost").alive() is False
    with pytest.raises(api.UpdaterError):
        api.UpdateServer("localhost").get("/devices")
