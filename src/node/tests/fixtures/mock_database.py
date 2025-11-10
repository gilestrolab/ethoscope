"""
Mock database utilities for testing.

This module provides mock implementations of database connections and
operations for use in tests.
"""

import datetime
import json
import os
import sqlite3
import tempfile
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from unittest.mock import MagicMock
from unittest.mock import Mock


class MockDatabase:
    """Mock implementation of database operations."""

    def __init__(self):
        """Initialize mock database."""
        self.connected = False
        self.data = {}
        self.queries = []
        self.last_insert_id = 0

    def connect(self):
        """Mock database connection."""
        self.connected = True
        return True

    def disconnect(self):
        """Mock database disconnection."""
        self.connected = False
        return True

    def execute(self, query: str, params: Optional[Tuple] = None) -> bool:
        """Mock query execution."""
        self.queries.append({"query": query, "params": params})

        # Simulate INSERT operations
        if query.strip().upper().startswith("INSERT"):
            self.last_insert_id += 1
            return True

        # Simulate other operations
        return True

    def fetchone(self) -> Optional[Dict[str, Any]]:
        """Mock fetchone operation."""
        # Return mock data based on query patterns
        if self.queries:
            last_query = self.queries[-1]["query"].upper()
            if "SELECT" in last_query:
                if "EXPERIMENTS" in last_query:
                    return {
                        "id": 1,
                        "name": "Test Experiment",
                        "start_time": datetime.datetime.now().isoformat(),
                        "end_time": None,
                        "device_id": "test_device_001",
                    }
                elif "DEVICES" in last_query:
                    return {
                        "id": "test_device_001",
                        "name": "Test Device",
                        "ip": "192.168.1.100",
                        "status": "running",
                        "last_seen": datetime.datetime.now().isoformat(),
                    }
        return None

    def fetchall(self) -> List[Dict[str, Any]]:
        """Mock fetchall operation."""
        # Return mock data based on query patterns
        if self.queries:
            last_query = self.queries[-1]["query"].upper()
            if "SELECT" in last_query:
                if "EXPERIMENTS" in last_query:
                    return [
                        {
                            "id": 1,
                            "name": "Test Experiment 1",
                            "start_time": datetime.datetime.now().isoformat(),
                            "end_time": None,
                            "device_id": "test_device_001",
                        },
                        {
                            "id": 2,
                            "name": "Test Experiment 2",
                            "start_time": datetime.datetime.now().isoformat(),
                            "end_time": datetime.datetime.now().isoformat(),
                            "device_id": "test_device_002",
                        },
                    ]
                elif "DEVICES" in last_query:
                    return [
                        {
                            "id": "test_device_001",
                            "name": "Test Device 1",
                            "ip": "192.168.1.100",
                            "status": "running",
                            "last_seen": datetime.datetime.now().isoformat(),
                        },
                        {
                            "id": "test_device_002",
                            "name": "Test Device 2",
                            "ip": "192.168.1.101",
                            "status": "stopped",
                            "last_seen": datetime.datetime.now().isoformat(),
                        },
                    ]
        return []

    def commit(self):
        """Mock commit operation."""
        return True

    def rollback(self):
        """Mock rollback operation."""
        return True

    def get_queries(self) -> List[Dict[str, Any]]:
        """Get list of executed queries."""
        return self.queries.copy()

    def clear_queries(self):
        """Clear query history."""
        self.queries = []

    def set_mock_data(self, table: str, data: List[Dict[str, Any]]):
        """Set mock data for a specific table."""
        self.data[table] = data

    def get_mock_data(self, table: str) -> List[Dict[str, Any]]:
        """Get mock data for a specific table."""
        return self.data.get(table, [])


class MockSQLiteDatabase:
    """Mock implementation using temporary SQLite database."""

    def __init__(self):
        """Initialize mock SQLite database."""
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_file.close()
        self.db_path = self.temp_file.name
        self.connection = None

    def connect(self):
        """Connect to temporary database."""
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self._create_test_tables()
        return self.connection

    def disconnect(self):
        """Disconnect from database."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def _create_test_tables(self):
        """Create test tables."""
        cursor = self.connection.cursor()

        # Create experiments table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                start_time TEXT,
                end_time TEXT,
                device_id TEXT,
                config TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Create devices table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                ip TEXT,
                port INTEGER,
                status TEXT,
                last_seen TEXT,
                hardware_version TEXT,
                software_version TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Create tracking_data table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tracking_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER,
                device_id TEXT,
                timestamp TEXT,
                roi_id INTEGER,
                x REAL,
                y REAL,
                width REAL,
                height REAL,
                angle REAL,
                area REAL,
                FOREIGN KEY (experiment_id) REFERENCES experiments (id)
            )
        """
        )

        self.connection.commit()

    def insert_test_data(self):
        """Insert test data into database."""
        cursor = self.connection.cursor()

        # Insert test experiments
        cursor.execute(
            """
            INSERT INTO experiments (name, description, start_time, device_id, config)
            VALUES (?, ?, ?, ?, ?)
        """,
            (
                "Test Experiment",
                "Test experiment for unit testing",
                datetime.datetime.now().isoformat(),
                "test_device_001",
                json.dumps({"tracking": True, "video": False}),
            ),
        )

        # Insert test devices
        cursor.execute(
            """
            INSERT INTO devices (id, name, ip, port, status, last_seen, hardware_version, software_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "test_device_001",
                "Test Device 1",
                "192.168.1.100",
                9000,
                "running",
                datetime.datetime.now().isoformat(),
                "1.0",
                "1.0.0",
            ),
        )

        # Insert test tracking data
        experiment_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO tracking_data (experiment_id, device_id, timestamp, roi_id, x, y, width, height, angle, area)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                1,
                "test_device_001",
                datetime.datetime.now().isoformat(),
                1,
                100.5,
                200.3,
                50,
                30,
                45.0,
                1500,
            ),
        )

        self.connection.commit()

    def cleanup(self):
        """Clean up temporary database."""
        self.disconnect()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.cleanup()


def create_mock_database_with_data() -> MockDatabase:
    """Create a mock database with sample data."""
    db = MockDatabase()

    # Add sample experiments
    db.set_mock_data(
        "experiments",
        [
            {
                "id": 1,
                "name": "Test Experiment 1",
                "description": "First test experiment",
                "start_time": datetime.datetime.now().isoformat(),
                "end_time": None,
                "device_id": "test_device_001",
                "config": json.dumps({"tracking": True, "video": False}),
            },
            {
                "id": 2,
                "name": "Test Experiment 2",
                "description": "Second test experiment",
                "start_time": datetime.datetime.now().isoformat(),
                "end_time": datetime.datetime.now().isoformat(),
                "device_id": "test_device_002",
                "config": json.dumps({"tracking": True, "video": True}),
            },
        ],
    )

    # Add sample devices
    db.set_mock_data(
        "devices",
        [
            {
                "id": "test_device_001",
                "name": "Test Device 1",
                "ip": "192.168.1.100",
                "port": 9000,
                "status": "running",
                "last_seen": datetime.datetime.now().isoformat(),
                "hardware_version": "1.0",
                "software_version": "1.0.0",
            },
            {
                "id": "test_device_002",
                "name": "Test Device 2",
                "ip": "192.168.1.101",
                "port": 9000,
                "status": "stopped",
                "last_seen": datetime.datetime.now().isoformat(),
                "hardware_version": "1.0",
                "software_version": "1.0.0",
            },
        ],
    )

    return db
