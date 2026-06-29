"""Storage abstraction and a stdlib-only SQLite implementation.

The ABC mirrors the slice of ``ExperimentalDB``'s incubator CRUD that the
node currently exposes — ``addIncubator``, ``updateIncubator``,
``deleteIncubator``, ``getAllIncubators``, ``getIncubatorByName`` — but
normalised into a small focused contract so the node's adapter can wrap
``ExperimentalDB`` while the standalone server uses its own dedicated SQLite
file.

The standalone implementation is intentionally bare: one table, idempotent
``CREATE TABLE IF NOT EXISTS`` plus a tiny ``schema_version`` row, no foreign
keys, no cross-process sharing. Concurrent access is single-server-thread
only — the same model as ``/etc/ethoscope/ethoscope-node.db``.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
import threading
from abc import ABC, abstractmethod
from typing import Any

# A normalised incubator record is just a dict with these keys. Anything missing
# from the dict defaults at the storage layer; anything extra is ignored.
INCUBATOR_FIELDS = (
    "id",
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
)

IncubatorRecord = dict[str, Any]

_UPDATABLE_TEXT_FIELDS = frozenset(
    {"name", "location", "owner", "description", "lights_on", "lights_off"}
)
_UPDATABLE_INT_FIELDS = frozenset(
    {
        "active",
        "light_period_minutes",
        "fade_in_seconds",
        "fade_out_seconds",
        "max_light",
        "crepuscular",
    }
)
_UPDATABLE_NULLABLE_FLOAT_FIELDS = frozenset({"light_cycle_anchor"})
_UPDATABLE_NULLABLE_TEXT_FIELDS = frozenset({"hostname"})


class IncubatorStorage(ABC):
    """Contract for any backend that persists incubator records.

    The node adapter wraps ``ExperimentalDB``; the standalone server uses
    :class:`SQLiteIncubatorStorage`. Both must obey the same return-value
    conventions:

    * ``add`` returns the new row id (>0) or ``-1`` on error.
    * ``update`` / ``delete`` return rows-affected (>=0) or ``-1`` on error.
    * ``get`` returns ``None`` when no row matches.
    """

    @abstractmethod
    def list_all(self, *, active_only: bool = False) -> dict[str, IncubatorRecord]:
        """Return all incubators keyed by name."""

    @abstractmethod
    def get(
        self,
        *,
        name: str | None = None,
        incubator_id: int | None = None,
    ) -> IncubatorRecord | None:
        """Look up one incubator by name or id."""

    @abstractmethod
    def add(self, record: IncubatorRecord) -> int:
        """Insert a new incubator. Returns the new row id or -1 on error."""

    @abstractmethod
    def update(
        self,
        *,
        name: str | None = None,
        incubator_id: int | None = None,
        **fields: Any,
    ) -> int:
        """Patch an existing incubator. Returns rows affected or -1 on error."""

    @abstractmethod
    def delete(
        self,
        *,
        name: str | None = None,
        incubator_id: int | None = None,
    ) -> int:
        """Permanently delete an incubator. Returns rows affected or -1 on error."""


class SQLiteIncubatorStorage(IncubatorStorage):
    """SQLite-file backed storage for the standalone server.

    Manages its own schema and migrations. Safe to instantiate against an
    existing path — schema migrations are idempotent. Uses a single
    threading.RLock to serialise writes from the (single-threaded by default)
    Bottle server.
    """

    SCHEMA_VERSION = 1

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialise(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incubators (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    location TEXT DEFAULT '',
                    owner TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    created TIMESTAMP NOT NULL,
                    active INTEGER DEFAULT 1,
                    lights_on TEXT DEFAULT '',
                    lights_off TEXT DEFAULT '',
                    light_period_minutes INTEGER DEFAULT 1440,
                    light_cycle_anchor REAL,
                    hostname TEXT,
                    fade_in_seconds INTEGER DEFAULT 1,
                    fade_out_seconds INTEGER DEFAULT 1,
                    max_light INTEGER DEFAULT 100,
                    crepuscular INTEGER DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version "
                "(version INTEGER NOT NULL PRIMARY KEY)"
            )
            current = conn.execute(
                "SELECT version FROM schema_version LIMIT 1"
            ).fetchone()
            if current is None:
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (self.SCHEMA_VERSION,),
                )

    # --- helpers -----------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> IncubatorRecord | None:
        if row is None:
            return None
        return dict(row)

    @staticmethod
    def _build_where(
        name: str | None, incubator_id: int | None
    ) -> tuple[str, tuple[Any, ...]]:
        if incubator_id is not None:
            return "id = ?", (int(incubator_id),)
        if name is not None:
            return "name = ?", (name,)
        raise ValueError("Either name or incubator_id must be provided")

    # --- ABC implementation ------------------------------------------------------

    def list_all(self, *, active_only: bool = False) -> dict[str, IncubatorRecord]:
        sql = "SELECT * FROM incubators"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY name"
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql).fetchall()
        return {row["name"]: dict(row) for row in rows}

    def get(
        self,
        *,
        name: str | None = None,
        incubator_id: int | None = None,
    ) -> IncubatorRecord | None:
        where, params = self._build_where(name, incubator_id)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM incubators WHERE {where}", params
            ).fetchone()
        return self._row_to_dict(row)

    def add(self, record: IncubatorRecord) -> int:
        name = record.get("name")
        if not name:
            self._logger.error("Name is required when adding an incubator")
            return -1

        created = record.get("created")
        if created is None:
            created = datetime.datetime.now().timestamp()

        try:
            with self._lock, self._connect() as conn:
                existing = conn.execute(
                    "SELECT id FROM incubators WHERE name = ?", (name,)
                ).fetchone()
                if existing is not None:
                    self._logger.error("Incubator '%s' already exists", name)
                    return -1

                cur = conn.execute(
                    """
                    INSERT INTO incubators (
                        name, location, owner, description, created, active,
                        lights_on, lights_off, light_period_minutes,
                        light_cycle_anchor, hostname,
                        fade_in_seconds, fade_out_seconds, max_light, crepuscular
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        record.get("location", ""),
                        record.get("owner", ""),
                        record.get("description", ""),
                        created,
                        int(record.get("active", 1)),
                        record.get("lights_on", ""),
                        record.get("lights_off", ""),
                        int(record.get("light_period_minutes") or 1440),
                        record.get("light_cycle_anchor"),
                        record.get("hostname"),
                        int(record.get("fade_in_seconds") or 1),
                        int(record.get("fade_out_seconds") or 1),
                        int(record.get("max_light") or 100),
                        1 if int(record.get("crepuscular") or 0) else 0,
                    ),
                )
                return int(cur.lastrowid or -1)
        except sqlite3.Error as e:
            self._logger.error("Error adding incubator %s: %s", name, e)
            return -1

    def update(
        self,
        *,
        name: str | None = None,
        incubator_id: int | None = None,
        **fields: Any,
    ) -> int:
        if not fields:
            return 0
        try:
            where, where_params = self._build_where(name, incubator_id)
        except ValueError as e:
            self._logger.error("update() requires name or incubator_id: %s", e)
            return -1

        set_clauses: list[str] = []
        set_params: list[Any] = []
        for field, value in fields.items():
            if field in _UPDATABLE_TEXT_FIELDS:
                set_clauses.append(f"{field} = ?")
                set_params.append("" if value is None else str(value))
            elif field in _UPDATABLE_INT_FIELDS:
                set_clauses.append(f"{field} = ?")
                set_params.append(int(value))
            elif field in _UPDATABLE_NULLABLE_FLOAT_FIELDS:
                set_clauses.append(f"{field} = ?")
                set_params.append(None if value is None else float(value))
            elif field in _UPDATABLE_NULLABLE_TEXT_FIELDS:
                set_clauses.append(f"{field} = ?")
                set_params.append(None if value is None else str(value))
            elif field == "created":
                set_clauses.append(f"{field} = ?")
                set_params.append(value)
            else:
                self._logger.warning(
                    "Unknown field '%s' in incubator update — skipping", field
                )

        if not set_clauses:
            return 0

        sql = f"UPDATE incubators SET {', '.join(set_clauses)} WHERE {where}"
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute(sql, (*set_params, *where_params))
                return cur.rowcount
        except sqlite3.Error as e:
            self._logger.error("Error updating incubator: %s", e)
            return -1

    def delete(
        self,
        *,
        name: str | None = None,
        incubator_id: int | None = None,
    ) -> int:
        try:
            where, params = self._build_where(name, incubator_id)
        except ValueError as e:
            self._logger.error("delete() requires name or incubator_id: %s", e)
            return -1
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute(f"DELETE FROM incubators WHERE {where}", params)
                return cur.rowcount
        except sqlite3.Error as e:
            self._logger.error("Error deleting incubator: %s", e)
            return -1
