"""
Storage API Module

Lets a user reclaim space on an ethoscope by deleting runs the node has already
backed up. The node is the only party that can tell a backed-up run from one that is
not, because it holds the rsync copies; the device supplies the listing and performs
the deletion after validating it again.
"""

import threading

from ethoscope_node.utils.device_storage import (
    ACTION_ROOTS,
    assess_free_space,
    classify_run,
    summarise,
    thresholds_for,
)

from .base import BaseAPI, error_decorator

OUTDATED_FIRMWARE_ERROR = (
    "This ethoscope cannot report its stored data. It probably needs a software "
    "update before it can free space."
)

UNREACHABLE_ERROR = "This ethoscope is not currently reachable."


class StorageAPI(BaseAPI):
    """API endpoints for inspecting and reclaiming device storage."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Reason: a purge is a read-modify-write against the device; two overlapping
        # ones would verify against a listing the other has already invalidated.
        self._purge_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def register_routes(self):
        """Register storage-related routes."""
        self.app.route("/device/<id>/storage", method="GET")(self._get_device_storage)
        self.app.route("/device/<id>/storage/purge", method="POST")(
            self._purge_device_storage
        )

    def _node_dirs(self) -> dict[str, str]:
        """
        Return the node directories rsync mirrors each device root into.

        The backup daemon takes these from the configuration file
        (``rsync_backup_tool.py``), so read the same keys; fall back to the paths the
        server was started with.
        """
        dirs = {"results": self.results_dir, "videos": self.videos_dir}
        try:
            folders = self.config.content["folders"]
            dirs["results"] = folders["results"]["path"] or dirs["results"]
            dirs["videos"] = folders["video"]["path"] or dirs["videos"]
        except (AttributeError, KeyError, TypeError):
            self.logger.debug("Falling back to server data directories for storage")
        return dirs

    def _thresholds(self, action: str) -> dict:
        """
        The free-space gates for one kind of run.

        Read from the configuration's ``alerts`` section the same way
        :meth:`_node_dirs` reads ``folders``, falling back to the module defaults so
        an installation whose config predates these keys still gets a warning.
        """
        alerts = {}
        try:
            alerts = self.config.content["alerts"]
        except (AttributeError, KeyError, TypeError):
            self.logger.debug("No alerts configuration; using default storage gates")
        return thresholds_for(action, alerts)

    def _device(self, device_id: str):
        """
        Return the live device object, or None if the scanner does not have one.

        Reason: unlike the other device endpoints this one feeds a modal, so an
        unknown or offline device has to come back as a sentence the user can read
        rather than as the traceback ``validate_device_exists`` would produce.
        """
        if not self.device_scanner:
            return None
        return self.device_scanner.get_device(device_id)

    def _lock_for(self, device_id: str) -> threading.Lock:
        """Return the per-device purge lock, creating it on first use."""
        with self._locks_guard:
            return self._purge_locks.setdefault(device_id, threading.Lock())

    def _classified_listing(self, device) -> tuple[dict | None, dict]:
        """
        Fetch the device's runs and mark each one backed up or not.

        Returns:
            tuple: ``(listing, node_dirs)`` where listing is None if the device could
            not be reached or does not serve the route.
        """
        node_dirs = self._node_dirs()
        listing = device.list_runs()
        if not isinstance(listing, dict) or "runs" not in listing:
            return None, node_dirs

        listing = dict(listing)
        listing["runs"] = [
            classify_run(run, node_dirs) for run in listing.get("runs", [])
        ]
        return listing, node_dirs

    @error_decorator
    def _get_device_storage(self, id):
        """
        Report a device's disk usage and which of its runs can be deleted.

        With ``?action=tracking`` or ``?action=video`` the answer also carries a
        ``preflight`` assessment, which is what the web interface consults before
        starting a run. It is the same device call either way — the reclaimable
        figure the warning quotes only exists once every run has been classified —
        so this is one request, not two. Without a recognised ``action`` the
        response is unchanged, and the Free up space modal keeps using it as before.

        An unreachable or too-old device answers with a sentence, as the modal
        expects; the caller treats that as "no warning" and starts anyway.
        """
        device = self._device(id)
        if device is None:
            return {"error": UNREACHABLE_ERROR}

        listing, node_dirs = self._classified_listing(device)

        if listing is None:
            return {"error": OUTDATED_FIRMWARE_ERROR}

        runs = listing["runs"]
        totals = summarise(runs)
        disk = listing.get("disk", {})
        response = {
            "device_id": id,
            "disk": disk,
            "node_dirs": node_dirs,
            "runs": runs,
            "other": listing.get("other", {"files": 0, "size_bytes": 0}),
            "totals": totals,
        }

        action = self.get_query_param("action")
        if action in ACTION_ROOTS:
            response["preflight"] = assess_free_space(
                disk, totals, action, self._thresholds(action), runs
            )
        return response

    @error_decorator
    def _purge_device_storage(self, id):
        """
        Delete the requested runs, after re-verifying each against the node's copies.

        The client's list is never forwarded as given: the device is listed afresh and
        only paths that are still present and still backed up are sent on.
        """
        device = self._device(id)
        if device is None:
            return {"error": UNREACHABLE_ERROR}

        requested = self.get_request_json().get("runs", [])
        if not requested:
            return {"error": "No runs selected"}

        status = (device.info() or {}).get("status")
        if status != "stopped":
            return {"error": f"Refusing to delete data while the device is {status}"}

        with self._lock_for(id):
            listing, _ = self._classified_listing(device)
            if listing is None:
                return {"error": OUTDATED_FIRMWARE_ERROR}

            by_path = {run.get("path"): run for run in listing["runs"]}
            verified, skipped = [], []
            for path in requested:
                run = by_path.get(path)
                if run is None:
                    skipped.append(
                        {"path": path, "reason": "No longer present on the device"}
                    )
                elif not run.get("backed_up"):
                    skipped.append({"path": path, "reason": run.get("reason", "")})
                else:
                    verified.append(path)

            if not verified:
                return {
                    "deleted": [],
                    "skipped": skipped,
                    "freed_bytes": 0,
                    "disk": listing.get("disk", {}),
                }

            self.logger.info(f"Deleting {len(verified)} backed-up run(s) on {id}")
            result = device.remove_runs(verified)

        if not isinstance(result, dict):
            return {"error": "The ethoscope did not confirm the deletion"}

        skipped.extend(
            {"path": f.get("path"), "reason": f.get("error", "")}
            for f in result.get("failed", [])
        )
        return {
            "deleted": result.get("removed", []),
            "skipped": skipped,
            "freed_bytes": result.get("freed_bytes", 0),
            "disk": result.get("disk", {}),
        }
