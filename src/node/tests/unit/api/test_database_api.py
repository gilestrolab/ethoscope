"""
Unit tests for Database API endpoints.

Tests database queries for runs, experiments, and cached database information.
"""

import json
import unittest
from unittest.mock import Mock, patch

from ethoscope_node.api.database_api import DatabaseAPI


class TestDatabaseAPI(unittest.TestCase):
    """Test suite for DatabaseAPI class."""

    def setUp(self):
        """Create mock server instance and DatabaseAPI for testing."""
        self.mock_server = Mock()
        self.mock_server.app = Mock()
        self.mock_server.config = {}
        self.mock_server.device_scanner = Mock()
        self.mock_server.sensor_scanner = Mock()
        self.mock_server.database = Mock()
        self.mock_server.results_dir = "/tmp/results"
        self.mock_server.sensors_dir = "/tmp/sensors"
        self.mock_server.roi_templates_dir = "/tmp/templates"
        self.mock_server.tmp_imgs_dir = "/tmp/imgs"
        self.mock_server.devices = {}

        self.api = DatabaseAPI(self.mock_server)

    def test_register_routes(self):
        """Test that all database routes are registered."""
        # Track route registrations
        route_calls = []

        def mock_route(path, method):
            def decorator(func):
                route_calls.append((path, method, func.__name__))
                return func

            return decorator

        self.api.app.route = mock_route

        # Register routes
        self.api.register_routes()

        # Verify all 3 routes were registered
        self.assertEqual(len(route_calls), 3)

        # Check specific routes
        paths = [call[0] for call in route_calls]
        self.assertIn("/runs_list", paths)
        self.assertIn("/experiments_list", paths)
        self.assertIn("/cached_databases/<device_name>", paths)

    def test_runs_list_success(self):
        """Test getting runs list successfully."""
        mock_runs = [
            {"id": 1, "name": "run1", "start_time": "2024-01-01"},
            {"id": 2, "name": "run2", "start_time": "2024-01-02"},
        ]
        self.api.database.getRun.return_value = mock_runs

        result = self.api._runs_list()

        # Should return JSON string
        parsed = json.loads(result)
        self.assertEqual(parsed, mock_runs)
        self.api.database.getRun.assert_called_once_with("all", asdict=True)

    def test_runs_list_database_exception(self):
        """Test runs list handles database exceptions."""
        self.api.database.getRun.side_effect = RuntimeError("Database error")

        result = self.api._runs_list()

        # error_decorator should catch and return error dict
        self.assertIn("error", result)
        self.assertIn("Database error", result["error"])

    def test_experiments_list_success(self):
        """Test getting experiments list successfully."""
        mock_experiments = [
            {"id": 1, "name": "exp1", "description": "Test 1"},
            {"id": 2, "name": "exp2", "description": "Test 2"},
        ]
        self.api.database.getExperiment.return_value = mock_experiments

        result = self.api._experiments_list()

        # Should return JSON string
        parsed = json.loads(result)
        self.assertEqual(parsed, mock_experiments)
        self.api.database.getExperiment.assert_called_once_with("all", asdict=True)

    def test_experiments_list_database_exception(self):
        """Test experiments list handles database exceptions."""
        self.api.database.getExperiment.side_effect = RuntimeError("Database error")

        result = self.api._experiments_list()

        # error_decorator should catch and return error dict
        self.assertIn("error", result)
        self.assertIn("Database error", result["error"])

    def test_cached_databases_with_sqlite(self):
        """Test getting cached databases with SQLite databases."""
        # Setup mock devices with SQLite databases
        self.api.devices = {
            "device1": {
                "name": "test_device",
                "databases": {
                    "SQLite": {
                        "db1.db": {
                            "file_exists": True,
                            "filesize": 50000,  # > 32KB
                            "db_status": "active",
                        },
                        "db2.db": {
                            "file_exists": True,
                            "filesize": 100000,
                            "db_status": "active",
                        },
                    }
                },
            }
        }

        result = self.api._cached_databases("test_device")

        parsed = json.loads(result)
        self.assertEqual(len(parsed), 2)
        # Should be sorted by name (reverse)
        self.assertEqual(parsed[0]["name"], "db2.db")
        self.assertEqual(parsed[0]["type"], "SQLite")
        self.assertEqual(parsed[0]["size"], 100000)
        self.assertEqual(parsed[1]["name"], "db1.db")

    def test_cached_databases_filters_small_sqlite(self):
        """Test that small SQLite databases are filtered out."""
        self.api.devices = {
            "device1": {
                "name": "test_device",
                "databases": {
                    "SQLite": {
                        "small.db": {
                            "file_exists": True,
                            "filesize": 10000,  # < 32KB
                            "db_status": "active",
                        },
                        "large.db": {
                            "file_exists": True,
                            "filesize": 50000,  # > 32KB
                            "db_status": "active",
                        },
                    }
                },
            }
        }

        result = self.api._cached_databases("test_device")

        parsed = json.loads(result)
        # Only large.db should be included
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["name"], "large.db")

    def test_cached_databases_filters_nonexistent_sqlite(self):
        """Test that non-existent SQLite databases are filtered out."""
        self.api.devices = {
            "device1": {
                "name": "test_device",
                "databases": {
                    "SQLite": {
                        "missing.db": {
                            "file_exists": False,
                            "filesize": 50000,
                            "db_status": "missing",
                        },
                        "exists.db": {
                            "file_exists": True,
                            "filesize": 50000,
                            "db_status": "active",
                        },
                    }
                },
            }
        }

        result = self.api._cached_databases("test_device")

        parsed = json.loads(result)
        # Only exists.db should be included
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["name"], "exists.db")

    def test_cached_databases_with_mariadb(self):
        """Test getting cached databases with MariaDB databases."""
        self.api.devices = {
            "device1": {
                "name": "test_device",
                "databases": {
                    "MariaDB": {
                        "maria_db1": {
                            "db_size_bytes": 200000,
                            "db_status": "active",
                        },
                        "maria_db2": {
                            "db_size_bytes": 150000,
                            "db_status": "active",
                        },
                    }
                },
            }
        }

        result = self.api._cached_databases("test_device")

        parsed = json.loads(result)
        self.assertEqual(len(parsed), 2)
        # Should be sorted by name (reverse)
        self.assertEqual(parsed[0]["name"], "maria_db2")
        self.assertEqual(parsed[0]["type"], "MariaDB")
        self.assertEqual(parsed[0]["size"], 150000)
        self.assertEqual(parsed[1]["name"], "maria_db1")

    def test_cached_databases_with_both_types(self):
        """Test getting cached databases with both SQLite and MariaDB."""
        self.api.devices = {
            "device1": {
                "name": "test_device",
                "databases": {
                    "SQLite": {
                        "sqlite_db.db": {
                            "file_exists": True,
                            "filesize": 50000,
                            "db_status": "active",
                        }
                    },
                    "MariaDB": {
                        "maria_db": {
                            "db_size_bytes": 200000,
                            "db_status": "active",
                        }
                    },
                },
            }
        }

        result = self.api._cached_databases("test_device")

        parsed = json.loads(result)
        self.assertEqual(len(parsed), 2)
        # Check both types are present
        types = [db["type"] for db in parsed]
        self.assertIn("SQLite", types)
        self.assertIn("MariaDB", types)

    def test_cached_databases_device_not_found(self):
        """Test getting cached databases when device doesn't exist."""
        self.api.devices = {"device1": {"name": "other_device", "databases": {}}}

        with patch.object(self.api.logger, "warning") as mock_log:
            result = self.api._cached_databases("nonexistent_device")

            parsed = json.loads(result)
            self.assertEqual(parsed, [])
            mock_log.assert_called_once()
            self.assertIn("not found", mock_log.call_args[0][0])

    def test_cached_databases_no_databases(self):
        """Test getting cached databases when device has no databases."""
        self.api.devices = {
            "device1": {
                "name": "test_device",
                "databases": {},  # No databases
            }
        }

        result = self.api._cached_databases("test_device")

        parsed = json.loads(result)
        self.assertEqual(parsed, [])

    def test_cached_databases_exception(self):
        """Test cached databases handles exceptions."""
        # Make devices property raise exception
        self.api.devices = Mock()
        self.api.devices.items.side_effect = RuntimeError("Scanner error")

        with patch.object(self.api.logger, "error") as mock_log:
            result = self.api._cached_databases("test_device")

            # Should return empty list
            parsed = json.loads(result)
            self.assertEqual(parsed, [])
            # Should log error
            mock_log.assert_called_once()

    def test_cached_databases_sorting(self):
        """Test that databases are sorted by name in reverse order."""
        self.api.devices = {
            "device1": {
                "name": "test_device",
                "databases": {
                    "SQLite": {
                        "a_first.db": {
                            "file_exists": True,
                            "filesize": 50000,
                            "db_status": "active",
                        },
                        "z_last.db": {
                            "file_exists": True,
                            "filesize": 50000,
                            "db_status": "active",
                        },
                        "m_middle.db": {
                            "file_exists": True,
                            "filesize": 50000,
                            "db_status": "active",
                        },
                    }
                },
            }
        }

        result = self.api._cached_databases("test_device")

        parsed = json.loads(result)
        self.assertEqual(len(parsed), 3)
        # Should be in reverse alphabetical order
        self.assertEqual(parsed[0]["name"], "z_last.db")
        self.assertEqual(parsed[1]["name"], "m_middle.db")
        self.assertEqual(parsed[2]["name"], "a_first.db")


if __name__ == "__main__":
    unittest.main()
