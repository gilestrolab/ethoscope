"""Where an incubator physically sits — parent/child rules.

A *virtual* incubator is a short-lived "shoe box" used to fragment a light
regime for a subset of animals. Unlike a normal or smart incubator it is not
a box that stands on its own: it is normally placed *inside* a proper
incubator, so its record on its own does not say where the animals actually
are. That is what a parent is for.

The rule enforced here is deliberately small:

* only a virtual incubator has a parent; normal/smart records store ``''``;
* a parent is either the name of a **physical** (normal or smart) incubator,
  or the literal sentinel :data:`ROOM` meaning "standing in the open room";
* absent or unrecognised input defaults to :data:`ROOM`, so a virtual
  incubator always declares where it is.

Because parents must be physical, the hierarchy is at most one level deep and
cycles are impossible by construction.

Both write paths — the node's ``setup_api`` (ExperimentalDB) and the
standalone server's ``IncubatorRoutes`` (storage ABC) — go through
:func:`validate_parent`, so the two deployments cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Sentinel parent: the virtual box sits in the open room, not inside another
# incubator. Stored verbatim so a plain `SELECT parent FROM incubators` reads
# as the user set it. (An incubator literally *named* "Room" resolves to the
# same thing, which is what the user meant anyway.)
ROOM = "Room"

VIRTUAL = "virtual"
PHYSICAL_TYPES = ("normal", "smart")

#: Callable resolving an incubator name to its record (or None if unknown).
Lookup = Callable[[str], "dict[str, Any] | None"]


def normalise_type(value: Any) -> str:
    """Return a known incubator category, defaulting to 'normal'."""
    candidate = str(value or "").strip().lower()
    return candidate if candidate in (*PHYSICAL_TYPES, VIRTUAL) else "normal"


def is_virtual(record: dict[str, Any] | None) -> bool:
    """True when the record is a virtual "shoe box"."""
    return bool(record) and normalise_type(record.get("type")) == VIRTUAL


def is_room(parent: Any) -> bool:
    """True when the parent value means "no enclosing incubator"."""
    name = str(parent or "").strip()
    return not name or name.casefold() == ROOM.casefold()


def validate_parent(
    requested: Any,
    *,
    incubator_type: Any,
    self_name: str | None,
    lookup: Lookup,
) -> tuple[str, str | None]:
    """Resolve the parent to persist for an incubator.

    Args:
        requested (Any): Parent name as supplied by the caller. Empty, None
            or "Room" (any case) all mean the open room.
        incubator_type (Any): The category the record will have after the
            write — only 'virtual' records carry a parent.
        self_name (str | None): Name of the record being written, used to
            reject self-parenting.
        lookup (Lookup): Resolves an incubator name to its record.

    Returns:
        tuple[str, str | None]: The parent to store and an error message.
        The stored value falls back to :data:`ROOM` whenever an error is
        returned, so a lenient caller may ignore the message and still write
        a coherent record. Non-virtual records always resolve to ``''``.
    """
    if normalise_type(incubator_type) != VIRTUAL:
        return "", None

    name = str(requested or "").strip()
    if is_room(name):
        return ROOM, None

    if self_name and name == str(self_name).strip():
        return ROOM, f"'{name}' cannot be its own parent"

    parent = lookup(name)
    if not parent:
        return ROOM, f"There is no incubator named '{name}' to use as a parent"

    if is_virtual(parent):
        return ROOM, (
            f"'{name}' is itself a virtual incubator — a virtual incubator "
            "must sit inside a physical one, or in the Room"
        )

    return str(parent.get("name") or name), None


def children_of(records: dict[str, dict[str, Any]], parent_name: str) -> list[str]:
    """Names of the virtual incubators currently parented to ``parent_name``.

    Args:
        records (dict[str, dict]): All incubator records keyed by name.
        parent_name (str): The parent to look for.

    Returns:
        list[str]: Names of the virtual children (empty when there are none).
    """
    target = str(parent_name or "").strip()
    if not target or is_room(target):
        return []
    return [
        record.get("name") or key
        for key, record in (records or {}).items()
        if is_virtual(record) and str(record.get("parent") or "").strip() == target
    ]


def effective_location(record: dict[str, Any], lookup: Lookup) -> str:
    """Human-readable answer to "where is this incubator?".

    Args:
        record (dict): The incubator record.
        lookup (Lookup): Resolves an incubator name to its record.

    Returns:
        str: For a parented virtual box, the parent name followed by the
        parent's own location when it has one. Otherwise the record's own
        location, or :data:`ROOM` when it is blank.
    """
    own_location = str(record.get("location") or "").strip()
    if not is_virtual(record):
        return own_location

    parent_name = str(record.get("parent") or "").strip()
    if is_room(parent_name):
        return own_location or ROOM

    parent = lookup(parent_name) or {}
    parent_location = str(parent.get("location") or "").strip()
    return f"{parent_name} ({parent_location})" if parent_location else parent_name
