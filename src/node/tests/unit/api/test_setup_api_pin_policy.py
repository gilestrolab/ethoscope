"""
Unit tests for the PIN policy as seen through the node's HTTP handlers.

While authentication is off no PIN is needed to create or edit users; while it
is on PINs behave as before. Authentication can be turned on (wizard step 7,
/setup/tunnel) only when an active administrator has a PIN, which that same
request may supply. The handlers run against a real configuration object and
a real database, both under pytest's tmp_path.
"""

import copy
import logging
from unittest.mock import Mock

import pytest

from ethoscope_node.api.auth_api import AuthAPI
from ethoscope_node.api.setup_api import SetupAPI
from ethoscope_node.utils.configuration import (
    ADMIN_PIN_REQUIRED_MESSAGE,
    PIN_REQUIRED_MESSAGE,
    EthoscopeConfiguration,
)


@pytest.fixture
def config(tmp_path):
    """
    Provide a default configuration saved under tmp_path, auth off.

    Args:
        tmp_path (Path): pytest temporary directory.

    Returns:
        EthoscopeConfiguration: The configuration.
    """
    cfg = EthoscopeConfiguration.__new__(EthoscopeConfiguration)
    cfg._config_file = tmp_path / "ethoscope.conf"
    cfg._settings = copy.deepcopy(EthoscopeConfiguration.DEFAULT_SETTINGS)
    cfg._logger = logging.getLogger("test_setup_api_pin_policy")
    return cfg


@pytest.fixture
def db(users_db, monkeypatch):
    """
    Route every ExperimentalDB() the handlers open to the temporary database.

    Args:
        users_db (ExperimentalDB): Empty users table under tmp_path.
        monkeypatch (MonkeyPatch): pytest monkeypatch fixture.

    Returns:
        ExperimentalDB: The temporary database.
    """
    for target in (
        "ethoscope_node.api.setup_api.ExperimentalDB",
        "ethoscope_node.utils.etho_db.ExperimentalDB",
    ):
        monkeypatch.setattr(target, lambda *args, **kwargs: users_db)
    return users_db


@pytest.fixture
def api(config, db):
    """
    Provide a SetupAPI wired to the temporary configuration and database.

    Args:
        config (EthoscopeConfiguration): Temporary configuration.
        db (ExperimentalDB): Temporary database.

    Returns:
        SetupAPI: The handler object.
    """
    server = Mock()
    server.config = config
    return SetupAPI(server)


def post(api, handler, payload: dict) -> dict:
    """
    Call a handler as if the payload had been POSTed to it.

    Args:
        api (BaseAPI): Handler object.
        handler (str): Name of the handler method.
        payload (dict): JSON body.

    Returns:
        dict: The handler's response.
    """
    api.get_request_json = lambda: payload
    return getattr(api, handler)()


def set_auth(config, enabled: bool):
    """
    Set the authentication switch directly, as a hand-edited config would.

    Args:
        config (EthoscopeConfiguration): Configuration to change.
        enabled (bool): New value.
    """
    config._settings["authentication"]["enabled"] = enabled


def add_user(db, username: str, pin: str = "", isadmin: int = 0):
    """
    Insert an active user row.

    Args:
        db (ExperimentalDB): Target database.
        username (str): Username; the email is derived from it.
        pin (str): Stored PIN.
        isadmin (int): 1 for an administrator.
    """
    db.addUser(username=username, email=f"{username}@lab.org", pin=pin, isadmin=isadmin)


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


ADMIN = {"username": "admin", "fullname": "Ada Admin", "email": "admin@lab.org"}
TUNNEL_OFF = {"tunnel_enabled": False}


class TestAdminUser:
    """POST /setup/admin-user (wizard step 3)."""

    def test_create_without_pin_while_auth_off(self, api, db):
        """The wizard's admin needs no PIN while authentication is off."""
        result = post(api, "_setup_admin_user", dict(ADMIN))

        assert result["result"] == "success"
        assert stored_pin(db, "admin") == ""

    def test_create_without_pin_while_auth_on(self, api, db, config):
        """While authentication is on the admin must get a PIN."""
        set_auth(config, True)

        result = post(api, "_setup_admin_user", dict(ADMIN, pin=""))

        assert result == {"result": "error", "message": PIN_REQUIRED_MESSAGE}
        assert db.getUserByName("admin") == {}

    def test_create_with_pin_while_auth_on(self, api, db, config):
        """While authentication is on a PIN is stored as before."""
        set_auth(config, True)

        result = post(api, "_setup_admin_user", dict(ADMIN, pin="1234"))

        assert result["result"] == "success"
        assert db.verify_pin("admin", "1234") is True

    def test_update_with_blank_pin_keeps_stored_pin(self, api, db):
        """Re-running the step with the PIN field hidden keeps the PIN."""
        add_user(db, "admin", pin="1234", isadmin=1)

        result = post(api, "_setup_admin_user", dict(ADMIN, pin=""))

        assert result["result"] == "success"
        assert stored_pin(db, "admin") == "1234"


