"""
Unit tests for the PIN policy of the node.

PINs are required only while authentication is on, and authentication can be
turned on only once an active administrator has a PIN. Covers check_new_pin(),
ExperimentalDB.has_admin_with_pin(), the guard in
EthoscopeConfiguration.update_authentication_config(), the users-page path
EthoscopeConfiguration.add_user(), and that an empty PIN never logs anyone in.
All databases and config files live in pytest's tmp_path.
"""

import logging
from unittest.mock import Mock, patch

import pytest

from ethoscope_node.utils.configuration import (
    ADMIN_PIN_REQUIRED_MESSAGE,
    PIN_REQUIRED_MESSAGE,
    EthoscopeConfiguration,
    check_new_pin,
)

DB_CLASS = "ethoscope_node.utils.etho_db.ExperimentalDB"


@pytest.fixture
def db(users_db):
    """
    Alias the shared temporary users database (see tests/conftest.py).

    Args:
        users_db (ExperimentalDB): Empty users table under tmp_path.

    Returns:
        ExperimentalDB: The temporary database.
    """
    return users_db


def make_config(tmp_path, auth_enabled: bool) -> EthoscopeConfiguration:
    """
    Build a configuration object backed by a file in tmp_path.

    Args:
        tmp_path (Path): pytest temporary directory.
        auth_enabled (bool): Initial authentication switch.

    Returns:
        EthoscopeConfiguration: The configuration, without touching /etc.
    """
    config = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
    config._config_file = tmp_path / "ethoscope.conf"
    config._settings = {"authentication": {"enabled": auth_enabled}}
    config._logger = logging.getLogger("test_pin_policy")
    return config


def add_user(db, username: str, pin: str = "", isadmin: int = 0, active: int = 1):
    """
    Insert a user row.

    Args:
        db (ExperimentalDB): Target database.
        username (str): Username; the email is derived from it.
        pin (str): Stored PIN.
        isadmin (int): 1 for an administrator.
        active (int): 1 for an active user.
    """
    db.addUser(
        username=username,
        email=f"{username}@lab.org",
        pin=pin,
        isadmin=isadmin,
        active=active,
    )


def stored_pin(db, username: str):
    """
    Read the raw stored PIN of a user.

    Args:
        db (ExperimentalDB): Database to read.
        username (str): User to look up.

    Returns:
        str | None: The pin column.
    """
    return db.getUserByName(username, asdict=True)["pin"]


class TestCheckNewPin:
    """The rule applied to PINs of new users."""

    def test_blank_pin_allowed_while_auth_off(self):
        """No PIN is needed while authentication is off."""
        assert check_new_pin("", auth_enabled=False) is None

    def test_blank_pin_refused_while_auth_on(self):
        """A new user must have a PIN while authentication is on."""
        assert check_new_pin("", auth_enabled=True) == PIN_REQUIRED_MESSAGE

    @pytest.mark.parametrize("auth_enabled", [False, True])
    def test_short_pin_refused_whenever_given(self, auth_enabled):
        """A PIN that is given keeps today's length check, auth on or off."""
        assert "at least 4" in check_new_pin("12", auth_enabled=auth_enabled)

    def test_valid_pin_accepted(self):
        """A four-character PIN passes."""
        assert check_new_pin("1234", auth_enabled=True) is None


class TestHasAdminWithPin:
    """ExperimentalDB.has_admin_with_pin decides whether auth may go on."""

    def test_no_users(self, db):
        """An empty node has no administrator who could log in."""
        assert db.has_admin_with_pin() is False

    @pytest.mark.parametrize("pin", ["", "   "])
    def test_admin_without_pin(self, db, pin):
        """An administrator with a blank PIN does not count."""
        add_user(db, "admin", pin=pin, isadmin=1)
        assert db.has_admin_with_pin() is False

    def test_inactive_admin_with_pin(self, db):
        """A deactivated administrator cannot log in, so does not count."""
        add_user(db, "admin", pin="1234", isadmin=1, active=0)
        assert db.has_admin_with_pin() is False

    def test_non_admin_with_pin(self, db):
        """A regular user with a PIN cannot administer the node."""
        add_user(db, "user", pin="1234", isadmin=0)
        assert db.has_admin_with_pin() is False

    def test_active_admin_with_pin(self, db):
        """One active administrator with a PIN is enough."""
        add_user(db, "user", pin="1234", isadmin=0)
        add_user(db, "admin", pin="5678", isadmin=1)
        assert db.has_admin_with_pin() is True


class TestEmptyPinNeverAuthenticates:
    """Users created without a PIN while auth was off cannot log in later."""

    def test_empty_stored_pin(self, db):
        """An empty stored PIN matches nothing, not even an empty attempt."""
        add_user(db, "alice", pin="", isadmin=1)

        assert db.verify_pin("alice", "") is False
        assert db.verify_pin("alice", "1234") is False
        assert db.authenticate_user("alice", "") is None

    def test_null_stored_pin(self, db):
        """A NULL PIN reads as empty and never as the string 'None'."""
        add_user(db, "alice", pin="", isadmin=1)
        db.executeSQL(
            f"UPDATE {db._users_table_name} SET pin = NULL WHERE username = 'alice'"
        )

        assert db.getAllUsers(asdict=True)["alice"]["PIN"] == ""
        assert db.verify_pin("alice", "None") is False
        assert db.verify_pin("alice", "") is False


