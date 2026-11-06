"""
Tests for the node server's index route (scripts/server.py, EthoscopeNodeServer._index).

The route is called on a stand-in object, so no server, scanner or configuration file is created.
"""

import importlib.util
import logging
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import bottle
import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "server.py"
_spec = importlib.util.spec_from_file_location("node_server_script", _MODULE_PATH)
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


def _bind_request(query=""):
    """
    Bind bottle's thread-local request to a minimal GET / environment.

    Args:
        query (str): The query string.
    """
    bottle.request.bind(
        {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/",
            "QUERY_STRING": query,
            "SCRIPT_NAME": "",
            "HTTP_HOST": "node",
            "wsgi.url_scheme": "http",
        }
    )


def _node(is_setup_required):
    """
    Build a stand-in server carrying only what _index uses.

    Args:
        is_setup_required (Callable[[], bool]): The configuration's setup check.

    Returns:
        SimpleNamespace: An object with ``config`` and ``logger``.
    """
    config = SimpleNamespace(is_setup_required=is_setup_required)
    return SimpleNamespace(config=config, logger=logging.getLogger("test_server_index"))


def test_index_redirects_to_wizard_when_setup_required():
    """A node that needs setup sends / to the installation wizard, without a redirect loop."""
    _bind_request()
    with pytest.raises(bottle.HTTPResponse) as raised:
        server.EthoscopeNodeServer._index(_node(lambda: True))

    assert raised.value.status_code in (302, 303)
    target = urlsplit(raised.value.get_header("Location"))
    # Browsers do not send the fragment: a target path of "/" would come back here forever.
    assert target.path == "/installation-wizard"
    assert target.fragment == "!/installation-wizard"


def test_index_does_not_redirect_with_reconfigure():
    """?reconfigure=true serves the page even when setup is required."""
    _bind_request("reconfigure=true")
    response = server.EthoscopeNodeServer._index(_node(lambda: True))

    assert response.status_code not in (302, 303)


def test_index_serves_page_when_setup_check_fails():
    """An error while checking setup serves the page instead of failing."""

    def broken():
        raise RuntimeError("database unavailable")

    _bind_request()
    response = server.EthoscopeNodeServer._index(_node(broken))

    assert response.status_code not in (302, 303)
