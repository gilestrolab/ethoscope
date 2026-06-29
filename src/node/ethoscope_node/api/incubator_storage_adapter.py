"""ExperimentalDB-backed adapter for the incubators subpackage.

Bridges the ``IncubatorStorage`` ABC defined in
``ethoscope_node.incubators.storage`` to the existing ``ExperimentalDB`` CRUD
methods. This is the *only* place the node-side incubator stack touches
ExperimentalDB — the routes, scanner, firmware client, schedule algorithm,
and reconciler all work against the ABC and therefore against this adapter
identically to the standalone SQLite backend.
"""

from __future__ import annotations

from typing import Any

from ethoscope_node.incubators.storage import IncubatorStorage

# Subset of fields ExperimentalDB.addIncubator accepts. Anything outside this
# set is silently dropped before the call (the storage tests assert the same
# behaviour for the standalone SQLite backend).
_ADD_FIELDS = {
    "name",
    "location",
    "owner",
    "description",
    "created",
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
}


class ExperimentalDBIncubatorStorage(IncubatorStorage):
    """Wraps ``ExperimentalDB`` so the incubator routes can use it as storage."""

    def __init__(self, db):
        self._db = db

    def list_all(self, *, active_only: bool = False) -> dict[str, dict[str, Any]]:
        return self._db.getAllIncubators(active_only=active_only, asdict=True) or {}

    def get(
        self,
        *,
        name: str | None = None,
        incubator_id: int | None = None,
    ) -> dict[str, Any] | None:
        if incubator_id is not None:
            row = self._db.getIncubatorById(int(incubator_id), asdict=True)
        elif name is not None:
            row = self._db.getIncubatorByName(name, asdict=True)
        else:
            raise ValueError("Either name or incubator_id must be provided")
        return row if row else None

    def add(self, record: dict[str, Any]) -> int:
        kwargs = {k: v for k, v in record.items() if k in _ADD_FIELDS}
        if "name" not in kwargs:
            return -1
        return int(self._db.addIncubator(**kwargs))

    def update(
        self,
        *,
        name: str | None = None,
        incubator_id: int | None = None,
        **fields: Any,
    ) -> int:
        return int(
            self._db.updateIncubator(name=name, incubator_id=incubator_id, **fields)
        )

    def delete(
        self,
        *,
        name: str | None = None,
        incubator_id: int | None = None,
    ) -> int:
        return int(self._db.deleteIncubator(name=name, incubator_id=incubator_id))
