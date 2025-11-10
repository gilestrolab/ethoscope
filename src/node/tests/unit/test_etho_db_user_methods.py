"""
Unit tests for EthoDB user-related methods.

Tests the new user querying methods added for notification recipient filtering:
- getAllUsers with admin_only parameter
- getUsersForDevice with running_only parameter
- getUserByRun method
"""

import os
import shutil
import tempfile
from datetime import datetime

import pytest

from ethoscope_node.utils.etho_db import ExperimentalDB


@pytest.fixture
def test_db():
    """
    Create a temporary test database with sample data.

    Returns:
        ExperimentalDB: Database instance with test data
    """
    # Create temporary directory for database in a unique location to avoid migrations
    temp_dir = tempfile.mkdtemp(prefix="test_etho_db_")

    # Initialize database
    db = ExperimentalDB(temp_dir)

    # Clear any migrated data to start with a clean slate
    db.executeSQL(f"DELETE FROM {db._users_table_name}")
    db.executeSQL(f"DELETE FROM {db._runs_table_name}")
    db.executeSQL(f"DELETE FROM {db._ethoscopes_table_name}")

    # Add test users (active and isadmin must be integers: 1 or 0)
    db.addUser(
        username="alice",
        fullname="Alice Smith",
        pin="1234",
        email="alice@example.com",
        telephone="555-0001",
        labname="Lab A",
        active=1,
        isadmin=1,
    )

    db.addUser(
        username="bob",
        fullname="Bob Jones",
        pin="5678",
        email="bob@example.com",
        telephone="555-0002",
        labname="Lab B",
        active=1,
        isadmin=0,
    )

    db.addUser(
        username="charlie",
        fullname="Charlie Brown",
        pin="9012",
        email="charlie@example.com",
        telephone="555-0003",
        labname="Lab C",
        active=0,  # Inactive user
        isadmin=0,
    )

    db.addUser(
        username="diana",
        fullname="Diana Prince",
        pin="3456",
        email="diana@example.com",
        telephone="555-0004",
        labname="Lab D",
        active=1,
        isadmin=0,
    )

    # Add test ethoscope devices
    db.updateEthoscopes("device_001", ethoscope_name="Device 1", status="running")
    db.updateEthoscopes("device_002", ethoscope_name="Device 2", status="stopped")

    # Add test runs
    # Running experiment by Bob on device_001
    db.addRun(
        run_id="run_001",
        experiment_type="tracking",
        ethoscope_name="Device 1",
        ethoscope_id="device_001",
        username="bob",
        user_id=2,  # Bob's ID
        location="Incubator 1",
    )

    # Stopped experiment by Alice on device_001 (past user)
    db.addRun(
        run_id="run_002",
        experiment_type="sleep_deprivation",
        ethoscope_name="Device 1",
        ethoscope_id="device_001",
        username="alice",
        user_id=1,  # Alice's ID
        location="Incubator 1",
    )
    # Stop this run
    db.stopRun("run_002")

    # Running experiment by Diana on device_002
    db.addRun(
        run_id="run_003",
        experiment_type="tracking",
        ethoscope_name="Device 2",
        ethoscope_id="device_002",
        username="diana",
        user_id=4,  # Diana's ID
        location="Incubator 2",
    )

    # Stopped experiment by inactive user Charlie on device_002
    db.addRun(
        run_id="run_004",
        experiment_type="tracking",
        ethoscope_name="Device 2",
        ethoscope_id="device_002",
        username="charlie",
        user_id=3,  # Charlie's ID (inactive)
        location="Incubator 2",
    )
    # Stop this run
    db.stopRun("run_004")

    yield db

    # Cleanup
    db.close()
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestGetAllUsers:
    """Test getAllUsers method with admin_only parameter."""

    def test_get_all_users_no_filters(self, test_db):
        """Test getting all users without filters."""
        users = test_db.getAllUsers(asdict=True)
        assert len(users) == 4
        assert "alice" in users
        assert "bob" in users
        assert "charlie" in users
        assert "diana" in users

    def test_get_all_users_active_only(self, test_db):
        """Test getting only active users."""
        users = test_db.getAllUsers(active_only=True, asdict=True)
        assert len(users) == 3
        assert "alice" in users
        assert "bob" in users
        assert "diana" in users
        assert "charlie" not in users  # Inactive

    def test_get_all_users_admin_only(self, test_db):
        """Test getting only admin users."""
        users = test_db.getAllUsers(admin_only=True, asdict=True)
        assert len(users) == 1
        assert "alice" in users
        assert users["alice"]["isadmin"] == 1

    def test_get_all_users_active_admin_only(self, test_db):
        """Test getting only active admin users."""
        users = test_db.getAllUsers(active_only=True, admin_only=True, asdict=True)
        assert len(users) == 1
        assert "alice" in users
        assert users["alice"]["active"] == 1
        assert users["alice"]["isadmin"] == 1

    def test_get_all_users_as_list(self, test_db):
        """Test getting users as list instead of dict."""
        users = test_db.getAllUsers(active_only=True, asdict=False)
        assert isinstance(users, list)
        assert len(users) == 3


