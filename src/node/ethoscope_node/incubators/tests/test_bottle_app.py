"""Smoke tests for the Bottle wiring and the standalone CLI entry point.

These exercise the routes through ``webtest`` if available, otherwise via
the ``bottle.Bottle.match`` API directly. We do NOT spin up a real socket
server.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import bottle
import pytest

from ethoscope_node.incubators import standalone
from ethoscope_node.incubators.bottle_app import make_app
from ethoscope_node.incubators.routes import IncubatorRoutes
from ethoscope_node.incubators.storage import SQLiteIncubatorStorage


@pytest.fixture
def routes(tmp_path):
    storage = SQLiteIncubatorStorage(str(tmp_path / "smoke.db"))
    scanner = MagicMock()
    scanner.get_all_devices_info.return_value = {}
    client = MagicMock()
    return IncubatorRoutes(storage, scanner, client)


def _call(app, method, path, body=None):
    """Invoke a Bottle route via a minimal-but-spec-correct WSGI environ."""
    import io
    from wsgiref.util import setup_testing_defaults

    environ: dict = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path

    if body is not None:
        encoded = json.dumps(body).encode()
        environ["CONTENT_TYPE"] = "application/json"
        environ["CONTENT_LENGTH"] = str(len(encoded))
        environ["wsgi.input"] = io.BytesIO(encoded)
    else:
        environ.setdefault("wsgi.input", io.BytesIO(b""))

    environ.setdefault("wsgi.errors", io.StringIO())

    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = headers
        return lambda data: None

    # Surface route errors in tests instead of Bottle's 500 catchall.
    app.catchall = False
    chunks = app(environ, start_response)
    body_bytes = b"".join(chunks) if chunks else b""
    return captured.get("status", "200"), body_bytes


def test_list_merged_route(routes):
    app = make_app(routes, serve_static=False)
    routes._storage.add({"name": "Inc1"})
    status, body = _call(app, "GET", "/api/incubators")
    assert status.startswith("200")
    parsed = json.loads(body)
    assert "Inc1" in parsed


def test_add_route(routes):
    app = make_app(routes, serve_static=False)
    status, body = _call(app, "POST", "/api/incubators", {"name": "Inc1"})
    assert status.startswith("200")
    parsed = json.loads(body)
    assert parsed["result"] == "success"
    assert routes._storage.get(name="Inc1") is not None


def test_update_route(routes):
    routes._storage.add({"name": "Inc1"})
    app = make_app(routes, serve_static=False)
    status, body = _call(app, "PUT", "/api/incubators/Inc1", {"location": "X"})
    assert status.startswith("200")
    assert routes._storage.get(name="Inc1")["location"] == "X"


def test_delete_route(routes):
    routes._storage.add({"name": "Inc1"})
    app = make_app(routes, serve_static=False)
    status, _ = _call(app, "DELETE", "/api/incubators/Inc1")
    assert status.startswith("200")
    assert routes._storage.get(name="Inc1") is None


def test_static_route_serves_index(routes, tmp_path):
    app = make_app(routes)
    status, body = _call(app, "GET", "/")
    # Either 200 (web/ exists) or 404 (web/ missing). The shipped package
    # bundles web/, so it should be a 200 with HTML content.
    assert status.startswith("200")
    assert b"Smart Incubators" in body or b"<html" in body.lower()


def test_bind_route_calls_routes(routes):
    routes._storage.add({"name": "Inc1"})
    routes._scanner.get_device_by_hostname.return_value = None  # offline
    app = make_app(routes, serve_static=False)
    status, body = _call(
        app, "POST", "/api/incubators/Inc1/bind", {"hostname": "incubator-7"}
    )
    assert status.startswith("200")
    assert routes._storage.get(name="Inc1")["hostname"] == "incubator-7"


def test_light_override_validates_pct(routes):
    routes._storage.add({"name": "Inc1", "hostname": "incubator-1"})
    app = make_app(routes, serve_static=False)
    status, body = _call(
        app, "POST", "/api/incubators/Inc1/light-override", {"pct": "not-a-number"}
    )
    assert status.startswith("400")
    parsed = json.loads(body)
    assert parsed["result"] == "error"


def test_web_directory_is_packaged():
    """The shipped tree must include the SPA so it works after `pip install`."""
    web_dir = os.path.join(
        os.path.dirname(standalone.__file__),
        "web",
    )
    assert os.path.isfile(os.path.join(web_dir, "index.html"))
    assert os.path.isfile(os.path.join(web_dir, "app.js"))
    assert os.path.isfile(os.path.join(web_dir, "style.css"))


def test_standalone_main_wires_dependencies(tmp_path):
    """``main()`` should set up storage/scanner/reconciler and start Bottle.

    We patch out ``bottle.run`` to avoid actually opening a socket, and patch
    the scanner so it doesn't try to talk to mDNS in the test environment.
    """
    db_path = str(tmp_path / "main.db")
    with (
        patch("bottle.run") as run_mock,
        patch("ethoscope_node.incubators.standalone.IncubatorScanner") as scanner_cls,
    ):
        scanner_cls.return_value.start = MagicMock()
        scanner_cls.return_value.stop = MagicMock()
        scanner_cls.return_value.get_all_devices_info.return_value = {}

        rc = standalone.main(
            [
                "--port",
                "0",  # ephemeral
                "--db-path",
                db_path,
                "--no-reconcile",
            ]
        )

    assert rc == 0
    run_mock.assert_called_once()
    assert os.path.exists(db_path)
