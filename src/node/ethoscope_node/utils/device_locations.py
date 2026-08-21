"""Answer "which incubator is this ethoscope in?" for every known device.

Three sources say something about where a device is, in decreasing order of
confidence:

1. ``experimental_info.current.location`` — the device is running right now and
   reports the incubator it was started in. Authoritative.
2. ``experimental_info.previous.location`` — the device is online but idle, and
   still remembers its last run.
3. the node's ``runs`` table — the device is switched off and reports nothing
   at all, but the node recorded where it last ran.

Without (3) most of a real fleet disappears from an occupancy view, since an
ethoscope spends much of its life powered down. Each attribution therefore
carries the ``source`` it came from, so the UI can show a current placement
differently from a months-old memory.

The resolution itself is a pure function of the two inputs, which keeps it
testable without a scanner or a database.
"""

from __future__ import annotations

from typing import Any

# Provenance of an attribution, most to least current.
CURRENT = "current"
PREVIOUS = "previous"
LAST_RUN = "last_run"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _as_timestamp(value: Any) -> float | None:
    """Best-effort unix timestamp from whatever the payload carried."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_device_location(
    info: dict[str, Any],
    last_run: dict[str, Any] | None,
) -> dict[str, Any]:
    """Work out where one device is.

    Args:
        info (dict): The device's entry from the scanner's device map.
        last_run (dict | None): That device's row from
            :meth:`ExperimentalDB.getLastKnownLocations`, if it has one.

    Returns:
        dict: ``{"incubator", "source", "since", "user"}``. ``incubator`` is
        ``None`` when nothing places the device anywhere, in which case
        ``source`` is ``None`` too.
    """
    experimental_info = info.get("experimental_info") or {}
    current = experimental_info.get("current") or {}
    previous = experimental_info.get("previous") or {}
    last_run = last_run or {}

    location = _clean(current.get("location"))
    if location:
        # The newest recorded run is this one, so it dates the placement —
        # but only claim that when the run ids actually agree.
        same_run = _clean(last_run.get("run_id")) == _clean(current.get("run_id"))
        return {
            "incubator": location,
            "source": CURRENT,
            "since": last_run.get("since") if same_run else None,
            "user": _clean(current.get("name")),
        }

    location = _clean(previous.get("location"))
    if location:
        return {
            "incubator": location,
            "source": PREVIOUS,
            "since": _as_timestamp(previous.get("date_time")),
            "user": _clean(previous.get("user")),
        }

    location = _clean(last_run.get("location"))
    if location:
        return {
            "incubator": location,
            "source": LAST_RUN,
            "since": last_run.get("since"),
            "user": _clean(last_run.get("user")),
        }

    return {"incubator": None, "source": None, "since": None, "user": ""}


def resolve_device_locations(
    devices: dict[str, dict[str, Any]],
    last_runs: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Resolve every device in the scanner's map.

    Args:
        devices (dict): Device map keyed by device id (the scanner's
            ``get_all_devices_info()`` output).
        last_runs (dict): Last-known locations keyed by device id, from
            :meth:`ExperimentalDB.getLastKnownLocations`.

    Returns:
        dict: One entry per device, keyed by device id, carrying the device's
        ``name`` and ``status`` alongside the resolved placement. Devices that
        cannot be placed are still listed, with ``incubator`` set to ``None``,
        so the caller can show them as unplaced rather than silently lose them.
    """
    resolved = {}
    for device_id, info in (devices or {}).items():
        info = info or {}
        placement = resolve_device_location(info, (last_runs or {}).get(device_id))
        resolved[device_id] = {
            "id": device_id,
            "name": info.get("name") or device_id,
            "status": info.get("status") or "unknown",
            **placement,
        }
    return resolved
