"""
Incubator API Module — node-side bridge.

After Phase 2 this is a thin wrapper over
:class:`ethoscope_node.incubators.routes.IncubatorRoutes` — all the actual
logic (merged view, schedule push, drift reconciliation, fade timing,
T-cycle algorithm) lives in the self-contained ``incubators`` subpackage so
the same code path also powers the standalone ``ethoscope-incubator-server``
deployment.

Endpoints kept identical to Phase 1 for frontend compatibility:

* ``GET  /incubators/live`` — live telemetry of discovered units
* ``GET  /incubators/merged`` — joined DB records + live units
* ``POST /incubator/bind`` — bind/unbind a record to a physical unit

Added in Phase 2:

* ``POST /incubator/push-schedule`` — manual re-push for the "Push now" UI
* ``GET  /incubator/<name>/telemetry`` — proxied firmware ``/telemetry``
"""

from __future__ import annotations

from ethoscope_node.api.base import BaseAPI, error_decorator
from ethoscope_node.api.incubator_storage_adapter import (
    ExperimentalDBIncubatorStorage,
)
from ethoscope_node.incubators.firmware_client import IncubatorFirmwareClient
from ethoscope_node.incubators.routes import IncubatorRoutes


class IncubatorAPI(BaseAPI):
    """Bridges incubator routes onto the node's existing CherryPy/Bottle app."""

    def __init__(self, server_instance):
        super().__init__(server_instance)
        self._client = IncubatorFirmwareClient()
        # Adapter exists as long as the API does — ExperimentalDB is a singleton
        # multiprocessing.Process owned by the server.
        self._storage = (
            ExperimentalDBIncubatorStorage(self.database) if self.database else None
        )
        self._routes = (
            IncubatorRoutes(self._storage, self.incubator_scanner, self._client)
            if self._storage is not None
            else None
        )

    def register_routes(self):
        self.app.route("/incubators/live", method="GET")(self._get_incubators_live)
        self.app.route("/incubators/merged", method="GET")(self._get_incubators_merged)
        self.app.route("/incubator/bind", method="POST")(self._bind_incubator)
        self.app.route("/incubator/push-schedule", method="POST")(self._push_schedule)
        self.app.route("/incubator/<name>/telemetry", method="GET")(self._get_telemetry)

    # --- read endpoints ----------------------------------------------------------

    @error_decorator
    def _get_incubators_live(self):
        if self._routes is None:
            return {}
        return self._routes.list_live()

    @error_decorator
    def _get_incubators_merged(self):
        if self._routes is None:
            return {}
        return self._routes.list_merged()

    @error_decorator
    def _get_telemetry(self, name):
        if self._routes is None:
            return {"result": "error", "message": "Database unavailable"}
        return self._routes.get_telemetry(name)

    # --- write endpoints ---------------------------------------------------------

    def _bind_incubator(self):
        """Bind a DB incubator record to a physical unit by hostname.

        Wraps :meth:`IncubatorRoutes.bind` so the existing frontend continues
        to POST ``{"name": ..., "hostname": ...}`` to the same URL.
        """
        if self._routes is None:
            return {"result": "error", "message": "Database unavailable"}

        data = self.get_request_json()
        name = (data.get("name") or "").strip()
        if not name:
            return {"result": "error", "message": "Incubator name is required"}
        return self._routes.bind(name, data.get("hostname"))

    def _push_schedule(self):
        """Manually push the DB schedule to the firmware of a bound unit."""
        if self._routes is None:
            return {"result": "error", "message": "Database unavailable"}

        data = self.get_request_json()
        name = (data.get("name") or "").strip()
        if not name:
            return {"result": "error", "message": "Incubator name is required"}
        return self._routes.push_schedule(name)

    # --- helper exposed for setup_api auto-push ---------------------------------

    def push_schedule_to_unit(self, name: str) -> bool:
        """Best-effort schedule push, called from setup_api after writes.

        Returns ``True`` when the push actually completed against an online
        unit. Returns ``False`` silently when the record is unbound or the
        unit is offline — the reconciler will catch up on the next tick.
        """
        if self._routes is None:
            return False
        return self._routes._maybe_push(name)
