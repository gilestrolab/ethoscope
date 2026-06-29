"""Bottle wiring around :class:`IncubatorRoutes`.

This is the only module in the subpackage that imports ``bottle``. It exposes
:func:`make_app` which returns a freshly-built ``bottle.Bottle()`` configured
with the standalone-friendly routes and (optionally) a static-file route for
the SPA under ``web/``.
"""

from __future__ import annotations

import os
from typing import Any

import bottle

from ethoscope_node.incubators.routes import IncubatorRoutes

_WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


def _json_body() -> dict[str, Any]:
    try:
        return bottle.request.json or {}
    except Exception:
        return {}


def make_app(routes: IncubatorRoutes, *, serve_static: bool = True) -> bottle.Bottle:
    """Build a Bottle app bound to the given :class:`IncubatorRoutes`."""
    app = bottle.Bottle()

    @app.get("/api/incubators")
    def _list_merged():
        return routes.list_merged()

    @app.get("/api/incubators/live")
    def _list_live():
        return routes.list_live()

    @app.get("/api/incubators/<name>/telemetry")
    def _telemetry(name):
        return routes.get_telemetry(name)

    @app.post("/api/incubators")
    def _add():
        return routes.add(_json_body())

    @app.put("/api/incubators/<name>")
    def _update(name):
        return routes.update(name, _json_body())

    @app.delete("/api/incubators/<name>")
    def _delete(name):
        return routes.delete(name)

    @app.post("/api/incubators/<name>/bind")
    def _bind(name):
        body = _json_body()
        return routes.bind(name, body.get("hostname"))

    @app.post("/api/incubators/<name>/push")
    def _push(name):
        return routes.push_schedule(name)

    @app.post("/api/incubators/<name>/reset-anchor")
    def _reset_anchor(name):
        return routes.reset_anchor(name)

    @app.post("/api/incubators/<name>/light-override")
    def _light_override(name):
        body = _json_body()
        try:
            pct = int(body.get("pct", 0))
        except (TypeError, ValueError):
            bottle.response.status = 400
            return {"result": "error", "message": "pct must be an integer 0-100"}
        return routes.light_override(name, pct)

    if serve_static and os.path.isdir(_WEB_DIR):

        @app.get("/")
        def _index():
            return bottle.static_file("index.html", root=_WEB_DIR)

        @app.get("/<filename:path>")
        def _static(filename):
            return bottle.static_file(filename, root=_WEB_DIR)

    return app
