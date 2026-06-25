"""Unit tests for the bootstrap path resolver (ethoscope_node.utils.paths)."""

import json
import os
import sqlite3
import unittest
from unittest.mock import patch

from ethoscope_node.utils import paths


class TestResolveDataDir(unittest.TestCase):
    def test_explicit_wins(self):
        with patch.dict(os.environ, {"ETHOSCOPE_DATA_DIR": "/from/env"}):
            self.assertEqual(paths.resolve_data_dir("/explicit"), "/explicit")

    def test_env_used_when_no_explicit(self):
        with patch.dict(os.environ, {"ETHOSCOPE_DATA_DIR": "/from/env"}):
            self.assertEqual(paths.resolve_data_dir(), "/from/env")

    def test_default_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(paths.resolve_data_dir(), "/ethoscope_data")


class TestResolveConfigDir(unittest.TestCase):
    def test_explicit_wins(self):
        with patch.dict(os.environ, {"ETHOSCOPE_CONFIG_DIR": "/from/env"}):
            self.assertEqual(paths.resolve_config_dir("/explicit"), "/explicit")

    def test_env_used_when_no_explicit(self):
        with patch.dict(os.environ, {"ETHOSCOPE_CONFIG_DIR": "/from/env/config"}):
            self.assertEqual(paths.resolve_config_dir(), "/from/env/config")

    def test_derived_from_data_dir_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(paths.resolve_config_dir(), "/ethoscope_data/config")

    def test_derived_from_explicit_data_dir(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                paths.resolve_config_dir(data_dir="/mnt/data"), "/mnt/data/config"
            )

    def test_derived_from_env_data_dir(self):
        with patch.dict(os.environ, {"ETHOSCOPE_DATA_DIR": "/mnt/data"}, clear=True):
            self.assertEqual(paths.resolve_config_dir(), "/mnt/data/config")


