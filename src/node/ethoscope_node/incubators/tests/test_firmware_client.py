"""Tests for the firmware HTTP client.

Uses stdlib ``unittest.mock`` to patch ``requests.get`` / ``requests.post``.
This keeps the minimal-install dependency set lean (no ``responses`` /
``requests-mock``).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from ethoscope_node.incubators.firmware_client import (
    IncubatorFirmwareClient,
    IncubatorHTTPError,
)


def _ok_response(json_body=None, *, text="", status=200):
    resp = MagicMock()
    resp.status_code = status
    if json_body is None:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_body
    resp.text = text
    return resp


@pytest.fixture
def client():
    return IncubatorFirmwareClient(timeout=1.0)


def test_get_telemetry_returns_json(client):
    payload = {"node_id": 1, "temperature": 24.5}
    with patch("requests.get", return_value=_ok_response(payload)) as m:
        assert client.get_telemetry("10.0.0.5") == payload
    m.assert_called_once_with("http://10.0.0.5:80/telemetry", timeout=1.0)


def test_get_config_returns_json(client):
    with patch("requests.get", return_value=_ok_response({"lights_on": "09:00"})):
        assert client.get_config("10.0.0.5") == {"lights_on": "09:00"}


def test_push_config_posts_json(client):
    payload = {"lights_on": "10:00", "fade_in_ms": 5000}
    with patch("requests.post", return_value=_ok_response({"result": "ok"})) as m:
        result = client.push_config("10.0.0.5", payload)
    assert result == {"result": "ok"}
    m.assert_called_once_with("http://10.0.0.5:80/config", json=payload, timeout=1.0)


def test_set_location_uses_correct_endpoint(client):
    with patch("requests.post", return_value=_ok_response({"result": "ok"})) as m:
        client.set_location("10.0.0.5", "MyIncubator")
    m.assert_called_once_with(
        "http://10.0.0.5:80/set", json={"location": "MyIncubator"}, timeout=1.0
    )


def test_set_light_override(client):
    with patch("requests.post", return_value=_ok_response({"result": "ok"})) as m:
        client.set_light_override("10.0.0.5", 42)
    m.assert_called_once_with(
        "http://10.0.0.5:80/command", json={"set_light": 42}, timeout=1.0
    )


def test_non_200_raises_incubator_http_error(client):
    with patch(
        "requests.get",
        return_value=_ok_response({"error": "bad"}, status=500),
    ):
        with pytest.raises(IncubatorHTTPError, match="returned 500"):
            client.get_telemetry("10.0.0.5")


def test_network_error_raises_incubator_http_error(client):
    with patch("requests.get", side_effect=requests.ConnectionError("nope")):
        with pytest.raises(IncubatorHTTPError, match="failed"):
            client.get_telemetry("10.0.0.99")


def test_empty_post_response_treated_as_ok(client):
    # No JSON body → push_config treats 200+non-JSON as {} (some endpoints reply empty).
    with patch("requests.post", return_value=_ok_response(None)):
        assert client.push_config("10.0.0.5", {"max_light": 50}) == {}


def test_custom_port(client):
    with patch("requests.get", return_value=_ok_response({"node_id": 9})) as m:
        assert client.get_telemetry("10.0.0.5", port=8080) == {"node_id": 9}
    m.assert_called_once_with("http://10.0.0.5:8080/telemetry", timeout=1.0)


def test_get_with_invalid_json_raises(client):
    # GET endpoints REQUIRE JSON; this is the contract.
    with patch("requests.get", return_value=_ok_response(None)):
        with pytest.raises(IncubatorHTTPError, match="non-JSON"):
            client.get_telemetry("10.0.0.5")


def test_get_health_hits_health_endpoint(client):
    with patch("requests.get", return_value=_ok_response({"wifi": True})) as m:
        assert client.get_health("10.0.0.5") == {"wifi": True}
    m.assert_called_once_with("http://10.0.0.5:80/health", timeout=1.0)


def test_get_i2c_scan_hits_scan_endpoint(client):
    payload = {"count": 1, "devices": [{"addr": "0x44", "name": "SHT31"}]}
    with patch("requests.get", return_value=_ok_response(payload)) as m:
        assert client.get_i2c_scan("10.0.0.5") == payload
    m.assert_called_once_with("http://10.0.0.5:80/i2c_scan", timeout=1.0)


def test_reboot_posts_reboot_command(client):
    with patch("requests.post", return_value=_ok_response({"reboot": True})) as m:
        assert client.reboot("10.0.0.5") == {"reboot": True}
    m.assert_called_once_with(
        "http://10.0.0.5:80/command", json={"reboot": True}, timeout=1.0
    )


def test_sync_time_posts_sync_time_command(client):
    with patch("requests.post", return_value=_ok_response({"sync_time": True})) as m:
        client.sync_time("10.0.0.5")
    m.assert_called_once_with(
        "http://10.0.0.5:80/command", json={"sync_time": True}, timeout=1.0
    )


def test_set_time_posts_set_time_command_as_int(client):
    with patch("requests.post", return_value=_ok_response({"set_time": 100})) as m:
        client.set_time("10.0.0.5", 100)
    m.assert_called_once_with(
        "http://10.0.0.5:80/command", json={"set_time": 100}, timeout=1.0
    )
