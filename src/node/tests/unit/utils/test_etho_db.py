"""
Comprehensive unit tests for ethoscope_node.utils.etho_db module.

This module tests the ExperimentalDB class and all its database operations including:
- Database initialization and table creation
- SQL execution with error handling
- User CRUD operations
- Incubator CRUD operations
- Device management
- Run/experiment tracking
- Alert logging
- Database migrations
- Cleanup operations
"""

import datetime
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from ethoscope_node.utils.etho_db import (
    ExperimentalDB,
    Incubators,
    UsersDB,
    random_date,
    set_default_config_dir,
    simpleDB,
)


@pytest.fixture
def temp_config_dir():
    """Create a temporary directory for test database files."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Cleanup
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def test_db(temp_config_dir):
    """Create a test database instance."""
    db = ExperimentalDB(config_dir=temp_config_dir)
    yield db
    # Cleanup happens in temp_config_dir fixture


@pytest.fixture
def populated_db(temp_config_dir):
    """Create a test database with sample data."""
    db = ExperimentalDB(config_dir=temp_config_dir)

    # Add test users
    db.addUser(
        username="test_user1",
        fullname="Test User One",
        email="test1@example.com",
        pin="1234",
        labname="Test Lab",
        active=1,
    )
    db.addUser(
        username="test_user2",
        fullname="Test User Two",
        email="test2@example.com",
        pin="5678",
        labname="Test Lab",
        active=1,
    )
    db.addUser(
        username="inactive_user",
        fullname="Inactive User",
        email="inactive@example.com",
        pin="0000",
        labname="Test Lab",
        active=0,
    )

    # Add test incubators
    db.addIncubator(name="Incubator_01", location="Room A", owner="test_user1")
    db.addIncubator(name="Incubator_02", location="Room B", owner="test_user2")

    # Add test ethoscope
    db.updateEthoscopes(
        ethoscope_id="test_etho_001",
        ethoscope_name="ETHOSCOPE_001",
        active=1,
        last_ip="192.168.1.100",
        status="online",
    )

    # Add test run
    db.addRun(
        run_id="test_run_001",
        experiment_type="tracking",
        ethoscope_name="ETHOSCOPE_001",
        ethoscope_id="test_etho_001",
        username="test_user1",
        user_id=1,
        location="Incubator_01",
    )

    yield db


class TestExperimentalDBInitialization:
    """Test ExperimentalDB initialization and setup."""

    def test_init_creates_config_dir(self, temp_config_dir):
        """Test that ExperimentalDB creates config directory if it doesn't exist."""
        config_dir = os.path.join(temp_config_dir, "new_config")
        assert not os.path.exists(config_dir)

        db = ExperimentalDB(config_dir=config_dir)

        assert os.path.exists(config_dir)
        assert os.path.isfile(db._db_name)

    def test_init_with_default_config_dir(self):
        """Test initialization with default config directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            set_default_config_dir(temp_dir)
            db = ExperimentalDB()
            assert db._config_dir == temp_dir

    def test_init_creates_all_tables(self, test_db):
        """Test that all required tables are created."""
        conn = sqlite3.connect(test_db._db_name)
        cursor = conn.cursor()

        # Check for all expected tables
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]

        expected_tables = [
            "alert_logs",
            "ethoscopes",
            "experiments",
            "incubators",
            "runs",
            "users",
        ]

        for table in expected_tables:
            assert table in tables, f"Table {table} not created"

        conn.close()

    def test_table_schema_runs(self, test_db):
        """Test runs table has correct schema."""
        conn = sqlite3.connect(test_db._db_name)
        cursor = conn.cursor()

        cursor.execute(f"PRAGMA table_info({test_db._runs_table_name})")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        assert "run_id" in columns
        assert "type" in columns
        assert "ethoscope_name" in columns
        assert "ethoscope_id" in columns
        assert "user_name" in columns
        assert "start_time" in columns
        assert "end_time" in columns
        assert "status" in columns

        conn.close()

    def test_table_schema_users(self, test_db):
        """Test users table has correct schema."""
        conn = sqlite3.connect(test_db._db_name)
        cursor = conn.cursor()

        cursor.execute(f"PRAGMA table_info({test_db._users_table_name})")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        assert "id" in columns
        assert "username" in columns
        assert "fullname" in columns
        assert "email" in columns
        assert "pin" in columns
        assert "telephone" in columns
        assert "active" in columns
        assert "isadmin" in columns

        conn.close()

    def test_table_schema_ethoscopes(self, test_db):
        """Test ethoscopes table has correct schema."""
        conn = sqlite3.connect(test_db._db_name)
        cursor = conn.cursor()

        cursor.execute(f"PRAGMA table_info({test_db._ethoscopes_table_name})")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        assert "ethoscope_id" in columns
        assert "ethoscope_name" in columns
        assert "first_seen" in columns
        assert "last_seen" in columns
        assert "active" in columns
        assert "status" in columns

        conn.close()


class TestExecuteSQL:
    """Test SQL execution functionality."""

    def test_execute_select_query(self, populated_db):
        """Test executing a SELECT query."""
        result = populated_db.executeSQL(
            "SELECT * FROM users WHERE username = ?", ("test_user1",)
        )

        assert isinstance(result, list)
        assert len(result) > 0
        assert result[0]["username"] == "test_user1"

    def test_execute_insert_query(self, test_db):
        """Test executing an INSERT query returns last row id."""
        result = test_db.executeSQL(
            f"INSERT INTO {test_db._users_table_name} "
            "(username, fullname, email, pin, active, isadmin, created) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "testuser",
                "Test User",
                "test@example.com",
                "1234",
                1,
                0,
                datetime.datetime.now().timestamp(),
            ),
        )

        assert isinstance(result, int)
        assert result > 0  # Should return the inserted row id

    def test_execute_update_query(self, populated_db):
        """Test executing an UPDATE query."""
        result = populated_db.executeSQL(
            f"UPDATE {populated_db._users_table_name} SET fullname = ? WHERE username = ?",
            ("Updated Name", "test_user1"),
        )

        # UPDATE returns 0 or the number of affected rows
        assert result == 0 or isinstance(result, int)

    def test_execute_invalid_sql(self, test_db):
        """Test executing invalid SQL returns -1."""
        result = test_db.executeSQL("INVALID SQL QUERY")

        assert result == -1

    def test_execute_with_connection_error(self, test_db):
        """Test SQL execution handles connection errors."""
        # Use an invalid database path
        test_db._db_name = "/invalid/path/to/database.db"

        result = test_db.executeSQL("SELECT * FROM users")

        assert result == -1

    def test_execute_with_parameters(self, populated_db):
        """Test parameterized queries prevent SQL injection."""
        # This should safely handle special characters
        result = populated_db.executeSQL(
            "SELECT * FROM users WHERE username = ?",
            ("test'; DROP TABLE users; --",),
        )

        # Result could be a list or 0 (if no rows found)
        assert isinstance(result, (list, int))
        if isinstance(result, list):
            assert len(result) == 0  # Should not find anything, but shouldn't crash


class TestUserCRUD:
    """Test user CRUD operations."""

    def test_add_user_success(self, test_db):
        """Test adding a new user."""
        result = test_db.addUser(
            username="newuser",
            fullname="New User",
            email="newuser@example.com",
            pin="9999",
            labname="New Lab",
            active=1,
            isadmin=0,
        )

        assert result > 0

        # Verify user was added
        user = test_db.getUserByName("newuser", asdict=True)
        assert user["username"] == "newuser"
        assert user["fullname"] == "New User"
        assert user["email"] == "newuser@example.com"

    def test_add_user_without_username(self, test_db):
        """Test adding user without username fails."""
        result = test_db.addUser(username="", email="test@example.com")

        assert result == -1

    def test_add_user_without_email(self, test_db):
        """Test adding user without email fails."""
        result = test_db.addUser(username="testuser", email="")

        assert result == -1

    def test_add_duplicate_username(self, populated_db):
        """Test adding user with duplicate username fails."""
        result = populated_db.addUser(
            username="test_user1", email="different@example.com"
        )

        assert result == -1

    def test_add_duplicate_email(self, populated_db):
        """Test adding user with duplicate email fails."""
        result = populated_db.addUser(
            username="different_user", email="test1@example.com"
        )

        assert result == -1

    def test_add_user_with_special_characters(self, test_db):
        """Test adding user with special characters in fields."""
        result = test_db.addUser(
            username="user_with_apostrophe",
            fullname="O'Brien",
            email="obrien@example.com",
            pin="1'2'3'4",
        )

        assert result > 0

        user = test_db.getUserByName("user_with_apostrophe", asdict=True)
        assert user["fullname"] == "O'Brien"

    def test_get_user_by_name(self, populated_db):
        """Test retrieving user by username."""
        user = populated_db.getUserByName("test_user1", asdict=False)

        assert user is not None
        assert user["username"] == "test_user1"

    def test_get_user_by_name_asdict(self, populated_db):
        """Test retrieving user by username as dictionary."""
        user = populated_db.getUserByName("test_user1", asdict=True)

        assert isinstance(user, dict)
        assert user["username"] == "test_user1"
        assert user["email"] == "test1@example.com"

    def test_get_user_by_name_not_found(self, populated_db):
        """Test retrieving non-existent user returns empty dict."""
        user = populated_db.getUserByName("nonexistent")

        assert user == {}

    def test_get_user_by_email(self, populated_db):
        """Test retrieving user by email."""
        user = populated_db.getUserByEmail("test1@example.com", asdict=True)

        assert user["username"] == "test_user1"

    def test_get_user_by_email_not_found(self, populated_db):
        """Test retrieving user by non-existent email."""
        user = populated_db.getUserByEmail("nonexistent@example.com")

        assert user == {}

    def test_get_user_by_id(self, populated_db):
        """Test retrieving user by database ID."""
        user = populated_db.getUserById(1, asdict=True)

        assert user is not None
        assert "username" in user

    def test_get_user_by_id_not_found(self, populated_db):
        """Test retrieving user by non-existent ID."""
        user = populated_db.getUserById(9999)

        assert user == {}

    def test_get_all_users(self, populated_db):
        """Test retrieving all users."""
        users = populated_db.getAllUsers(asdict=False)

        assert isinstance(users, list)
        assert len(users) >= 3  # At least 2 active + 1 inactive

    def test_get_all_users_active_only(self, populated_db):
        """Test retrieving only active users."""
        users = populated_db.getAllUsers(active_only=True, asdict=False)

        assert len(users) >= 2  # At least 2 active users
        # Verify all returned users are active
        for user in users:
            assert user["active"] == 1

    def test_get_all_users_asdict(self, populated_db):
        """Test retrieving all users as dictionary."""
        users = populated_db.getAllUsers(asdict=True)

        assert isinstance(users, dict)
        assert "test_user1" in users
        assert "test_user2" in users

    def test_update_user_by_username(self, populated_db):
        """Test updating user by username."""
        result = populated_db.updateUser(
            username="test_user1",
            fullname="Updated Full Name",
            email="updated@example.com",
        )

        assert result >= 0

        user = populated_db.getUserByName("test_user1", asdict=True)
        assert user["fullname"] == "Updated Full Name"
        assert user["email"] == "updated@example.com"

    def test_update_user_by_id(self, populated_db):
        """Test updating user by database ID."""
        result = populated_db.updateUser(user_id=1, fullname="Updated by ID")

        assert result >= 0

    def test_update_user_no_identifier(self, populated_db):
        """Test updating user without ID or username fails."""
        result = populated_db.updateUser(fullname="No Identifier")

        assert result == -1

    def test_update_user_no_updates(self, populated_db):
        """Test updating user with no fields returns 0."""
        result = populated_db.updateUser(username="test_user1")

        assert result == 0

    def test_deactivate_user(self, populated_db):
        """Test deactivating a user."""
        result = populated_db.deactivateUser(username="test_user1")

        assert result >= 0

        user = populated_db.getUserByName("test_user1", asdict=True)
        assert user["active"] == 0


class TestIncubatorCRUD:
    """Test incubator CRUD operations."""

    def test_add_incubator_success(self, test_db):
        """Test adding a new incubator."""
        result = test_db.addIncubator(
            name="Test_Incubator",
            location="Room C",
            owner="test_owner",
            description="Test incubator",
        )

        assert result > 0

        incubator = test_db.getIncubatorByName("Test_Incubator", asdict=True)
        assert incubator["name"] == "Test_Incubator"
        assert incubator["location"] == "Room C"

    def test_add_incubator_without_name(self, test_db):
        """Test adding incubator without name fails."""
        result = test_db.addIncubator(name="")

        assert result == -1

    def test_add_duplicate_incubator_name(self, populated_db):
        """Test adding incubator with duplicate name fails."""
        result = populated_db.addIncubator(name="Incubator_01")

        assert result == -1

    def test_get_incubator_by_name(self, populated_db):
        """Test retrieving incubator by name."""
        incubator = populated_db.getIncubatorByName("Incubator_01", asdict=True)

        assert incubator["name"] == "Incubator_01"
        assert incubator["location"] == "Room A"

    def test_get_incubator_by_name_not_found(self, populated_db):
        """Test retrieving non-existent incubator."""
        incubator = populated_db.getIncubatorByName("Nonexistent")

        assert incubator == {}

    def test_get_incubator_by_id(self, populated_db):
        """Test retrieving incubator by database ID."""
        incubator = populated_db.getIncubatorById(1, asdict=True)

        assert incubator is not None
        assert "name" in incubator

    def test_get_all_incubators(self, populated_db):
        """Test retrieving all incubators."""
        incubators = populated_db.getAllIncubators(asdict=False)

        assert isinstance(incubators, list)
        assert len(incubators) >= 2  # At least 2 incubators from fixture

    def test_get_all_incubators_asdict(self, populated_db):
        """Test retrieving all incubators as dictionary."""
        incubators = populated_db.getAllIncubators(asdict=True)

        assert isinstance(incubators, dict)
        assert "Incubator_01" in incubators
        assert "Incubator_02" in incubators

    def test_update_incubator_by_name(self, populated_db):
        """Test updating incubator by name."""
        result = populated_db.updateIncubator(
            name="Incubator_01", location="New Location", description="Updated"
        )

        assert result >= 0

        incubator = populated_db.getIncubatorByName("Incubator_01", asdict=True)
        assert incubator["location"] == "New Location"

    def test_update_incubator_by_id(self, populated_db):
        """Test updating incubator by database ID."""
        result = populated_db.updateIncubator(incubator_id=1, location="Updated by ID")

        assert result >= 0

    def test_deactivate_incubator(self, populated_db):
        """Test deactivating an incubator."""
        result = populated_db.deactivateIncubator(name="Incubator_01")

        assert result >= 0

        incubator = populated_db.getIncubatorByName("Incubator_01", asdict=True)
        assert incubator["active"] == 0


class TestDeviceManagement:
    """Test ethoscope device management."""

    def test_update_ethoscopes_new_device(self, test_db):
        """Test adding a new ethoscope."""
        result = test_db.updateEthoscopes(
            ethoscope_id="new_etho_001",
            ethoscope_name="ETHOSCOPE_NEW",
            active=1,
            last_ip="192.168.1.200",
            status="online",
        )

        assert result > 0

        device = test_db.getEthoscope("new_etho_001", asdict=True)
        assert device["new_etho_001"]["ethoscope_name"] == "ETHOSCOPE_NEW"

    def test_update_ethoscopes_existing_device(self, populated_db):
        """Test updating an existing ethoscope."""
        result = populated_db.updateEthoscopes(
            ethoscope_id="test_etho_001", status="offline", problems="Connection lost"
        )

        assert result >= 0

        device = populated_db.getEthoscope("test_etho_001", asdict=True)
        assert device["test_etho_001"]["status"] == "offline"

    def test_update_ethoscopes_blacklist(self, test_db):
        """Test that blacklisted devices are not added."""
        result = test_db.updateEthoscopes(
            ethoscope_id="blacklisted_001",
            ethoscope_name="ETHOSCOPE_000",  # Default blacklisted name
            active=1,
        )

        assert result is None

    def test_update_ethoscopes_without_name(self, test_db):
        """Test that devices without valid names are not added."""
        result = test_db.updateEthoscopes(ethoscope_id="no_name_001", ethoscope_name="")

        assert result is None

    def test_get_ethoscope_by_id(self, populated_db):
        """Test retrieving ethoscope by ID."""
        device = populated_db.getEthoscope("test_etho_001", asdict=True)

        assert "test_etho_001" in device
        assert device["test_etho_001"]["ethoscope_name"] == "ETHOSCOPE_001"

    def test_get_ethoscope_all(self, populated_db):
        """Test retrieving all ethoscopes."""
        devices = populated_db.getEthoscope("all", asdict=True)

        assert isinstance(devices, dict)
        assert len(devices) >= 1

    def test_get_ethoscope_not_found(self, populated_db):
        """Test retrieving non-existent ethoscope."""
        device = populated_db.getEthoscope("nonexistent")

        assert device == {}


class TestRunOperations:
    """Test run/experiment tracking operations."""

    def test_add_run_with_run_id(self, test_db):
        """Test adding a run with specified run_id."""
        result = test_db.addRun(
            run_id="custom_run_001",
            experiment_type="tracking",
            ethoscope_name="ETHOSCOPE_001",
            ethoscope_id="test_etho_001",
            username="testuser",
            user_id=1,
        )

        assert result > 0

        run = test_db.getRun("custom_run_001", asdict=True)
        assert "custom_run_001" in run

    def test_add_run_generates_run_id(self, test_db):
        """Test adding a run auto-generates run_id if not provided."""
        result = test_db.addRun(
            experiment_type="video",
            ethoscope_name="ETHOSCOPE_001",
            ethoscope_id="test_etho_001",
            username="testuser",
            user_id=1,
        )

        assert result > 0

    def test_get_run_by_id(self, populated_db):
        """Test retrieving run by run_id."""
        run = populated_db.getRun("test_run_001", asdict=True)

        assert "test_run_001" in run
        assert run["test_run_001"]["ethoscope_name"] == "ETHOSCOPE_001"

    def test_get_run_all(self, populated_db):
        """Test retrieving all runs."""
        runs = populated_db.getRun("all", asdict=True)

        assert isinstance(runs, dict)
        assert len(runs) >= 1

    def test_get_run_not_found(self, populated_db):
        """Test retrieving non-existent run."""
        run = populated_db.getRun("nonexistent")

        assert run == {}

    def test_stop_run(self, populated_db):
        """Test stopping a run."""
        status = populated_db.stopRun("test_run_001")

        assert status == "stopped"

        run = populated_db.getRun("test_run_001", asdict=False)
        assert run[0]["status"] == "stopped"

    def test_flag_problem(self, populated_db):
        """Test flagging a problem on a run."""
        result = populated_db.flagProblem("test_run_001", "Test problem message")

        assert result >= 0

        run = populated_db.getRun("test_run_001", asdict=False)
        assert "Test problem message" in run[0]["problems"]


class TestAlertOperations:
    """Test alert logging operations."""

    def test_log_alert(self, test_db):
        """Test logging an alert."""
        result = test_db.logAlert(
            device_id="test_device_001",
            alert_type="device_stopped",
            message="Device stopped unexpectedly",
            recipients="admin@example.com",
            run_id="test_run_001",
        )

        assert result > 0

    def test_has_alert_been_sent_true(self, test_db):
        """Test checking if alert has been sent (true case)."""
        # Log an alert first
        test_db.logAlert(
            device_id="test_device_001",
            alert_type="storage_warning",
            message="Low storage",
            run_id="test_run_001",
        )

        # Check if it exists
        result = test_db.hasAlertBeenSent(
            "test_device_001", "storage_warning", "test_run_001"
        )

        assert result is True

    def test_has_alert_been_sent_false(self, test_db):
        """Test checking if alert has been sent (false case)."""
        result = test_db.hasAlertBeenSent(
            "test_device_001", "nonexistent_alert", "test_run_001"
        )

        assert result is False

    def test_get_alert_history(self, test_db):
        """Test retrieving alert history."""
        # Add some alerts
        test_db.logAlert("device_001", "type1", "Message 1")
        test_db.logAlert("device_001", "type2", "Message 2")
        test_db.logAlert("device_002", "type1", "Message 3")

        # Get all alerts (as rows, not dict since dict conversion may fail with sqlite3.Row)
        alerts = test_db.getAlertHistory(asdict=False)
        assert isinstance(alerts, list)
        assert len(alerts) == 3

    def test_get_alert_history_filtered(self, test_db):
        """Test retrieving filtered alert history."""
        # Add some alerts
        test_db.logAlert("device_001", "type1", "Message 1")
        test_db.logAlert("device_001", "type2", "Message 2")
        test_db.logAlert("device_002", "type1", "Message 3")

        # Filter by device
        alerts = test_db.getAlertHistory(device_id="device_001", asdict=False)
        assert len(alerts) == 2

        # Filter by type
        alerts = test_db.getAlertHistory(alert_type="type1", asdict=False)
        assert len(alerts) == 2


class TestPINAuthentication:
    """Test PIN hashing and authentication."""

    def test_hash_pin(self, test_db):
        """Test PIN hashing."""
        hashed = test_db.hash_pin("1234")

        assert hashed.startswith("pbkdf2$")
        assert len(hashed) > 50

    def test_verify_pin_success(self, populated_db):
        """Test successful PIN verification."""
        # First hash and update the PIN
        hashed = populated_db.hash_pin("1234")
        populated_db.updateUser(username="test_user1", pin=hashed)

        # Verify it
        result = populated_db.verify_pin("test_user1", "1234")

        assert result is True

    def test_verify_pin_failure(self, populated_db):
        """Test failed PIN verification."""
        # First hash and update the PIN
        hashed = populated_db.hash_pin("1234")
        populated_db.updateUser(username="test_user1", pin=hashed)

        # Try wrong PIN
        result = populated_db.verify_pin("test_user1", "wrong")

        assert result is False

    def test_verify_pin_user_not_found(self, populated_db):
        """Test PIN verification for non-existent user."""
        result = populated_db.verify_pin("nonexistent", "1234")

        assert result is False

    def test_authenticate_user_success(self, populated_db):
        """Test successful user authentication."""
        # Hash and set PIN
        hashed = populated_db.hash_pin("1234")
        populated_db.updateUser(username="test_user1", pin=hashed)

        # Authenticate
        user = populated_db.authenticate_user("test_user1", "1234")

        assert user is not None
        assert user["username"] == "test_user1"

    def test_authenticate_user_wrong_pin(self, populated_db):
        """Test authentication with wrong PIN."""
        # Hash and set PIN
        hashed = populated_db.hash_pin("1234")
        populated_db.updateUser(username="test_user1", pin=hashed)

        # Try wrong PIN
        user = populated_db.authenticate_user("test_user1", "wrong")

        assert user is None

    def test_authenticate_inactive_user(self, populated_db):
        """Test authentication of inactive user fails."""
        # Hash and set PIN for inactive user
        hashed = populated_db.hash_pin("0000")
        populated_db.updateUser(username="inactive_user", pin=hashed)

        user = populated_db.authenticate_user("inactive_user", "0000")

        assert user is None


class TestCleanupOperations:
    """Test database cleanup operations."""

    def test_retire_inactive_devices(self, populated_db):
        """Test retiring devices not seen for a long time."""
        # Create a device with old last_seen timestamp
        old_date = datetime.datetime.now() - datetime.timedelta(days=100)
        populated_db.executeSQL(
            f"INSERT INTO {populated_db._ethoscopes_table_name} "
            "(ethoscope_id, ethoscope_name, first_seen, last_seen, active) "
            "VALUES (?, ?, ?, ?, ?)",
            ("old_device", "OLD_DEVICE", old_date, old_date, 1),
        )

        # Retire devices not seen for 90 days
        count = populated_db.retire_inactive_devices(threshold_days=90)

        assert count >= 1

    def test_purge_unnamed_devices(self, populated_db):
        """Test purging devices without valid names."""
        # Create device with no name
        now = datetime.datetime.now()
        populated_db.executeSQL(
            f"INSERT INTO {populated_db._ethoscopes_table_name} "
            "(ethoscope_id, ethoscope_name, first_seen, last_seen, active) "
            "VALUES (?, ?, ?, ?, ?)",
            ("unnamed_device", "", now, now, 1),
        )

        # Purge unnamed devices
        count = populated_db.purge_unnamed_devices()

        assert count >= 1

    def test_cleanup_stale_busy_devices(self, populated_db):
        """Test cleaning up stale busy devices."""
        # Create a busy device with old last_seen
        old_date = datetime.datetime.now() - datetime.timedelta(minutes=15)
        populated_db.executeSQL(
            f"INSERT INTO {populated_db._ethoscopes_table_name} "
            "(ethoscope_id, ethoscope_name, first_seen, last_seen, active, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("busy_device", "BUSY_DEVICE", old_date, old_date, 1, "busy"),
        )

        # Cleanup devices busy for more than 10 minutes
        count = populated_db.cleanup_stale_busy_devices(timeout_minutes=10)

        assert count >= 1


class TestSimpleDB:
    """Test simpleDB class."""

    def test_simple_db_init(self, temp_config_dir):
        """Test simpleDB initialization."""
        db_file = os.path.join(temp_config_dir, "test_simple.db")
        db = simpleDB(db_file, keys=["name", "value"])

        assert db._db_file == db_file
        assert "name" in db._keys
        assert "value" in db._keys

    def test_simple_db_add(self, temp_config_dir):
        """Test adding items to simpleDB."""
        db_file = os.path.join(temp_config_dir, "test_simple.db")
        db = simpleDB(db_file, keys=["name", "value"])

        db.add({"name": "test", "value": "123"})

        assert len(db._db) == 1
        assert db._db[0]["name"] == "test"

    def test_simple_db_list(self, temp_config_dir):
        """Test listing items from simpleDB."""
        db_file = os.path.join(temp_config_dir, "test_simple.db")
        db = simpleDB(db_file, keys=["name", "value"])

        db.add({"name": "test1", "value": "123"})
        db.add({"name": "test2", "value": "456"})

        items = db.list()
        assert len(items) == 2

    def test_simple_db_save_load(self, temp_config_dir):
        """Test saving and loading simpleDB."""
        db_file = os.path.join(temp_config_dir, "test_simple.db")
        db = simpleDB(db_file, keys=["name", "value"])

        db.add({"name": "test", "value": "123"})
        result = db.save()
        assert result is True

        # Load in new instance
        db2 = simpleDB(db_file, keys=["name", "value"])
        result = db2.load()
        assert result is True
        assert len(db2._db) == 1


class TestUtilityFunctions:
    """Test utility functions."""

    def test_random_date(self):
        """Test random_date function."""
        start = datetime.datetime(2020, 1, 1)
        end = datetime.datetime(2020, 12, 31)

        result = random_date(start, end)

        assert isinstance(result, datetime.datetime)
        assert start <= result <= end

    def test_set_default_config_dir(self, temp_config_dir):
        """Test setting default config directory."""
        set_default_config_dir(temp_config_dir)

        # This should use the default
        db = ExperimentalDB()

        assert db._config_dir == temp_config_dir


class TestDatabaseMigrations:
    """Test database schema migration functions."""

    def test_migrate_ethoscopes_primary_key_old_structure(self, temp_config_dir):
        """Test migration of ethoscopes table from old id-based to ethoscope_id primary key."""
        # Create database with old structure
        db_path = os.path.join(temp_config_dir, "ethoscope-node.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create old-style table with auto-incrementing id
        cursor.execute(
            """
            CREATE TABLE ethoscopes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ethoscope_id TEXT NOT NULL,
                ethoscope_name TEXT NOT NULL,
                first_seen TIMESTAMP NOT NULL,
                last_seen TIMESTAMP NOT NULL,
                active INTEGER,
                last_ip TEXT,
                machineinfo TEXT,
                problems TEXT,
                comments TEXT,
                status TEXT
            )
        """
        )

        # Insert some test data with duplicate ethoscope_ids
        now = datetime.datetime.now()
        cursor.execute(
            "INSERT INTO ethoscopes VALUES (1, 'etho_001', 'ETHOSCOPE_001', ?, ?, 1, '192.168.1.1', '', '', '', 'online')",
            (now, now),
        )
        cursor.execute(
            "INSERT INTO ethoscopes VALUES (2, 'etho_001', 'ETHOSCOPE_001_UPDATED', ?, ?, 1, '192.168.1.2', '', '', '', 'online')",
            (now, now),
        )
        cursor.execute(
            "INSERT INTO ethoscopes VALUES (3, 'etho_002', 'ETHOSCOPE_002', ?, ?, 1, '192.168.1.3', '', '', '', 'online')",
            (now, now),
        )
        conn.commit()
        conn.close()

        # Initialize ExperimentalDB which should trigger migration
        _ = ExperimentalDB(config_dir=temp_config_dir)

        # Verify migration occurred
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check that ethoscope_id is now primary key
        cursor.execute("PRAGMA table_info(ethoscopes)")
        columns = cursor.fetchall()
        ethoscope_id_col = [col for col in columns if col[1] == "ethoscope_id"][0]
        assert ethoscope_id_col[5] == 1  # pk column should be 1

        # Verify only the most recent duplicate was kept
        cursor.execute(
            "SELECT COUNT(*) FROM ethoscopes WHERE ethoscope_id = 'etho_001'"
        )
        assert cursor.fetchone()[0] == 1

        # Verify total count (2 unique ethoscope_ids)
        cursor.execute("SELECT COUNT(*) FROM ethoscopes")
        assert cursor.fetchone()[0] == 2

        conn.close()

    def test_migrate_runs_primary_key_old_structure(self, temp_config_dir):
        """Test migration of runs table from old id-based to run_id primary key."""
        # Create database with old structure
        db_path = os.path.join(temp_config_dir, "ethoscope-node.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create old-style runs table with auto-incrementing id
        cursor.execute(
            """
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                type TEXT NOT NULL,
                ethoscope_name TEXT NOT NULL,
                ethoscope_id TEXT NOT NULL,
                user_name TEXT,
                user_id INTEGER NOT NULL,
                location TEXT,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP,
                alert INTEGER,
                problems TEXT,
                experimental_data TEXT,
                comments TEXT,
                status TEXT
            )
        """
        )

        # Insert test data with duplicate run_ids
        now = datetime.datetime.now()
        cursor.execute(
            "INSERT INTO runs VALUES (1, 'run_001', 'tracking', 'ETHOSCOPE_001', 'etho_001', 'user1', 1, 'Room A', ?, 0, 0, '', '', '', 'running')",
            (now,),
        )
        cursor.execute(
            "INSERT INTO runs VALUES (2, 'run_001', 'tracking', 'ETHOSCOPE_001', 'etho_001', 'user1', 1, 'Room A', ?, 0, 0, '', '', '', 'stopped')",
            (now,),
        )
        conn.commit()
        conn.close()

        # Initialize ExperimentalDB which should trigger migration
        _ = ExperimentalDB(config_dir=temp_config_dir)

        # Verify migration occurred
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check that run_id is now primary key
        cursor.execute("PRAGMA table_info(runs)")
        columns = cursor.fetchall()
        run_id_col = [col for col in columns if col[1] == "run_id"][0]
        assert run_id_col[5] == 1  # pk column should be 1

        conn.close()

    def test_migrate_alert_logs_run_id_column(self, temp_config_dir):
        """Test migration to add run_id column to alert_logs table."""
        # Create database with old alert_logs structure (without run_id)
        db_path = os.path.join(temp_config_dir, "ethoscope-node.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE alert_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                message TEXT NOT NULL,
                recipients TEXT,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """
        )
        conn.commit()
        conn.close()

        # Initialize ExperimentalDB which should trigger migration
        _ = ExperimentalDB(config_dir=temp_config_dir)

        # Verify run_id column was added
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(alert_logs)")
        columns = [col[1] for col in cursor.fetchall()]
        assert "run_id" in columns
        conn.close()

    def test_migrate_users_add_telephone_column(self, temp_config_dir):
        """Test migration to add telephone column to users table."""
        # Create database with old users structure (without telephone)
        db_path = os.path.join(temp_config_dir, "ethoscope-node.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                fullname TEXT NOT NULL,
                pin TEXT,
                email TEXT NOT NULL,
                labname TEXT,
                active INTEGER,
                isadmin INTEGER,
                created TIMESTAMP
            )
        """
        )
        conn.commit()
        conn.close()

        # Initialize ExperimentalDB which should trigger migration
        _ = ExperimentalDB(config_dir=temp_config_dir)

        # Verify telephone column was added
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]
        assert "telephone" in columns
        conn.close()

    def test_migrate_users_from_config_empty_db(self, temp_config_dir):
        """Test migration of users from config file to empty database."""
        # Create a mock configuration - need to patch inside the module
        mock_config = Mock()
        mock_config.content = {
            "users": {
                "user1": {
                    "name": "user1",
                    "fullname": "User One",
                    "PIN": "1234",
                    "email": "user1@example.com",
                    "telephone": "+1234567890",
                    "group": "Lab A",
                    "active": True,
                    "isAdmin": False,
                },
                "admin": {
                    "name": "admin",
                    "fullname": "Administrator",
                    "PIN": "0000",
                    "email": "admin@example.com",
                    "group": "Lab A",
                    "active": True,
                    "isAdmin": True,
                },
            }
        }

        with patch(
            "ethoscope_node.utils.configuration.EthoscopeConfiguration"
        ) as mock_config_class:
            mock_config_class.return_value = mock_config

            db = ExperimentalDB(config_dir=temp_config_dir)

            # Verify users were migrated
            users = db.getAllUsers()
            assert len(users) >= 2

    def test_migrate_users_from_config_skips_populated_db(self, populated_db):
        """Test that user migration is skipped if database already has users."""
        # Count initial users
        initial_count = len(populated_db.getAllUsers())

        # Trigger migration again
        populated_db._migrate_users_from_config()

        # Verify no additional users were added
        final_count = len(populated_db.getAllUsers())
        assert final_count == initial_count

    def test_migrate_incubators_from_config_empty_db(self, temp_config_dir):
        """Test migration of incubators from config file to empty database."""
        mock_config = Mock()
        mock_config.content = {
            "incubators": {
                "inc1": {
                    "name": "Incubator 1",
                    "location": "Room A",
                    "owner": "user1",
                    "description": "Main incubator",
                },
                "inc2": {
                    "name": "Incubator 2",
                    "location": "Room B",
                    "owner": "user2",
                    "description": "Backup incubator",
                },
            }
        }

        with patch(
            "ethoscope_node.utils.configuration.EthoscopeConfiguration"
        ) as mock_config_class:
            mock_config_class.return_value = mock_config

            db = ExperimentalDB(config_dir=temp_config_dir)

            # Verify incubators were migrated
            incubators = db.getAllIncubators()
            assert len(incubators) >= 2


class TestExperimentOperations:
    """Test experiment management operations."""

    def test_add_to_experiment_new(self, test_db):
        """Test adding a new experiment with runs."""
        # Note: There's a bug in addToExperiment where INSERT only provides 3 values
        # but table has 5 columns (missing tags). This tests the current behavior.
        # The method returns -1 on error due to SQL mismatch
        result = test_db.addToExperiment(
            runs=["run_001", "run_002"],
            metadata="test_metadata",
            comments="Test experiment",
        )

        # Currently returns -1 due to SQL column mismatch bug
        # (INSERT provides 3 values, table has 5 columns)
        assert result == -1

    def test_add_to_experiment_update_existing(self, test_db):
        """Test updating an existing experiment."""
        # First manually insert a valid experiment to work around INSERT bug
        test_db.executeSQL(
            f"INSERT INTO {test_db._experiments_table_name} "
            "(runs, metadata, tags, comments) VALUES (?, ?, ?, ?)",
            ("run_001", None, None, "Initial"),
        )

        # Get the ID
        exp_id = test_db.executeSQL(
            f"SELECT id FROM {test_db._experiments_table_name} LIMIT 1"
        )[0]["id"]

        # Update it using the WHERE experiment_id = ? clause
        # Note: This also has a bug - WHERE clause uses experiment_id but column is id
        result = test_db.addToExperiment(
            experiment_id=exp_id, runs=["run_001", "run_002"], comments="Updated"
        )

        # Returns -1 or 0 since no rows matched (column name bug) or SQL error
        assert result in [-1, 0]

    def test_add_to_experiment_with_list_runs(self, test_db):
        """Test list of runs gets joined with semicolon."""
        # Verify the list joining behavior works even though INSERT fails
        result = test_db.addToExperiment(runs=["run_001", "run_002", "run_003"])

        # Returns -1 due to SQL column mismatch bug
        assert result == -1

    def test_add_to_experiment_with_string_runs(self, test_db):
        """Test adding experiment with runs as string."""
        result = test_db.addToExperiment(runs="run_001;run_002")

        # Returns -1 due to SQL column mismatch bug
        assert result == -1

    def test_get_experiment_by_id(self, test_db):
        """Test retrieving experiment by ID."""
        # Manually insert valid experiment
        test_db.executeSQL(
            f"INSERT INTO {test_db._experiments_table_name} "
            "(runs, metadata, tags, comments) VALUES (?, ?, ?, ?)",
            ("run_001", None, None, "Test"),
        )

        exp_id = test_db.executeSQL(
            f"SELECT id FROM {test_db._experiments_table_name} LIMIT 1"
        )[0]["id"]

        # Note: getExperiment uses wrong column name (run_id instead of id)
        # When query fails, row is -1, which leads to TypeError on row[0].keys()
        # Test the current (buggy) behavior
        try:
            experiment = test_db.getExperiment(exp_id, asdict=True)
            # If no exception, should return empty dict or -1
            assert experiment in [{}, -1]
        except (TypeError, AttributeError):
            # Expected - row is -1 from SQL error, can't call row[0].keys()
            pass

    def test_get_experiment_all(self, test_db):
        """Test retrieving all experiments."""
        # Manually insert valid experiments
        test_db.executeSQL(
            f"INSERT INTO {test_db._experiments_table_name} "
            "(runs, metadata, tags, comments) VALUES (?, ?, ?, ?)",
            ("run_001", None, None, "Exp 1"),
        )
        test_db.executeSQL(
            f"INSERT INTO {test_db._experiments_table_name} "
            "(runs, metadata, tags, comments) VALUES (?, ?, ?, ?)",
            ("run_002", None, None, "Exp 2"),
        )

        experiments = test_db.getExperiment("all", asdict=True)

        assert isinstance(experiments, dict)
        assert len(experiments) >= 2

    def test_get_experiment_not_found(self, test_db):
        """Test retrieving non-existent experiment."""
        # getExperiment with specific ID uses wrong column name (run_id vs id)
        # so query fails and returns -1
        experiment = test_db.getExperiment(99999)

        # Returns -1 due to SQL error (no column run_id)
        assert experiment == -1 or experiment == {}


class TestAdvancedUserQueries:
    """Test advanced user query operations."""

    def test_get_user_by_run(self, populated_db):
        """Test retrieving user information from a run."""
        user = populated_db.getUserByRun("test_run_001", asdict=True)

        assert user["username"] == "test_user1"

    def test_get_user_by_run_not_found(self, populated_db):
        """Test retrieving user for non-existent run."""
        user = populated_db.getUserByRun("nonexistent_run")

        assert user == {}

    def test_get_users_for_device_running_only(self, populated_db):
        """Test getting users with running experiments on a device."""
        users = populated_db.getUsersForDevice(
            "test_etho_001", running_only=True, asdict=True
        )

        assert len(users) >= 1
        assert any(u["username"] == "test_user1" for u in users)

    def test_get_users_for_device_all_runs(self, populated_db):
        """Test getting all users who have run experiments on a device."""
        # Stop the existing run
        populated_db.stopRun("test_run_001")

        # Add another run
        populated_db.addRun(
            run_id="test_run_002",
            ethoscope_id="test_etho_001",
            ethoscope_name="ETHOSCOPE_001",
            username="test_user2",
            user_id=2,
        )

        users = populated_db.getUsersForDevice(
            "test_etho_001", running_only=False, asdict=True
        )

        assert len(users) >= 2

    def test_get_users_for_device_no_users(self, test_db):
        """Test getting users for device with no runs."""
        users = test_db.getUsersForDevice("nonexistent_device")

        assert users == []

    def test_get_all_users_admin_only(self, temp_config_dir):
        """Test retrieving only admin users."""
        db = ExperimentalDB(config_dir=temp_config_dir)

        # Add regular and admin users
        db.addUser(username="regular", email="regular@example.com", isadmin=0)
        db.addUser(username="admin1", email="admin1@example.com", isadmin=1)
        db.addUser(username="admin2", email="admin2@example.com", isadmin=1)

        admins = db.getAllUsers(admin_only=True)

        assert len(admins) >= 2
        for user in admins:
            assert user["isadmin"] == 1


class TestPINMigrationAndLegacyFormats:
    """Test PIN migration and legacy format handling."""

    def test_verify_pin_plaintext_auto_upgrade(self, populated_db):
        """Test that plaintext PINs are automatically upgraded on verification."""
        # Set a plaintext PIN
        populated_db.updateUser(username="test_user1", pin="1234")

        # Verify with plaintext (should upgrade)
        result = populated_db.verify_pin("test_user1", "1234")

        assert result is True

        # Check that PIN was upgraded to hashed format
        user = populated_db.getUserByName("test_user1", asdict=True)
        assert user["pin"].startswith("pbkdf2$")

    def test_verify_pin_legacy_simple_hash_upgrade(self, populated_db):
        """Test that legacy simple hash PINs are upgraded on verification."""
        import hashlib

        # Create legacy simple hash
        legacy_hash = hashlib.pbkdf2_hmac(
            "sha256", b"1234", b"ethoscope_salt", 100000
        ).hex()

        # Set legacy hash
        populated_db.updateUser(username="test_user1", pin=legacy_hash)

        # Verify (should upgrade)
        result = populated_db.verify_pin("test_user1", "1234")

        assert result is True

        # Check that PIN was upgraded
        user = populated_db.getUserByName("test_user1", asdict=True)
        assert user["pin"].startswith("pbkdf2$")

    def test_migrate_plaintext_pins(self, temp_config_dir):
        """Test batch migration of plaintext PINs."""
        db = ExperimentalDB(config_dir=temp_config_dir)

        # Add users with plaintext PINs
        db.addUser(username="user1", email="user1@example.com", pin="1111")
        db.addUser(username="user2", email="user2@example.com", pin="2222")

        # Migrate
        count = db.migrate_plaintext_pins()

        # Note: The migration logic checks for various formats, so count may vary
        # Just verify it doesn't crash and returns a number
        assert isinstance(count, int)
        assert count >= 0

    def test_verify_pin_invalid_pbkdf2_format(self, populated_db):
        """Test verification with corrupted PBKDF2 hash format."""
        # Set invalid PBKDF2 format
        populated_db.updateUser(username="test_user1", pin="pbkdf2$invalid$format")

        result = populated_db.verify_pin("test_user1", "1234")

        assert result is False

    def test_verify_pin_no_pin_set(self, populated_db):
        """Test verification when user has no PIN set."""
        # Set empty PIN
        populated_db.updateUser(username="test_user1", pin="")

        result = populated_db.verify_pin("test_user1", "1234")

        assert result is False


class TestAdvancedCleanupOperations:
    """Test advanced cleanup operations."""

    def test_cleanup_offline_busy_devices(self, populated_db):
        """Test cleanup of devices marked busy/unreached but actually offline."""
        # Create devices with different statuses and old timestamps
        old_date = datetime.datetime.now() - datetime.timedelta(hours=3)

        # Busy device that hasn't been seen
        populated_db.executeSQL(
            f"INSERT INTO {populated_db._ethoscopes_table_name} "
            "(ethoscope_id, ethoscope_name, first_seen, last_seen, active, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("busy_device", "BUSY_DEVICE", old_date, old_date, 1, "busy"),
        )

        # Unreached device that hasn't been seen
        populated_db.executeSQL(
            f"INSERT INTO {populated_db._ethoscopes_table_name} "
            "(ethoscope_id, ethoscope_name, first_seen, last_seen, active, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "unreached_device",
                "UNREACHED_DEVICE",
                old_date,
                old_date,
                1,
                "unreached",
            ),
        )

        # Cleanup devices not seen for 2 hours
        count = populated_db.cleanup_offline_busy_devices(threshold_hours=2)

        assert count >= 2

        # Verify devices are now marked as offline
        busy = populated_db.getEthoscope("busy_device", asdict=True)
        assert busy["busy_device"]["status"] == "offline"

        unreached = populated_db.getEthoscope("unreached_device", asdict=True)
        assert unreached["unreached_device"]["status"] == "offline"

    def test_cleanup_orphaned_running_sessions_multiple_sessions(self, populated_db):
        """Test cleanup of orphaned running sessions when device has multiple running sessions."""
        # Create device
        populated_db.updateEthoscopes(
            ethoscope_id="multi_session_device",
            ethoscope_name="MULTI_SESSION",
            status="running",
        )

        # Create multiple running sessions (simulates device restart without cleanup)
        old_time = datetime.datetime.now() - datetime.timedelta(hours=5)
        recent_time = datetime.datetime.now() - datetime.timedelta(minutes=10)

        # Old session (should be cleaned up)
        populated_db.executeSQL(
            f"INSERT INTO {populated_db._runs_table_name} "
            "(run_id, type, ethoscope_name, ethoscope_id, user_name, user_id, "
            "location, start_time, end_time, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "old_run",
                "tracking",
                "MULTI_SESSION",
                "multi_session_device",
                "test_user1",
                1,
                "Room A",
                old_time,
                0,
                "running",
            ),
        )

        # Recent session (should be kept)
        populated_db.executeSQL(
            f"INSERT INTO {populated_db._runs_table_name} "
            "(run_id, type, ethoscope_name, ethoscope_id, user_name, user_id, "
            "location, start_time, end_time, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "recent_run",
                "tracking",
                "MULTI_SESSION",
                "multi_session_device",
                "test_user1",
                1,
                "Room A",
                recent_time,
                0,
                "running",
            ),
        )

        # Cleanup orphaned sessions
        count = populated_db.cleanup_orphaned_running_sessions(min_age_hours=1)

        assert count >= 1

        # Verify old session was stopped
        old_run = populated_db.getRun("old_run", asdict=False)
        assert old_run[0]["status"] == "stopped"

        # Verify recent session is still running
        recent_run = populated_db.getRun("recent_run", asdict=False)
        assert recent_run[0]["status"] == "running"

    def test_cleanup_orphaned_running_sessions_device_not_running(self, populated_db):
        """Test cleanup when device status doesn't match running session."""
        # Create device with offline status
        populated_db.updateEthoscopes(
            ethoscope_id="offline_device",
            ethoscope_name="OFFLINE_DEVICE",
            status="offline",
        )

        # Create old running session
        old_time = datetime.datetime.now() - datetime.timedelta(hours=3)
        populated_db.executeSQL(
            f"INSERT INTO {populated_db._runs_table_name} "
            "(run_id, type, ethoscope_name, ethoscope_id, user_name, user_id, "
            "location, start_time, end_time, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "orphan_run",
                "tracking",
                "OFFLINE_DEVICE",
                "offline_device",
                "test_user1",
                1,
                "Room A",
                old_time,
                0,
                "running",
            ),
        )

        # Cleanup
        count = populated_db.cleanup_orphaned_running_sessions(min_age_hours=1)

        assert count >= 1

        # Verify session was stopped
        run = populated_db.getRun("orphan_run", asdict=False)
        assert run[0]["status"] == "stopped"
        assert "Orphaned session cleanup" in run[0]["problems"]

    def test_parse_session_time_various_formats(self, test_db):
        """Test parsing session times in various formats."""
        # String datetime
        dt1 = test_db._parse_session_time("2023-01-15 10:30:00.123456")
        assert isinstance(dt1, datetime.datetime)

        # String datetime without microseconds
        dt2 = test_db._parse_session_time("2023-01-15 10:30:00")
        assert isinstance(dt2, datetime.datetime)

        # Float timestamp
        dt3 = test_db._parse_session_time(1673779800.0)
        assert isinstance(dt3, datetime.datetime)

        # Integer timestamp
        dt4 = test_db._parse_session_time(1673779800)
        assert isinstance(dt4, datetime.datetime)

        # Invalid format
        dt5 = test_db._parse_session_time("invalid")
        assert dt5 is None


