"""Tests for the ``ethoscope-incubator`` CLI.

Covers the pure-function helpers (host resolution, type coercion, duration
parsing, formatter) and each subcommand handler against a mocked
:class:`IncubatorFirmwareClient`. End-to-end exercise via ``main(argv)``
confirms argparse wiring + dispatch.
"""

from __future__ import annotations

import argparse
import json
from unittest.mock import MagicMock

import pytest

from ethoscope_node.incubators import cli
from ethoscope_node.incubators.firmware_client import IncubatorHTTPError

# ---------- Pure helpers ----------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("60", 60.0),
        ("60s", 60.0),
        ("5m", 300.0),
        ("2h", 7200.0),
        ("1d", 86400.0),
        ("0.5h", 1800.0),
        ("90S", 90.0),
    ],
)
def test_parse_duration_accepts_units(raw, expected):
    assert cli.parse_duration(raw) == expected


def test_parse_duration_rejects_nonsense():
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_duration("forever")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("incubator-51", "incubator-51.local"),
        ("nodename", "nodename.local"),
        ("incubator-51.local", "incubator-51.local"),
        ("192.168.1.10", "192.168.1.10"),
        ("fe80::1", "fe80::1"),
    ],
)
def test_resolve_host_appends_local_only_to_bare(raw, expected):
    assert cli.resolve_host(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("42", 42),
        ("3.14", 3.14),
        ("true", True),
        ("FALSE", False),
        ("null", None),
        ("EU/London", "EU/London"),
        ("pool.ntp.org", "pool.ntp.org"),
    ],
)
def test_coerce_value(raw, expected):
    assert cli.coerce_value(raw) == expected


def test_parse_kv_splits_on_first_equals():
    assert cli.parse_kv("tz=EU/London") == ("tz", "EU/London")
    assert cli.parse_kv("set_temp=22") == ("set_temp", 22)


def test_parse_kv_rejects_no_equals():
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_kv("set_temp")


def test_fmt_status_human_handles_nulls():
    block = cli.fmt_status_human(
        {
            "node_id": 7,
            "fw": "3.2.0",
            "build": 11,
            "uptime_s": 12,
            "temperature": None,
            "humidity": None,
            "lux": None,
            "set_temp": 22,
            "peltier_duty": 0,
            "peltier_dir": "off",
            "fan_on": False,
            "light_level": 0,
            "max_light": 100,
            "lights_on": 540,
            "lights_off": 1260,
            "light_period_minutes": 1440,
            "light_cycle_anchor": 0,
            "rtc": False,
            "time_valid": False,
            "sensor_fault": True,
            "time": 0,  # falsy → no clock line
        }
    )
    assert "incubator-7" in block
    assert "N/A" in block  # nulls render
    assert "MISSING" in block  # rtc:false renders as MISSING
    assert "sensor_fault YES" in block


# ---------- Subcommand handlers (mocked client) ----------


def _ns(**kw):
    """Build a Namespace-like with attribute access for the handlers."""
    obj = MagicMock()
    for k, v in kw.items():
        setattr(obj, k, v)
    return obj


def test_cmd_status_one_shot_returns_zero(capsys):
    client = MagicMock()
    client.get_telemetry.return_value = {"node_id": 1, "fw": "x", "build": 1}
    rc = cli.cmd_status(_ns(host="incubator-51", json=False, watch=None), client)
    assert rc == 0
    client.get_telemetry.assert_called_once_with("incubator-51.local")
    out = capsys.readouterr().out
    assert "incubator-1" in out


def test_cmd_status_json_emits_machine_readable(capsys):
    client = MagicMock()
    client.get_telemetry.return_value = {"node_id": 1, "temperature": 22.5}
    rc = cli.cmd_status(_ns(host="incubator-51", json=True, watch=None), client)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["temperature"] == 22.5


def test_cmd_status_returns_error_on_http_failure(capsys):
    client = MagicMock()
    client.get_telemetry.side_effect = IncubatorHTTPError("unreachable")
    rc = cli.cmd_status(_ns(host="x", json=False, watch=None), client)
    assert rc == 2
    assert "unreachable" in capsys.readouterr().err


def test_cmd_config_outputs_table(capsys):
    client = MagicMock()
    client.get_config.return_value = {"tz": "UTC", "set_temp": 22}
    rc = cli.cmd_config(_ns(host="x", json=False), client)
    assert rc == 0
    out = capsys.readouterr().out
    assert "tz" in out and "UTC" in out


