"""
Tests for the ethoscope-light CLI.
"""

import io
import json
from unittest.mock import patch

import pytest

from ethoscope.hardware.interfaces import light_cli
from ethoscope.hardware.interfaces.light_daemon import LightDaemonUnavailable


class _FakeClient:
    def __init__(self, *_, led=0, **__):
        self.calls = []
        self.pcts = []  # every FORCE PCT value, in order
        self._led = led

    def force_on(self):
        self.calls.append("force_on")

    def force_off(self):
        self.calls.append("force_off")

    def force_pct(self, pct):
        self.calls.append("force_pct")
        self.pcts.append(int(pct))

    def release(self):
        self.calls.append("release")

    def status(self):
        self.calls.append("status")
        return {"led": self._led, "mode": "forced", "force": self._led}


@pytest.fixture
def fake_client():
    fake = _FakeClient()
    with patch.object(light_cli, "LightDaemonClient", return_value=fake):
        yield fake


def _run(argv, capsys):
    rc = light_cli.main(argv)
    return rc, capsys.readouterr()


class TestDispatch:
    def test_on(self, fake_client, capsys):
        rc, captured = _run(["on"], capsys)
        assert rc == 0
        assert fake_client.calls == ["force_on"]
        assert "ON" in captured.out

    def test_off(self, fake_client, capsys):
        rc, captured = _run(["off"], capsys)
        assert rc == 0
        assert fake_client.calls == ["force_off"]
        assert "OFF" in captured.out

    def test_release(self, fake_client, capsys):
        rc, captured = _run(["release"], capsys)
        assert rc == 0
        assert fake_client.calls == ["release"]
        assert "schedule" in captured.out.lower()

    def test_status_prints_json(self, fake_client, capsys):
        rc, captured = _run(["status"], capsys)
        assert rc == 0
        payload = json.loads(captured.out)
        assert payload["mode"] == "forced"


class TestUnavailable:
    def test_returns_1_and_writes_stderr(self, capsys):
        class _Broken:
            def force_on(self):
                raise LightDaemonUnavailable("boom")

        with patch.object(light_cli, "LightDaemonClient", return_value=_Broken()):
            rc = light_cli.main(["on"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "not reachable" in captured.err


def _run_with(client, argv):
    """Run the CLI against a specific fake client, with time.sleep stubbed out."""
    with (
        patch.object(light_cli, "LightDaemonClient", return_value=client),
        patch.object(light_cli.time, "sleep"),
    ):
        return light_cli.main(argv)


class TestFade:
    def test_fade_up_lands_on_target_and_holds(self):
        client = _FakeClient(led=0)
        rc = _run_with(client, ["fade", "100"])
        assert rc == 0
        assert "status" in client.calls  # start level read from the daemon
        assert client.pcts, "fade must emit FORCE PCT steps"
        assert client.pcts[-1] == 100
        assert client.pcts == sorted(client.pcts)  # monotonic non-decreasing
        assert all(0 <= p <= 100 for p in client.pcts)
        assert "release" not in client.calls  # fade holds the level

    def test_fade_down_is_monotonic(self):
        client = _FakeClient(led=100)
        rc = _run_with(client, ["fade", "0", "-t", "1"])
        assert rc == 0
        assert client.pcts[-1] == 0
        assert client.pcts == sorted(client.pcts, reverse=True)

    def test_fade_to_current_level_is_single_write(self):
        client = _FakeClient(led=50)
        rc = _run_with(client, ["fade", "50"])
        assert rc == 0
        assert client.pcts == [50]  # start == target => one immediate set

    def test_fade_clamps_out_of_range_target(self):
        client = _FakeClient(led=0)
        rc = _run_with(client, ["fade", "250"])
        assert rc == 0
        assert max(client.pcts) == 100


class TestTest:
    def test_cycles_start_dark_and_release(self):
        client = _FakeClient(led=0)
        rc = _run_with(client, ["test", "-n", "2", "-t", "0.1"])
        assert rc == 0
        assert client.calls[0] == "force_off"  # known dark start
        assert client.calls[-1] == "release"  # resume schedule at the end
        assert max(client.pcts) == 100 and min(client.pcts) == 0
        assert client.pcts.count(100) >= 2  # reached full brightness each cycle

    def test_default_is_three_cycles(self):
        client = _FakeClient(led=0)
        rc = _run_with(client, ["test", "-t", "0.1"])
        assert rc == 0
        assert client.pcts.count(100) >= 3
