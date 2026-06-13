"""
Incubator API Module

Exposes live status of WiFi smart incubators (discovered via mDNS ``_incubator._tcp`` and
polled by :class:`IncubatorScanner`) and merges it with the configured incubator records in
the database. Phase 1 is monitor-only: the only write is binding a DB record to a physical
unit (which also pushes the incubator name into the unit's sensor ``location`` so its
readings group under that incubator).
"""

from .base import BaseAPI, error_decorator


class IncubatorAPI(BaseAPI):
    """API endpoints for live incubator monitoring and binding."""

    def register_routes(self):
        """Register incubator-related routes."""
        self.app.route("/incubators/live", method="GET")(self._get_incubators_live)
        self.app.route("/incubators/merged", method="GET")(self._get_incubators_merged)
        self.app.route("/incubator/bind", method="POST")(self._bind_incubator)

    @error_decorator
    def _get_incubators_live(self):
        """Return live telemetry for all discovered WiFi incubators (keyed by hostname)."""
        if not self.incubator_scanner:
            return {}
        return self.incubator_scanner.get_all_devices_info() or {}

    @error_decorator
    def _get_incubators_merged(self):
        """Merge configured incubators (DB) with live discovered units.

        Joined on ``hostname``. Each entry gets a ``source`` field
        ('configured', 'discovered', or 'both') and, when a live unit is present,
        its telemetry plus an online/offline ``live_status``.
        """
        from ethoscope_node.utils.etho_db import ExperimentalDB

        # Live discovered units, keyed by their derived hostname (incubator-<id>).
        discovered = {}
        if self.incubator_scanner:
            for _id, info in (self.incubator_scanner.get_all_devices_info() or {}).items():
                hostname = info.get("hostname") or _id
                discovered[hostname] = info

        # Configured incubators from the DB, keyed by name.
        try:
            db = ExperimentalDB()
            configured = db.getAllIncubators(active_only=False, asdict=True) or {}
        except Exception as e:
            self.logger.error(f"Error getting incubators from database: {e}")
            configured = {}

        merged = {}

        # Configured incubators first; attach live telemetry if bound + online.
        for name, cfg in configured.items():
            entry = dict(cfg)
            hostname = cfg.get("hostname")
            live = discovered.pop(hostname, None) if hostname else None
            if live is not None:
                entry.update(self._live_fields(live))
                entry["source"] = "both"
            else:
                entry["source"] = "configured"
                entry["live_status"] = "offline" if hostname else "unbound"
            merged[name] = entry

        # Remaining discovered-but-unbound units (no DB record references them).
        for hostname, live in discovered.items():
            entry = {
                "name": hostname,
                "hostname": hostname,
                "source": "discovered",
            }
            entry.update(self._live_fields(live))
            merged[hostname] = entry

        return merged

    @staticmethod
    def _live_fields(live: dict) -> dict:
        """Pick the telemetry fields the frontend status block needs from a live unit."""
        status = live.get("status", "offline")
        return {
            "ip": live.get("ip", ""),
            "live_status": status,
            "node_id": live.get("node_id"),
            "fw": live.get("fw", ""),
            "temperature": live.get("temperature"),
            "humidity": live.get("humidity"),
            "lux": live.get("lux"),
            "set_temp": live.get("set_temp"),
            "mode": live.get("mode"),
            "light_level": live.get("light_level"),
            "peltier_duty": live.get("peltier_duty"),
            "peltier_dir": live.get("peltier_dir"),
            "fan_on": live.get("fan_on"),
            "sensor_fault": live.get("sensor_fault"),
            "rssi": live.get("rssi"),
            "last_seen": live.get("last_seen", ""),
        }

    def _bind_incubator(self):
        """Bind a DB incubator record to a physical unit and align its sensor location.

        Body: ``{"name": <incubator name>, "hostname": <incubator-<id> or null>}``.
        Stores the hostname on the record; if non-null and the unit is online, pushes the
        incubator name into its sensor ``location`` (best-effort).
        """
        from ethoscope_node.utils.etho_db import ExperimentalDB

        data = self.get_request_json()
        name = (data.get("name") or "").strip()
        if not name:
            return {"result": "error", "message": "Incubator name is required"}

        # hostname may be explicitly null to unbind.
        hostname = data.get("hostname")
        if hostname is not None:
            hostname = str(hostname).strip() or None

        try:
            db = ExperimentalDB()
            result = db.updateIncubator(name=name, hostname=hostname)
            if result < 0:
                return {"result": "error", "message": "Failed to bind incubator"}
        except Exception as e:
            self.logger.error(f"Error binding incubator '{name}': {e}")
            return {"result": "error", "message": str(e)}

        # Best-effort: keep the unit's sensor location equal to its incubator name.
        location_pushed = False
        if hostname and self.incubator_scanner:
            try:
                self.incubator_scanner.set_location(hostname, name)
                location_pushed = True
            except Exception as e:
                self.logger.warning(
                    f"Bound {name} -> {hostname} but could not push location: {e}"
                )

        return {
            "result": "success",
            "message": f"Incubator '{name}' bound to {hostname or 'nothing'}",
            "location_pushed": location_pushed,
        }
