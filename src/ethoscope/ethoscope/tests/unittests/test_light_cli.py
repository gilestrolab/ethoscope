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
    def __init__(self, *_, **__):
        self.calls = []

    def force_on(self):
        self.calls.append("force_on")

    def force_off(self):
        self.calls.append("force_off")

    def release(self):
        self.calls.append("release")

    def status(self):
        self.calls.append("status")
        return {"led": "on", "mode": "forced", "force": "on"}


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