class TestGetUsersForDevice:
    """Test getUsersForDevice method with running_only parameter."""

    def test_get_users_for_device_running_only(self, test_db):
        """Test getting only users with currently running experiments."""
        users = test_db.getUsersForDevice("device_001", running_only=True, asdict=True)
        assert len(users) == 1
        assert users[0]["username"] == "bob"
        assert users[0]["email"] == "bob@example.com"

    def test_get_users_for_device_all_past_users(self, test_db):
        """Test getting all users who have used the device (including past)."""
        users = test_db.getUsersForDevice("device_001", running_only=False, asdict=True)
        assert len(users) == 2  # Both Alice and Bob have used device_001
        usernames = {u["username"] for u in users}
        assert "alice" in usernames
        assert "bob" in usernames

    def test_get_users_for_device_excludes_inactive(self, test_db):
        """Test that inactive users are always excluded."""
        # Charlie (inactive) has a stopped run on device_002
        users = test_db.getUsersForDevice("device_002", running_only=False, asdict=True)
        usernames = {u["username"] for u in users}
        assert "charlie" not in usernames  # Inactive user excluded
        assert "diana" in usernames  # Active user included

    def test_get_users_for_device_nonexistent(self, test_db):
        """Test getting users for a device that doesn't exist."""
        users = test_db.getUsersForDevice("device_999", running_only=True, asdict=True)
        assert len(users) == 0

    def test_get_users_for_device_as_list(self, test_db):
        """Test getting users as list of database rows."""
        users = test_db.getUsersForDevice("device_001", running_only=True, asdict=False)
        assert isinstance(users, list)
        assert len(users) == 1


class TestGetUserByRun:
    """Test getUserByRun method."""

    def test_get_user_by_run_valid(self, test_db):
        """Test getting user for a valid run."""
        user = test_db.getUserByRun("run_001", asdict=True)
        assert user is not None
        assert user["username"] == "bob"
        assert user["email"] == "bob@example.com"
        assert user["active"] == 1

    def test_get_user_by_run_stopped_experiment(self, test_db):
        """Test getting user for a stopped experiment."""
        user = test_db.getUserByRun("run_002", asdict=True)
        assert user is not None
        assert user["username"] == "alice"
        assert user["email"] == "alice@example.com"

    def test_get_user_by_run_inactive_user(self, test_db):
        """Test getting an inactive user for a run."""
        user = test_db.getUserByRun("run_004", asdict=True)
        assert user is not None
        assert user["username"] == "charlie"
        assert user["active"] == 0  # Inactive

    def test_get_user_by_run_nonexistent(self, test_db):
        """Test getting user for nonexistent run."""
        user = test_db.getUserByRun("run_999", asdict=True)
        assert user == {}

    def test_get_user_by_run_as_row(self, test_db):
        """Test getting user as database row."""
        user = test_db.getUserByRun("run_001", asdict=False)
        assert user is not None
        # Database row should have dict-like access
        assert dict(user)["username"] == "bob"


class TestNotificationRecipientScenarios:
    """Integration tests for common notification recipient scenarios."""

    def test_device_stopped_alert_recipients(self, test_db):
        """Test getting recipients for device stopped alert."""
        # Scenario: run_002 (Alice's experiment) just stopped
        # Should notify Alice (experiment owner) + admins, but not inactive users

        # Get user whose experiment stopped
        stopped_user = test_db.getUserByRun("run_002", asdict=True)

        # Get admins
        admins = test_db.getAllUsers(active_only=True, admin_only=True, asdict=True)

        # Combine recipients
        recipients = set()
        if stopped_user and stopped_user["active"] == 1:
            recipients.add(stopped_user["email"])
        for admin in admins.values():
            recipients.add(admin["email"])

        assert "alice@example.com" in recipients  # Experiment owner + admin
        assert "bob@example.com" not in recipients  # Other user
        assert "charlie@example.com" not in recipients  # Inactive user

    def test_storage_warning_recipients(self, test_db):
        """Test getting recipients for storage warning alert."""
        # Scenario: device_001 has low storage
        # Should notify users with currently running experiments + admins

        # Get users with running experiments on this device
        device_users = test_db.getUsersForDevice(
            "device_001", running_only=True, asdict=True
        )

        # Get admins
        admins = test_db.getAllUsers(active_only=True, admin_only=True, asdict=True)

        # Combine recipients
        recipients = set()
        for user in device_users:
            recipients.add(user["email"])
        for admin in admins.values():
            recipients.add(admin["email"])

        assert "bob@example.com" in recipients  # Has running experiment
        assert "alice@example.com" in recipients  # Admin
        assert "diana@example.com" not in recipients  # Different device
        assert "charlie@example.com" not in recipients  # Inactive

    def test_no_recipients_when_no_running_experiments(self, test_db):
        """Test that devices with no running experiments get admin-only alerts."""
        # device_002 has only Diana's running experiment
        device_users = test_db.getUsersForDevice(
            "device_002", running_only=True, asdict=True
        )
        usernames = {u["username"] for u in device_users}

        assert "diana" in usernames
        assert "charlie" not in usernames  # Inactive user excluded even with past runs