def test_cmd_set_pushes_typed_payload(capsys):
    client = MagicMock()
    client.push_config.return_value = {"changed": 2, "config": {}}
    args = _ns(
        host="incubator-51",
        assignments=[("set_temp", 22), ("max_light", 80)],
        json=False,
    )
    rc = cli.cmd_set(args, client)
    assert rc == 0
    client.push_config.assert_called_once_with(
        "incubator-51.local", {"set_temp": 22, "max_light": 80}
    )


def test_cmd_light_clamps_pct(capsys):
    client = MagicMock()
    client.set_light_override.return_value = {}
    cli.cmd_light(_ns(host="x", pct=250, json=False), client)
    client.set_light_override.assert_called_once_with("x.local", 100)
    client.reset_mock()
    cli.cmd_light(_ns(host="x", pct=-5, json=False), client)
    client.set_light_override.assert_called_once_with("x.local", 0)


def test_cmd_reboot_calls_client(capsys):
    client = MagicMock()
    client.reboot.return_value = {"reboot": True}
    rc = cli.cmd_reboot(_ns(host="x", json=False), client)
    assert rc == 0
    client.reboot.assert_called_once_with("x.local")


def test_cmd_time_sync_calls_sync_time(capsys):
    client = MagicMock()
    client.sync_time.return_value = {"sync_time": True}
    rc = cli.cmd_time_sync(_ns(host="x", json=False), client)
    assert rc == 0
    client.sync_time.assert_called_once_with("x.local")


def test_cmd_time_set_with_epoch_int(capsys):
    client = MagicMock()
    client.set_time.return_value = {"set_time": 100}
    rc = cli.cmd_time_set(_ns(host="x", epoch="100", json=False), client)
    assert rc == 0
    client.set_time.assert_called_once_with("x.local", 100)


def test_cmd_time_set_rejects_garbage(capsys):
    client = MagicMock()
    rc = cli.cmd_time_set(_ns(host="x", epoch="banana", json=False), client)
    assert rc == 2
    client.set_time.assert_not_called()
    assert "epoch" in capsys.readouterr().err


def test_cmd_i2c_prints_device_table(capsys):
    client = MagicMock()
    client.get_i2c_scan.return_value = {
        "count": 2,
        "devices": [
            {"addr": "0x44", "name": "SHT31"},
            {"addr": "0x68", "name": "DS3231/DS1307"},
        ],
    }
    rc = cli.cmd_i2c(_ns(host="x", json=False), client)
    assert rc == 0
    out = capsys.readouterr().out
    assert "0x44" in out and "SHT31" in out
    assert "0x68" in out and "DS3231" in out


def test_cmd_i2c_handles_empty_bus(capsys):
    client = MagicMock()
    client.get_i2c_scan.return_value = {"count": 0, "devices": []}
    rc = cli.cmd_i2c(_ns(host="x", json=False), client)
    assert rc == 0
    assert "0 device(s)" in capsys.readouterr().out


def test_cmd_health_emits_json_when_requested(capsys):
    client = MagicMock()
    client.get_health.return_value = {"wifi": True, "rtc": True}
    rc = cli.cmd_health(_ns(host="x", json=True), client)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rtc"] is True


# ---------- main() end-to-end (argparse wiring) ----------


def test_main_dispatches_status(monkeypatch, capsys):
    """A full argv → main() pass should route to cmd_status with the right host."""
    fake = MagicMock()
    fake.get_telemetry.return_value = {"node_id": 9, "fw": "x", "build": 1}
    monkeypatch.setattr(cli, "IncubatorFirmwareClient", lambda timeout: fake)
    rc = cli.main(["status", "incubator-9"])
    assert rc == 0
    fake.get_telemetry.assert_called_once_with("incubator-9.local")


def test_main_dispatches_set_with_typed_assignments(monkeypatch):
    fake = MagicMock()
    fake.push_config.return_value = {}
    monkeypatch.setattr(cli, "IncubatorFirmwareClient", lambda timeout: fake)
    rc = cli.main(["set", "10.0.0.5", "set_temp=22", "tz=EU/London"])
    assert rc == 0
    fake.push_config.assert_called_once_with(
        "10.0.0.5", {"set_temp": 22, "tz": "EU/London"}
    )


def test_main_requires_subcommand(capsys):
    with pytest.raises(SystemExit):
        cli.main([])


def test_main_dispatches_time_subcommand(monkeypatch):
    fake = MagicMock()
    fake.sync_time.return_value = {}
    monkeypatch.setattr(cli, "IncubatorFirmwareClient", lambda timeout: fake)
    rc = cli.main(["time", "sync", "incubator-51"])
    assert rc == 0
    fake.sync_time.assert_called_once_with("incubator-51.local")