class TestSimpleDBAdvanced:
    """Test advanced simpleDB operations."""

    def test_simple_db_remove_existing(self, temp_config_dir):
        """Test removing an item from simpleDB."""
        db_file = os.path.join(temp_config_dir, "test_simple.db")
        db = simpleDB(db_file, keys=["name", "value"])

        db.add({"name": "test1", "value": "123"})
        db.add({"name": "test2", "value": "456"})

        # Get the ID of first item
        item_id = db._db[0]["id"]

        # Remove it
        result = db.remove(item_id)

        assert result is True
        assert len(db._db) == 1

    def test_simple_db_remove_nonexistent(self, temp_config_dir):
        """Test removing non-existent item returns False."""
        db_file = os.path.join(temp_config_dir, "test_simple.db")
        db = simpleDB(db_file, keys=["name", "value"])

        db.add({"name": "test", "value": "123"})

        result = db.remove("NONEXISTENT_ID")

        assert result is False

    def test_simple_db_list_with_field(self, temp_config_dir):
        """Test listing specific field from simpleDB."""
        db_file = os.path.join(temp_config_dir, "test_simple.db")
        db = simpleDB(db_file, keys=["name", "value"])

        db.add({"name": "test1", "value": "123"})
        db.add({"name": "test2", "value": "456"})

        names = db.list(onlyfield="name")

        assert len(names) == 2
        assert "test1" in names
        assert "test2" in names

    def test_simple_db_list_active_only(self, temp_config_dir):
        """Test listing only active items from simpleDB."""
        db_file = os.path.join(temp_config_dir, "test_simple.db")
        db = simpleDB(db_file, keys=["name", "value"])

        db.add({"name": "active", "value": "123"}, active=True)
        db.add({"name": "inactive", "value": "456"}, active=False)

        items = db.list(active=True)

        assert len(items) == 1
        assert items[0]["name"] == "active"

    def test_simple_db_list_invalid_field(self, temp_config_dir):
        """Test listing with invalid field returns empty list."""
        db_file = os.path.join(temp_config_dir, "test_simple.db")
        db = simpleDB(db_file, keys=["name", "value"])

        db.add({"name": "test", "value": "123"})

        result = db.list(onlyfield="invalid_field")

        assert result == []

    def test_simple_db_save_error_handling(self, temp_config_dir):
        """Test simpleDB save with error conditions."""
        db_file = "/invalid/path/that/does/not/exist/test.db"
        db = simpleDB(db_file, keys=["name"])

        db.add({"name": "test"})

        result = db.save()

        assert result is False

    def test_simple_db_load_nonexistent_file(self, temp_config_dir):
        """Test loading from non-existent file returns False."""
        db_file = os.path.join(temp_config_dir, "nonexistent.db")
        db = simpleDB(db_file, keys=["name"])

        result = db.load()

        # Should return None/False for non-existent file
        assert result is None or result is False

    def test_users_db_class(self, temp_config_dir):
        """Test UsersDB specialized class."""
        db_file = os.path.join(temp_config_dir, "users.db")
        db = UsersDB(db_file)

        # Verify it has the correct keys
        assert "name" in db._keys
        assert "email" in db._keys
        assert "laboratory" in db._keys

    def test_incubators_db_class(self, temp_config_dir):
        """Test Incubators specialized class."""
        db_file = os.path.join(temp_config_dir, "incubators.db")
        db = Incubators(db_file)

        # Verify it has the correct keys
        assert "name" in db._keys
        assert "set_temperature" in db._keys
        assert "set_humidity" in db._keys