class TestWriteBootstrapEnv(unittest.TestCase):
    def test_writes_both_pointers(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            env_file = os.path.join(tmp, "subdir", "environment")
            paths.write_bootstrap_env("/data", "/data/config", env_file=env_file)

            with open(env_file) as f:
                content = f.read()
            self.assertIn("ETHOSCOPE_DATA_DIR=/data", content)
            self.assertIn("ETHOSCOPE_CONFIG_DIR=/data/config", content)


class TestMigrateConfigDir(unittest.TestCase):
    def _make(self, tmp, name, content="x"):
        path = os.path.join(tmp, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_moves_files_and_excludes_env(self):
        import tempfile

        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new:
            self._make(old, "ethoscope.conf")
            self._make(old, "ethoscope-node.db")
            self._make(old, "environment")  # bootstrap anchor, must stay
            os.makedirs(os.path.join(old, "keys"))
            self._make(os.path.join(old, "keys"), "id_rsa")

            moved = paths.migrate_config_dir(old, new)

            self.assertIn("ethoscope.conf", moved)
            self.assertIn("ethoscope-node.db", moved)
            self.assertIn("keys", moved)
            self.assertNotIn("environment", moved)  # excluded
            self.assertTrue(os.path.exists(os.path.join(new, "ethoscope.conf")))
            self.assertTrue(os.path.exists(os.path.join(new, "keys", "id_rsa")))
            self.assertTrue(os.path.exists(os.path.join(old, "environment")))

    def test_does_not_overwrite_existing_destination(self):
        import tempfile

        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new:
            self._make(old, "ethoscope.conf", "OLD")
            self._make(new, "ethoscope.conf", "NEW")

            moved = paths.migrate_config_dir(old, new)

            self.assertNotIn("ethoscope.conf", moved)
            with open(os.path.join(new, "ethoscope.conf")) as f:
                self.assertEqual(f.read(), "NEW")  # destination preserved

    def test_same_dir_is_noop(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self._make(tmp, "ethoscope.conf")
            self.assertEqual(paths.migrate_config_dir(tmp, tmp), [])

    def test_missing_source_is_noop(self):
        self.assertEqual(
            paths.migrate_config_dir("/nonexistent/old", "/nonexistent/new"), []
        )


class TestMigrateLegacyConfigDir(unittest.TestCase):
    def _make(self, tmp, name, content="x"):
        path = os.path.join(tmp, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_migrates_existing_legacy_config(self):
        import tempfile

        with (
            tempfile.TemporaryDirectory() as legacy,
            tempfile.TemporaryDirectory() as new,
        ):
            self._make(legacy, "ethoscope.conf")
            self._make(legacy, "ethoscope-node.db")  # users gate the wizard
            self._make(legacy, "environment")  # bootstrap anchor, must stay

            moved = paths.migrate_legacy_config_dir(new, legacy_dir=legacy)

            self.assertIn("ethoscope.conf", moved)
            self.assertIn("ethoscope-node.db", moved)
            self.assertNotIn("environment", moved)
            self.assertTrue(os.path.exists(os.path.join(new, "ethoscope.conf")))
            self.assertTrue(os.path.exists(os.path.join(new, "ethoscope-node.db")))
            self.assertTrue(os.path.exists(os.path.join(legacy, "environment")))

    def test_noop_when_legacy_has_no_config(self):
        import tempfile

        # Legacy dir exists (e.g. only the bootstrap env file) but was never a
        # config dir: nothing to migrate.
        with (
            tempfile.TemporaryDirectory() as legacy,
            tempfile.TemporaryDirectory() as new,
        ):
            self._make(legacy, "environment")
            self.assertEqual(
                paths.migrate_legacy_config_dir(new, legacy_dir=legacy), []
            )

    def test_noop_when_new_dir_already_configured(self):
        import tempfile

        # "Configured" means: real completed-wizard config JSON. Auto-stubs are
        # not enough — see test_migrates_over_auto_stub_config below.
        with (
            tempfile.TemporaryDirectory() as legacy,
            tempfile.TemporaryDirectory() as new,
        ):
            self._make(legacy, "ethoscope.conf", '{"setup": {"completed": true}}')
            current = json.dumps({"setup": {"completed": True}, "marker": "CURRENT"})
            self._make(new, "ethoscope.conf", current)

            self.assertEqual(
                paths.migrate_legacy_config_dir(new, legacy_dir=legacy), []
            )
            with open(os.path.join(new, "ethoscope.conf")) as f:
                self.assertEqual(f.read(), current)  # untouched

    def test_migrates_over_auto_stub_config(self):
        """Issue #221: the new dir already holds the auto-init stub written by
        EthoscopeConfiguration on first boot. That stub must not block the
        legacy migration — otherwise the operator's old config is stranded."""
        import tempfile

        with (
            tempfile.TemporaryDirectory() as legacy,
            tempfile.TemporaryDirectory() as new,
        ):
            # Legacy config — the one the user actually finished the wizard with.
            legacy_conf = json.dumps({"setup": {"completed": True}, "marker": "LEGACY"})
            self._make(legacy, "ethoscope.conf", legacy_conf)
            self._make(legacy, "ethoscope-node.db")  # real user DB carried over
            # New dir holds only the stubs the node wrote on first boot post-upgrade.
            stub_conf = json.dumps({"setup": {"completed": False}})
            self._make(new, "ethoscope.conf", stub_conf)
            # Empty SQLite stub (no users) — what ExperimentalDB() creates.
            stub_db = os.path.join(new, "ethoscope-node.db")
            conn = sqlite3.connect(stub_db)
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
            conn.commit()
            conn.close()

            moved = paths.migrate_legacy_config_dir(new, legacy_dir=legacy)

            self.assertIn("ethoscope.conf", moved)
            self.assertIn("ethoscope-node.db", moved)
            with open(os.path.join(new, "ethoscope.conf")) as f:
                self.assertEqual(json.loads(f.read())["marker"], "LEGACY")

    def test_preserves_new_dir_db_with_real_users(self):
        """If the user DB at the destination already has rows, never trample it
        — even when the config itself is just a stub. Losing accounts in
        flight would be worse than re-running the wizard."""
        import tempfile

        with (
            tempfile.TemporaryDirectory() as legacy,
            tempfile.TemporaryDirectory() as new,
        ):
            self._make(
                legacy, "ethoscope.conf", json.dumps({"setup": {"completed": True}})
            )
            self._make(legacy, "ethoscope-node.db", "LEGACY_DB")
            self._make(
                new, "ethoscope.conf", json.dumps({"setup": {"completed": False}})
            )
            # New-dir DB has one real user — must not be replaced.
            db_path = os.path.join(new, "ethoscope-node.db")
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO users (name) VALUES ('alice')")
            conn.commit()
            conn.close()

            moved = paths.migrate_legacy_config_dir(new, legacy_dir=legacy)

            self.assertNotIn("ethoscope-node.db", moved)
            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT name FROM users").fetchone()
            conn.close()
            self.assertEqual(row[0], "alice")

    def test_noop_when_new_dir_equals_legacy(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self._make(tmp, "ethoscope.conf")
            self.assertEqual(paths.migrate_legacy_config_dir(tmp, legacy_dir=tmp), [])

    def test_noop_when_legacy_missing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as new:
            self.assertEqual(
                paths.migrate_legacy_config_dir(new, legacy_dir="/nonexistent/etc"),
                [],
            )


if __name__ == "__main__":
    unittest.main()
