"""Framework-agnostic route handlers.

Each public method takes a small set of arguments (already-parsed JSON, path
parameters) and returns a dict that is serialised by the calling framework.
The Bottle adapter in :mod:`ethoscope_node.incubators.bottle_app` and the
node-side bridge in :mod:`ethoscope_node.api.incubator_api` both reuse this
class — that's the whole point of carving the handlers out of any specific
HTTP framework.

Result-shape convention: a successful call returns whatever data is asked
for. A failure returns ``{"result": "error", "message": <str>, ...}`` and the
caller is expected to translate that to an HTTP status (the standalone
adapter uses 400; the node adapter currently uses the legacy 200-with-error
payload for backwards compatibility — both are fine because the body shape is
identical).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ethoscope_node.incubators.firmware_client import (
    IncubatorFirmwareClient,
    IncubatorHTTPError,
)
from ethoscope_node.incubators.scanner import IncubatorScanner
from ethoscope_node.incubators.schedule import build_firmware_payload
from ethoscope_node.incubators.storage import IncubatorStorage

# Fields the standalone server accepts in add/update payloads. Anything else
# is silently ignored; the storage backend also has its own whitelist.
_WRITE_FIELDS = (
    "name",
    "location",
    "owner",
    "description",
    "active",
    "lights_on",
    "lights_off",
    "light_period_minutes",
    "light_cycle_anchor",
    "hostname",
    "fade_in_seconds",
    "fade_out_seconds",
    "max_light",
    "crepuscular",
    "type",
    "set_temp",
)


def _ok(**fields: Any) -> dict[str, Any]:
    return {"result": "success", **fields}


def _err(message: str, **fields: Any) -> dict[str, Any]:
    return {"result": "error", "message": message, **fields}


class IncubatorRoutes:
    """Bundle of handler methods sharing storage + scanner + firmware client."""

    def __init__(
        self,
        storage: IncubatorStorage,
        scanner: IncubatorScanner | None,
        client: IncubatorFirmwareClient,
    ):
        self._storage = storage
        self._scanner = scanner
        self._client = client
        self._logger = logging.getLogger(self.__class__.__name__)

    # --- read endpoints ----------------------------------------------------------

    def list_live(self) -> dict[str, dict[str, Any]]:
        """Discovered WiFi incubators keyed by their derived hostname/id."""
        if self._scanner is None:
            return {}
        return self._scanner.get_all_devices_info() or {}

    def list_merged(self) -> dict[str, dict[str, Any]]:
        """Join storage records and live telemetry. Same shape as Phase 1.

        Each entry gains a ``source`` field ('configured' | 'discovered' |
        'both') and, when a live unit is present, its telemetry plus an
        online/offline ``live_status``. Configured incubators with no
        ``hostname`` (never bound) report ``live_status='unbound'``.
        """
        discovered = {}
        if self._scanner is not None:
            for _id, info in (self._scanner.get_all_devices_info() or {}).items():
                hostname = info.get("hostname") or _id
                discovered[hostname] = info

        configured = self._storage.list_all() or {}

        merged: dict[str, dict[str, Any]] = {}
        for name, cfg in configured.items():
            entry = dict(cfg)
            hostname = cfg.get("hostname")
            live = discovered.pop(hostname, None) if hostname else None
            if live is not None:
                entry.update(self._live_fields(live))
                entry["source"] = "both"
            else:
                entry["source"] = "configured"
                entry["live_status"] = "offline" if hostname else "unbound"
            merged[name] = entry

        # Remaining discovered-but-unbound units (no DB record references them).
        for hostname, live in discovered.items():
            entry = {
                "name": hostname,
                "hostname": hostname,
                "source": "discovered",
            }
            entry.update(self._live_fields(live))
            merged[hostname] = entry

        return merged

    @staticmethod
    def _live_fields(live: dict) -> dict:
        """Pick the live fields the merged view needs."""
        status = live.get("status", "offline")
        return {
            "ip": live.get("ip", ""),
            "live_status": status,
            "node_id": live.get("node_id"),
            "fw": live.get("fw", ""),
            "temperature": live.get("temperature"),
            "humidity": live.get("humidity"),
            "lux": live.get("lux"),
            "set_temp": live.get("set_temp"),
            "light_level": live.get("light_level"),
            "max_light": live.get("max_light"),
            "lights_on_fw": live.get("lights_on"),
            "lights_off_fw": live.get("lights_off"),
            "light_period_minutes_fw": live.get("light_period_minutes"),
            "light_cycle_anchor_fw": live.get("light_cycle_anchor"),
            "fade_in_ms_fw": live.get("fade_in_ms"),
            "fade_out_ms_fw": live.get("fade_out_ms"),
            "peltier_duty": live.get("peltier_duty"),
            "peltier_dir": live.get("peltier_dir"),
            "fan_on": live.get("fan_on"),
            "sensor_fault": live.get("sensor_fault"),
            "rssi": live.get("rssi"),
            "last_seen": live.get("last_seen", ""),
        }

    def get_telemetry(self, name: str) -> dict[str, Any]:
        """Passthrough to the firmware's ``/telemetry`` for an incubator by name."""
        record = self._storage.get(name=name)
        if record is None:
            return _err(f"Incubator '{name}' not found")
        hostname = record.get("hostname")
        if not hostname or self._scanner is None:
            return _err(f"Incubator '{name}' is not bound to any unit")
        device = self._scanner.get_device_by_hostname(hostname)
        if device is None:
            return _err(f"Unit '{hostname}' is offline")
        try:
            return self._client.get_telemetry(device.ip(), port=device._port)
        except IncubatorHTTPError as e:
            return _err(str(e))

    # --- write endpoints ---------------------------------------------------------

    def add(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a new incubator. Pushes schedule if a hostname is bound."""
        record = self._sanitize_write(payload)
        if not record.get("name"):
            return _err("Incubator name is required")
        new_id = self._storage.add(record)
        if new_id < 0:
            return _err(f"Could not add incubator '{record['name']}'")
        pushed = self._maybe_push(record["name"])
        return _ok(id=new_id, name=record["name"], pushed=pushed)

    def update(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Patch an existing incubator. Pushes schedule if hostname is bound after.

        Rename via this endpoint is not supported — ``name`` in the payload is
        silently dropped. Delete-then-re-add if you need to change a name.
        """
        record = self._storage.get(name=name)
        if record is None:
            return _err(f"Incubator '{name}' not found")
        patch = self._sanitize_write(payload)
        patch.pop("name", None)
        rows = self._storage.update(name=name, **patch)
        if rows < 0:
            return _err(f"Could not update incubator '{name}'")
        pushed = self._maybe_push(name)
        return _ok(rows_affected=rows, pushed=pushed)

    def delete(self, name: str) -> dict[str, Any]:
        rows = self._storage.delete(name=name)
        if rows < 0:
            return _err(f"Could not delete incubator '{name}'")
        return _ok(rows_affected=rows)

    def bind(self, name: str, hostname: str | None) -> dict[str, Any]:
        """Bind a record to a physical unit hostname (or None to unbind).

        On bind: also pushes the incubator name as the unit's sensor
        ``location`` (best-effort) AND pushes the schedule.
        """
        record = self._storage.get(name=name)
        if record is None:
            return _err(f"Incubator '{name}' not found")
        clean_hostname = (
            str(hostname).strip()
            if hostname is not None and str(hostname).strip()
            else None
        )
        # Binding a physical unit makes the record 'smart' (firmware-backed,
        # light + temperature); unbinding reverts it to a plain manual 'normal'
        # incubator since it no longer has any hardware.
        update_fields: dict[str, Any] = {
            "hostname": clean_hostname,
            "type": "smart" if clean_hostname else "normal",
        }
        rows = self._storage.update(name=name, **update_fields)
        if rows < 0:
            return _err(f"Could not bind incubator '{name}'")
        location_pushed = False
        schedule_pushed = False
        if clean_hostname and self._scanner is not None:
            # Both pushes need a live device — skip cleanly when offline so the
            # bind itself still succeeds and we retry on the next reconcile tick.
            device = self._scanner.get_device_by_hostname(clean_hostname)
            if device is not None:
                try:
                    # The unit also acts as a sensor; mirror the incubator name
                    # onto its sensor name + location so it groups correctly.
                    self._scanner.set_identity(clean_hostname, name=name, location=name)
                    location_pushed = True
                except Exception as e:
                    self._logger.warning(
                        "Bound %s -> %s but could not push identity: %s",
                        name,
                        clean_hostname,
                        e,
                    )
                schedule_pushed = self._maybe_push(name)
        return _ok(
            name=name,
            hostname=clean_hostname,
            location_pushed=location_pushed,
            schedule_pushed=schedule_pushed,
        )

    def push_schedule(self, name: str) -> dict[str, Any]:
        """Manual push of the storage schedule to the bound firmware."""
        if self._maybe_push(name, force=True):
            return _ok(name=name)
        return _err(f"Could not push schedule for '{name}' (unbound or unit offline)")

    def push_identity(self, name: str) -> bool:
        """Mirror the incubator name onto its bound unit's sensor name+location.

        Best-effort: returns True only when actually pushed to an online unit.
        Used after a rename (and on adopt) so the associated sensor follows the
        incubator name. Silently returns False when unbound or offline.
        """
        record = self._storage.get(name=name)
        if record is None:
            return False
        hostname = record.get("hostname")
        if not hostname or self._scanner is None:
            return False
        if self._scanner.get_device_by_hostname(hostname) is None:
            return False
        try:
            self._scanner.set_identity(hostname, name=name, location=name)
            return True
        except Exception as e:
            self._logger.warning(
                "Could not push identity for '%s' -> %s: %s", name, hostname, e
            )
            return False

    def reset_anchor(self, name: str) -> dict[str, Any]:
        """Stamp ``light_cycle_anchor = now()`` on the record and push."""
        rows = self._storage.update(name=name, light_cycle_anchor=time.time())
        if rows < 0:
            return _err(f"Could not reset anchor for '{name}'")
        if rows == 0:
            return _err(f"Incubator '{name}' not found")
        pushed = self._maybe_push(name)
        return _ok(name=name, pushed=pushed)

    def light_override(self, name: str, pct: int) -> dict[str, Any]:
        """Transient firmware ``POST /command set_light``. Useful for bench testing."""
        record = self._storage.get(name=name)
        if record is None:
            return _err(f"Incubator '{name}' not found")
        hostname = record.get("hostname")
        if not hostname or self._scanner is None:
            return _err(f"Incubator '{name}' is not bound")
        device = self._scanner.get_device_by_hostname(hostname)
        if device is None:
            return _err(f"Unit '{hostname}' is offline")
        try:
            self._client.set_light_override(device.ip(), int(pct), port=device._port)
            return _ok(name=name, pct=int(pct))
        except IncubatorHTTPError as e:
            return _err(str(e))

    # --- helpers -----------------------------------------------------------------

    @staticmethod
    def _sanitize_write(payload: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of `payload` containing only writable fields."""
        return {k: v for k, v in payload.items() if k in _WRITE_FIELDS}

    def _maybe_push(self, name: str, *, force: bool = False) -> bool:
        """Push the storage schedule to the bound firmware. Best-effort.

        Returns True when a push actually completed successfully. Returns
        False if the record has no hostname binding, the unit is offline, or
        the firmware rejected the push (logged at WARNING).
        """
        record = self._storage.get(name=name)
        if record is None:
            return False
        hostname = record.get("hostname")
        if not hostname or self._scanner is None:
            return False
        device = self._scanner.get_device_by_hostname(hostname)
        if device is None:
            if force:
                self._logger.warning(
                    "Manual push of '%s' aborted: unit '%s' is offline",
                    name,
                    hostname,
                )
            return False
        try:
            payload = build_firmware_payload(record)
            self._client.push_config(device.ip(), payload, port=device._port)
            return True
        except IncubatorHTTPError as e:
            self._logger.warning(
                "Push of '%s' to %s failed (best-effort): %s", name, hostname, e
            )
            return False