class TestEnablingAuthentication:
    """update_authentication_config is the one place auth gets switched on."""

    def test_refused_without_admin_pin(self, db, tmp_path):
        """Turning auth on with no administrator PIN is refused, nothing saved."""
        add_user(db, "admin", pin="", isadmin=1)
        add_user(db, "user", pin="1234", isadmin=0)
        config = make_config(tmp_path, auth_enabled=False)

        with patch(DB_CLASS, return_value=db):
            with pytest.raises(ValueError) as exc_info:
                config.update_authentication_config({"enabled": True})

        assert str(exc_info.value) == ADMIN_PIN_REQUIRED_MESSAGE
        assert "Set a PIN for an administrator first" in str(exc_info.value)
        assert config._settings["authentication"]["enabled"] is False
        assert not config._config_file.exists()

    def test_allowed_with_admin_pin(self, db, tmp_path):
        """With an administrator PIN in place authentication goes on."""
        add_user(db, "admin", pin="1234", isadmin=1)
        config = make_config(tmp_path, auth_enabled=False)

        with patch(DB_CLASS, return_value=db):
            result = config.update_authentication_config({"enabled": True})

        assert result["enabled"] is True
        assert '"enabled": true' in config._config_file.read_text()

    def test_turning_off_needs_no_pin(self, tmp_path):
        """Switching auth off never consults the users."""
        config = make_config(tmp_path, auth_enabled=True)
        db_class = Mock()

        with patch(DB_CLASS, db_class):
            result = config.update_authentication_config({"enabled": False})

        assert result["enabled"] is False
        db_class.assert_not_called()


class TestUsersPageAddUser:
    """EthoscopeConfiguration.add_user serves the users page (node-actions)."""

    @staticmethod
    def userdata(name: str = "alice", **extra) -> dict:
        """
        Build the payload the users page posts.

        Args:
            name (str): Username.
            **extra: Fields to add or override.

        Returns:
            dict: The user data.
        """
        data = {"name": name, "fullname": name.title(), "email": f"{name}@lab.org"}
        data.update(extra)
        return data

    def test_create_without_pin_while_auth_off(self, db, tmp_path):
        """No PIN is needed to create a user while auth is off."""
        config = make_config(tmp_path, auth_enabled=False)

        with patch(DB_CLASS, return_value=db):
            result = config.add_user(self.userdata(PIN=None, isAdmin=True))

        assert result["result"] == "success"
        assert stored_pin(db, "alice") == ""

    def test_create_without_pin_while_auth_on(self, db, tmp_path):
        """While auth is on a new user without a PIN is refused."""
        config = make_config(tmp_path, auth_enabled=True)

        with patch(DB_CLASS, return_value=db):
            result = config.add_user(self.userdata(PIN=""))

        assert result == {"result": "error", "message": PIN_REQUIRED_MESSAGE}
        assert db.getUserByName("alice") == {}

    def test_create_with_short_pin(self, db, tmp_path):
        """A PIN that is given must still be at least 4 characters."""
        config = make_config(tmp_path, auth_enabled=False)

        with patch(DB_CLASS, return_value=db):
            result = config.add_user(self.userdata(PIN="12"))

        assert result["result"] == "error"
        assert "at least 4" in result["message"]

    def test_create_with_pin_while_auth_on(self, db, tmp_path):
        """While auth is on a user with a PIN is created as before."""
        config = make_config(tmp_path, auth_enabled=True)

        with patch(DB_CLASS, return_value=db):
            result = config.add_user(self.userdata(PIN="1234"))

        assert result["result"] == "success"
        assert db.verify_pin("alice", "1234") is True

    def test_update_with_blank_pin_keeps_it_while_auth_off(self, db, tmp_path):
        """A hidden (blank) PIN field never wipes the stored PIN."""
        add_user(db, "alice", pin="1234")
        user_id = db.getUserByName("alice", asdict=True)["id"]
        config = make_config(tmp_path, auth_enabled=False)

        with patch(DB_CLASS, return_value=db):
            result = config.add_user(
                self.userdata(id=user_id, PIN="", fullname="Alice Renamed")
            )

        assert result["result"] == "success"
        assert stored_pin(db, "alice") == "1234"
        assert db.getUserByName("alice", asdict=True)["fullname"] == "Alice Renamed"

    def test_update_with_blank_pin_refused_while_auth_on(self, db, tmp_path):
        """While auth is on, an update that would clear the PIN is refused."""
        add_user(db, "alice", pin="1234")
        user_id = db.getUserByName("alice", asdict=True)["id"]
        config = make_config(tmp_path, auth_enabled=True)

        with patch(DB_CLASS, return_value=db):
            result = config.add_user(self.userdata(id=user_id, PIN=""))

        assert result == {"result": "error", "message": PIN_REQUIRED_MESSAGE}
        assert stored_pin(db, "alice") == "1234"

    def test_update_without_pin_field_while_auth_on(self, db, tmp_path):
        """An update that does not mention the PIN leaves it alone."""
        add_user(db, "alice", pin="1234")
        user_id = db.getUserByName("alice", asdict=True)["id"]
        config = make_config(tmp_path, auth_enabled=True)

        with patch(DB_CLASS, return_value=db):
            result = config.add_user(self.userdata(id=user_id, active=False))

        assert result["result"] == "success"
        assert stored_pin(db, "alice") == "1234"
        assert db.getUserByName("alice", asdict=True)["active"] == 0
