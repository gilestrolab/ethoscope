"""Schedule evaluation and firmware-payload helpers.

The ``is_light_on`` function is the canonical reference: a faithful port of
``ethoscope.hardware.interfaces.light_daemon.LightController.should_light_be_on``
(device side) and the algorithm that the smart-incubator firmware
``LightControl::isLightOn`` implements (firmware side). All three must stay
behaviourally identical so the node, the ethoscope, and the firmware reach the
same decision for any given (now, lights_on, lights_off, period, anchor).

The schedule has two modes, picked automatically:

* **Wall-clock mode** — anchor is None *and* period_minutes is either None or
  1440. ``lights_on`` / ``lights_off`` are HH:MM times of day, cycle repeats
  every 24 h anchored to local midnight. Handles schedules that cross
  midnight (e.g. 22:00 to 06:00).
* **Anchored / T-cycle mode** — anchor is a unix timestamp marking ZT0.
  ``lights_on`` / ``lights_off`` are HH:MM *offsets* into a cycle of length
  ``period_minutes``. Used for non-24 h cycles or to phase-lock a 24 h cycle
  to a chosen wall-clock moment.
"""

from __future__ import annotations

import datetime
import time
from typing import Any

SCHEDULE_FIELDS = (
    "lights_on",
    "lights_off",
    "light_period_minutes",
    "light_cycle_anchor",
    "fade_in_seconds",
    "fade_out_seconds",
    "max_light",
)


def _parse_hhmm(time_str: str) -> datetime.time | None:
    """Parse an ``HH:MM`` string. Returns None on any parse failure."""
    try:
        parts = time_str.strip().split(":")
        return datetime.time(int(parts[0]), int(parts[1]))
    except (AttributeError, ValueError, IndexError):
        return None


def is_light_on(
    lights_on_str: str,
    lights_off_str: str,
    *,
    now: datetime.datetime | datetime.time | float | int | None = None,
    period_minutes: int | None = None,
    anchor: float | None = None,
) -> bool:
    """Return True iff the light should be on right now for the given schedule.

    Args:
        lights_on_str: HH:MM string for lights-on.
        lights_off_str: HH:MM string for lights-off.
        now: Optional override for the current moment. In wall-clock mode
            accepts a ``datetime.time`` or ``datetime.datetime``; in anchored
            mode accepts a ``datetime.datetime`` or a unix timestamp.
        period_minutes: Cycle length in minutes. ``None`` or ``1440`` with no
            anchor selects wall-clock mode.
        anchor: Unix timestamp marking ZT0. Required for non-24 h periods.

    Returns:
        ``True`` if the light should be on, ``False`` otherwise (including for
        any unparseable input — refusing is safer than guessing).
    """
    on_time = _parse_hhmm(lights_on_str)
    off_time = _parse_hhmm(lights_off_str)
    if on_time is None or off_time is None:
        return False

    on_seconds = on_time.hour * 3600 + on_time.minute * 60
    off_seconds = off_time.hour * 3600 + off_time.minute * 60

    use_anchored = anchor is not None or (
        period_minutes is not None and int(period_minutes) != 1440
    )

    if use_anchored:
        if anchor is None:
            return False
        try:
            period_s = int(period_minutes) * 60 if period_minutes else 86400
        except (TypeError, ValueError):
            return False
        if period_s <= 0:
            return False
        if isinstance(now, datetime.datetime):
            now_ts = now.timestamp()
        elif isinstance(now, (int, float)):
            now_ts = float(now)
        else:
            now_ts = time.time()
        current_seconds = (now_ts - float(anchor)) % period_s
    else:
        if isinstance(now, datetime.datetime):
            t = now.time()
        elif isinstance(now, datetime.time):
            t = now
        else:
            t = datetime.datetime.now().time()
        current_seconds = t.hour * 3600 + t.minute * 60 + t.second

    if on_seconds == off_seconds:
        return True
    if on_seconds < off_seconds:
        return on_seconds <= current_seconds < off_seconds
    return current_seconds >= on_seconds or current_seconds < off_seconds


def _coerce_uint(value: Any, *, default: int, lo: int = 0, hi: int = 2**32 - 1) -> int:
    """Coerce a value to a clamped non-negative int; fall back to ``default``."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if result < lo:
        return lo
    if result > hi:
        return hi
    return result


def build_firmware_payload(record: dict[str, Any]) -> dict[str, Any]:
    """Translate a storage record into the JSON body for the firmware's ``POST /config``.

    Maps the node's seconds-based fade and float anchor onto the firmware's
    millisecond and uint32 representations, defaulting anything missing to a
    sane value. Only fields the firmware actually accepts are emitted — extra
    keys in ``record`` are ignored on purpose so this can be fed the full DB
    row.

    Args:
        record: Storage record dict; expected (but not required) keys are
            ``lights_on``, ``lights_off``, ``light_period_minutes``,
            ``light_cycle_anchor``, ``fade_in_seconds``, ``fade_out_seconds``,
            ``max_light``.

    Returns:
        Firmware payload dict ready to be JSON-encoded.
    """
    payload: dict[str, Any] = {
        "lights_on": str(record.get("lights_on") or "00:00"),
        "lights_off": str(record.get("lights_off") or "00:00"),
        "light_period_minutes": _coerce_uint(
            record.get("light_period_minutes"), default=1440, lo=1, hi=65535
        ),
        # anchor=None means wall-clock mode; the firmware uses 0 as the same sentinel.
        "light_cycle_anchor": (
            int(record["light_cycle_anchor"]) if record.get("light_cycle_anchor") else 0
        ),
        "fade_in_ms": _coerce_uint(record.get("fade_in_seconds"), default=1, lo=0)
        * 1000,
        "fade_out_ms": _coerce_uint(record.get("fade_out_seconds"), default=1, lo=0)
        * 1000,
        "max_light": _coerce_uint(record.get("max_light"), default=100, lo=0, hi=100),
    }
    return payload


def schedule_drifted(record: dict[str, Any], telemetry: dict[str, Any]) -> bool:
    """Return True if the firmware's reported schedule disagrees with the storage record.

    Compares only the fields we own. Anything missing from telemetry is treated
    as a drift (the firmware is older or the network response was partial).
    """
    expected = build_firmware_payload(record)
    for field in (
        "lights_on",
        "lights_off",
        "light_period_minutes",
        "light_cycle_anchor",
        "fade_in_ms",
        "fade_out_ms",
        "max_light",
    ):
        if field not in telemetry:
            return True
        if telemetry[field] != expected[field]:
            return True
    return False
