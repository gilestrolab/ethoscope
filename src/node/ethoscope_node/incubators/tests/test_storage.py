"""Tests for the SQLite incubator storage backend."""

from __future__ import annotations

import os

import pytest

from ethoscope_node.incubators.storage import SQLiteIncubatorStorage


@pytest.fixture
def storage(tmp_path):
    return SQLiteIncubatorStorage(str(tmp_path / "inc.db"))


class TestSchema:
    def test_creates_file_and_table_on_first_use(self, tmp_path):
        db_path = str(tmp_path / "first.db")
        SQLiteIncubatorStorage(db_path)
        assert os.path.exists(db_path)

    def test_idempotent_on_repeated_init(self, tmp_path):
        path = str(tmp_path / "twice.db")
        SQLiteIncubatorStorage(path)
        # A second init against the same file must not raise.
        storage = SQLiteIncubatorStorage(path)
        assert storage.list_all() == {}

    def test_records_schema_version(self, tmp_path):
        import sqlite3

        path = str(tmp_path / "ver.db")
        SQLiteIncubatorStorage(path)
        conn = sqlite3.connect(path)
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        assert row[0] == SQLiteIncubatorStorage.SCHEMA_VERSION


class TestAdd:
    def test_minimal_record(self, storage):
        new_id = storage.add({"name": "Inc1"})
        assert new_id > 0
        rec = storage.get(name="Inc1")
        assert rec["name"] == "Inc1"
        assert rec["active"] == 1
        assert rec["light_period_minutes"] == 1440
        assert rec["fade_in_seconds"] == 1
        assert rec["fade_out_seconds"] == 1
        assert rec["max_light"] == 100

    def test_full_record_round_trip(self, storage):
        storage.add(
            {
                "name": "Inc2",
                "location": "Room A",
                "owner": "Alice",
                "description": "Top shelf",
                "active": 1,
                "lights_on": "09:00",
                "lights_off": "21:00",
                "light_period_minutes": 1260,
                "light_cycle_anchor": 1_700_000_000.0,
                "hostname": "incubator-2",
                "fade_in_seconds": 30,
                "fade_out_seconds": 60,
                "max_light": 75,
            }
        )
        rec = storage.get(name="Inc2")
        assert rec["location"] == "Room A"
        assert rec["light_period_minutes"] == 1260
        assert rec["light_cycle_anchor"] == pytest.approx(1_700_000_000.0)
        assert rec["hostname"] == "incubator-2"
        assert rec["fade_in_seconds"] == 30
        assert rec["fade_out_seconds"] == 60
        assert rec["max_light"] == 75

    def test_duplicate_name_returns_minus_one(self, storage):
        storage.add({"name": "Inc1"})
        assert storage.add({"name": "Inc1"}) == -1

    def test_missing_name_returns_minus_one(self, storage):
        assert storage.add({}) == -1
        assert storage.add({"name": ""}) == -1

    def test_handles_quotes_in_text_fields(self, storage):
        storage.add({"name": "O'Brien's box", "description": "won't break"})
        rec = storage.get(name="O'Brien's box")
        assert rec["description"] == "won't break"


class TestUpdate:
    def test_update_text_field(self, storage):
        storage.add({"name": "Inc1", "location": "old"})
        assert storage.update(name="Inc1", location="new") == 1
        assert storage.get(name="Inc1")["location"] == "new"

    def test_update_period_and_anchor(self, storage):
        storage.add({"name": "Inc1"})
        storage.update(name="Inc1", light_period_minutes=1260)
        storage.update(name="Inc1", light_cycle_anchor=1_700_000_000.0)
        rec = storage.get(name="Inc1")
        assert rec["light_period_minutes"] == 1260
        assert rec["light_cycle_anchor"] == pytest.approx(1_700_000_000.0)

    def test_clear_anchor_with_explicit_none(self, storage):
        storage.add({"name": "Inc1", "light_cycle_anchor": 1_700_000_000.0})
        storage.update(name="Inc1", light_cycle_anchor=None)
        assert storage.get(name="Inc1")["light_cycle_anchor"] is None

    def test_unbind_hostname_with_explicit_none(self, storage):
        storage.add({"name": "Inc1", "hostname": "incubator-1"})
        storage.update(name="Inc1", hostname=None)
        assert storage.get(name="Inc1")["hostname"] is None

    def test_update_fade_seconds(self, storage):
        storage.add({"name": "Inc1"})
        storage.update(name="Inc1", fade_in_seconds=30, fade_out_seconds=60)
        rec = storage.get(name="Inc1")
        assert rec["fade_in_seconds"] == 30
        assert rec["fade_out_seconds"] == 60

    def test_unknown_field_is_ignored_but_recorded(self, storage, caplog):
        import logging

        storage.add({"name": "Inc1"})
        with caplog.at_level(logging.WARNING):
            storage.update(name="Inc1", surprising_field="x")
        assert any("Unknown field" in m for m in caplog.messages)

    def test_no_fields_is_noop(self, storage):
        storage.add({"name": "Inc1"})
        assert storage.update(name="Inc1") == 0

    def test_requires_name_or_id(self, storage):
        assert storage.update(location="x") == -1

    def test_update_by_id(self, storage):
        new_id = storage.add({"name": "Inc1"})
        assert storage.update(incubator_id=new_id, location="X") == 1


class TestGetAndListAll:
    def test_get_returns_none_when_missing(self, storage):
        assert storage.get(name="nope") is None
        assert storage.get(incubator_id=9999) is None

    def test_list_all_keyed_by_name(self, storage):
        storage.add({"name": "Alpha"})
        storage.add({"name": "Beta", "active": 0})
        all_ = storage.list_all()
        assert set(all_.keys()) == {"Alpha", "Beta"}

    def test_list_active_only(self, storage):
        storage.add({"name": "Alpha"})
        storage.add({"name": "Beta", "active": 0})
        assert set(storage.list_all(active_only=True).keys()) == {"Alpha"}


class TestDelete:
    def test_delete_existing(self, storage):
        storage.add({"name": "Inc1"})
        assert storage.delete(name="Inc1") == 1
        assert storage.get(name="Inc1") is None

    def test_delete_by_id(self, storage):
        new_id = storage.add({"name": "Inc1"})
        assert storage.delete(incubator_id=new_id) == 1

    def test_delete_missing_returns_zero(self, storage):
        assert storage.delete(name="nope") == 0

    def test_requires_name_or_id(self, storage):
        assert storage.delete() == -1
