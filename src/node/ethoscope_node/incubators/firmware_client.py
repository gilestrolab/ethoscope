"""HTTP client for the smart-incubator firmware (REST endpoints).

The firmware exposes a small REST API on the same host that mDNS advertises
under ``_incubator._tcp``. All endpoints are idempotent (with the exception of
``POST /command set_light`` which is a transient override). This client is
pure HTTP — no mDNS, no threads. The scanner ``Incubator`` instance owns the
polling thread; this client is used both by the scanner (for ``set_location``
and ``push_config`` pushes) and by the standalone server (for ad-hoc pushes
triggered from the web UI).
"""

from __future__ import annotations

import logging
from typing import Any

import requests

DEFAULT_TIMEOUT_S = 5.0
DEFAULT_PORT = 80


class IncubatorHTTPError(RuntimeError):
    """Raised when the firmware returns a non-success status or is unreachable."""


class IncubatorFirmwareClient:
    """Minimal HTTP client targeting a single smart-incubator unit by IP."""

    def __init__(self, *, timeout: float = DEFAULT_TIMEOUT_S):
        self._timeout = timeout
        self._logger = logging.getLogger(self.__class__.__name__)

    def _url(self, ip: str, path: str, port: int = DEFAULT_PORT) -> str:
        return f"http://{ip}:{port}{path}"

    def _get(self, ip: str, path: str, port: int = DEFAULT_PORT) -> dict[str, Any]:
        url = self._url(ip, path, port)
        try:
            resp = requests.get(url, timeout=self._timeout)
        except requests.RequestException as e:
            raise IncubatorHTTPError(f"GET {url} failed: {e}") from e
        if resp.status_code != 200:
            raise IncubatorHTTPError(f"GET {url} returned {resp.status_code}")
        try:
            return resp.json()
        except ValueError as e:
            raise IncubatorHTTPError(f"GET {url} returned non-JSON body") from e

    def _post_json(
        self, ip: str, path: str, payload: dict[str, Any], port: int = DEFAULT_PORT
    ) -> dict[str, Any]:
        url = self._url(ip, path, port)
        try:
            resp = requests.post(url, json=payload, timeout=self._timeout)
        except requests.RequestException as e:
            raise IncubatorHTTPError(f"POST {url} failed: {e}") from e
        if resp.status_code != 200:
            raise IncubatorHTTPError(
                f"POST {url} returned {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError:
            # Some firmware endpoints reply with an empty 200 — treat as OK.
            return {}

    def get_telemetry(self, ip: str, *, port: int = DEFAULT_PORT) -> dict[str, Any]:
        """Fetch ``/telemetry`` — the live state snapshot of the unit."""
        return self._get(ip, "/telemetry", port)

    def get_config(self, ip: str, *, port: int = DEFAULT_PORT) -> dict[str, Any]:
        """Fetch ``/config`` — the unit's persisted configuration."""
        return self._get(ip, "/config", port)

    def push_config(
        self, ip: str, payload: dict[str, Any], *, port: int = DEFAULT_PORT
    ) -> dict[str, Any]:
        """Push a partial config update via ``POST /config``.

        The firmware accepts any subset of its config fields and persists what
        is sent. Use :func:`ethoscope_node.incubators.schedule.build_firmware_payload`
        to construct the payload from a storage record.
        """
        return self._post_json(ip, "/config", payload, port)

    def set_location(
        self, ip: str, location: str, *, port: int = DEFAULT_PORT
    ) -> dict[str, Any]:
        """Push the sensor ``location`` string via ``POST /set``.

        Keeps the unit's etho_sensor-channel ``location`` aligned with its
        bound incubator name so CSV/alerts/Sensors-page readings group under
        that incubator. Mirrors the existing Phase 1 behaviour.
        """
        return self._post_json(ip, "/set", {"location": location}, port)

    def set_light_override(
        self, ip: str, pct: int, *, port: int = DEFAULT_PORT
    ) -> dict[str, Any]:
        """Force the panel to a brightness percentage via ``POST /command``.

        Transient — the next schedule tick on the firmware (~ once per
        minute) re-overrides this. Useful for bench testing and for the
        standalone UI's preview button.
        """
        return self._post_json(ip, "/command", {"set_light": int(pct)}, port)