class TestAddAndUpdateUser:
    """POST /setup/add-user and /setup/update-user (wizard step 4 modals)."""

    def test_add_without_pin_while_auth_off(self, api, db):
        """Additional users need no PIN while authentication is off."""
        result = post(
            api, "_setup_add_user", {"username": "bob", "email": "bob@lab.org"}
        )

        assert result["result"] == "success"
        assert stored_pin(db, "bob") == ""

    def test_add_without_pin_while_auth_on(self, api, db, config):
        """While authentication is on a user without a PIN is refused."""
        set_auth(config, True)

        result = post(
            api,
            "_setup_add_user",
            {"username": "bob", "email": "bob@lab.org", "pin": ""},
        )

        assert result == {"result": "error", "message": PIN_REQUIRED_MESSAGE}
        assert db.getUserByName("bob") == {}

    def test_update_with_blank_pin_while_auth_off(self, api, db):
        """Editing a user while auth is off leaves the stored PIN alone."""
        add_user(db, "bob", pin="1234")

        result = post(
            api,
            "_setup_update_user",
            {"original_username": "bob", "fullname": "Bob B", "pin": ""},
        )

        assert result["result"] == "success"
        assert stored_pin(db, "bob") == "1234"

    def test_update_with_blank_pin_while_auth_on(self, api, db, config):
        """While auth is on, clearing a PIN would lock the user out: refused."""
        add_user(db, "bob", pin="1234")
        set_auth(config, True)

        result = post(
            api, "_setup_update_user", {"original_username": "bob", "pin": ""}
        )

        assert result == {"result": "error", "message": PIN_REQUIRED_MESSAGE}
        assert stored_pin(db, "bob") == "1234"

    def test_update_with_new_pin_while_auth_on(self, api, db, config):
        """While auth is on a new PIN is stored as before."""
        add_user(db, "bob", pin="1234")
        set_auth(config, True)

        result = post(
            api, "_setup_update_user", {"original_username": "bob", "pin": "9876"}
        )

        assert result["result"] == "success"
        assert stored_pin(db, "bob") == "9876"


class TestTunnelStepEnablesAuthentication:
    """POST /setup/tunnel (wizard step 7) is where authentication goes on."""

    def test_refused_without_admin_pin(self, api, db, config):
        """No administrator PIN anywhere: refused, nothing switched on."""
        add_user(db, "admin", pin="", isadmin=1)
        add_user(db, "bob", pin="1234")
        payload = {
            "tunnel_enabled": True,
            "tunnel_mode": "custom",
            "token": "token123",
            "custom_domain": "lab.example.org",
            "authentication_enabled": True,
        }

        result = post(api, "_setup_tunnel", payload)

        assert result == {"result": "error", "message": ADMIN_PIN_REQUIRED_MESSAGE}
        assert config._settings["authentication"]["enabled"] is False
        # The tunnel must not be left open with authentication off.
        assert config._settings["tunnel"]["enabled"] is False

    def test_admin_pin_in_same_request(self, api, db, config):
        """The step's own PIN is stored on the admin, then auth goes on."""
        add_user(db, "admin", pin="", isadmin=1)
        payload = dict(
            TUNNEL_OFF,
            authentication_enabled=True,
            admin_username="admin",
            admin_pin="2468",
        )

        result = post(api, "_setup_tunnel", payload)

        assert result["result"] == "success"
        assert config._settings["authentication"]["enabled"] is True
        assert stored_pin(db, "admin").startswith("pbkdf2$")
        assert db.verify_pin("admin", "2468") is True

    def test_only_admin_used_when_username_missing(self, api, db, config):
        """With a single active administrator the username may be omitted."""
        add_user(db, "admin", pin="", isadmin=1)
        add_user(db, "bob", pin="")

        result = post(
            api,
            "_setup_tunnel",
            dict(TUNNEL_OFF, authentication_enabled=True, admin_pin="2468"),
        )

        assert result["result"] == "success"
        assert db.verify_pin("admin", "2468") is True

    def test_short_admin_pin_refused(self, api, db, config):
        """The step's PIN obeys the usual length check."""
        add_user(db, "admin", pin="", isadmin=1)

        result = post(
            api,
            "_setup_tunnel",
            dict(
                TUNNEL_OFF,
                authentication_enabled=True,
                admin_username="admin",
                admin_pin="12",
            ),
        )

        assert result["result"] == "error"
        assert "at least 4" in result["message"]
        assert stored_pin(db, "admin") == ""
        assert config._settings["authentication"]["enabled"] is False

    def test_pin_for_non_admin_refused(self, api, db, config):
        """The PIN must go to an active administrator, not any user."""
        add_user(db, "admin", pin="", isadmin=1)
        add_user(db, "bob", pin="")

        result = post(
            api,
            "_setup_tunnel",
            dict(
                TUNNEL_OFF,
                authentication_enabled=True,
                admin_username="bob",
                admin_pin="2468",
            ),
        )

        assert result == {
            "result": "error",
            "message": "bob is not an active administrator.",
        }
        assert stored_pin(db, "bob") == ""
        assert config._settings["authentication"]["enabled"] is False

    def test_existing_admin_pin_is_enough(self, api, db, config):
        """An administrator who already has a PIN needs no new one."""
        add_user(db, "admin", pin="1234", isadmin=1)

        result = post(
            api, "_setup_tunnel", dict(TUNNEL_OFF, authentication_enabled=True)
        )

        assert result["result"] == "success"
        assert config._settings["authentication"]["enabled"] is True
        assert stored_pin(db, "admin") == "1234"

    def test_turning_off_needs_no_pin(self, api, db, config):
        """Leaving authentication off never asks for a PIN."""
        set_auth(config, True)

        result = post(
            api, "_setup_tunnel", dict(TUNNEL_OFF, authentication_enabled=False)
        )

        assert result["result"] == "success"
        assert config._settings["authentication"]["enabled"] is False


class TestCompleteSetup:
    """POST /setup/complete refuses to finish into a locked-out node."""

    def test_refused_when_auth_on_without_admin_pin(self, api, db, config):
        """A hand-enabled auth with no admin PIN blocks completion."""
        add_user(db, "admin", pin="", isadmin=1)
        set_auth(config, True)

        result = post(api, "_complete_setup", {})

        assert result["result"] == "error"
        assert config._settings["setup"]["completed"] is False

    def test_completes_when_auth_off_without_pins(self, api, db, config):
        """With authentication off nobody needs a PIN to finish."""
        add_user(db, "admin", pin="", isadmin=1)

        result = post(api, "_complete_setup", {})

        assert result["result"] == "success"
        assert config._settings["setup"]["completed"] is True


class TestLoginAndSession:
    """/auth/login and /auth/session as seen by the frontend."""

    @pytest.fixture
    def auth_api(self, config):
        """
        Provide an AuthAPI with a mocked middleware.

        Args:
            config (EthoscopeConfiguration): Temporary configuration.

        Returns:
            AuthAPI: The handler object.
        """
        server = Mock()
        server.config = config
        server.app.auth_middleware.get_current_user.return_value = None
        return AuthAPI(server)

    def test_empty_pin_cannot_log_in(self, auth_api):
        """An empty PIN is refused before any credential check runs."""
        result = post(auth_api, "_login", {"username": "admin", "pin": "  "})

        assert result == {"success": False, "message": "PIN is required"}
        auth_api.app.auth_middleware.login_user.assert_not_called()

    @pytest.mark.parametrize("handler", ["_get_session", "_check_auth"])
    def test_session_reports_auth_off(self, auth_api, handler):
        """The frontend learns that authentication is off (PINs hidden)."""
        result = getattr(auth_api, handler)()

        assert result["auth_enabled"] is False
        assert result["authenticated"] is True

    @pytest.mark.parametrize("handler", ["_get_session", "_check_auth"])
    def test_session_reports_auth_on(self, auth_api, config, handler):
        """With auth on, the flag is set whether or not someone is logged in."""
        set_auth(config, True)

        result = getattr(auth_api, handler)()

        assert result["auth_enabled"] is True
        assert result["authenticated"] is False
