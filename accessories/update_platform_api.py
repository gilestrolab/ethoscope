#!/usr/bin/env python3
"""
Client for the ethoscope update server API, and the rules for reading its answers.

``src/updater/update_server.py`` runs on the node and on every ethoscope and
exposes the endpoints the web updater uses. This module wraps them, and carries
the two judgements that decide what a command line updater is allowed to do: how
to classify a machine's update state, and whether it may be disturbed at all.

Both rules are deliberate copies of the ones in
``src/updater/static/js/script.js`` so that the CLI and the web page agree on
what "out of date" and "busy" mean.

Only the standard library is used, so this runs unchanged on the node, on an
ethoscope, or on a workstation pointed at a remote node.
"""

import fnmatch
import json
import urllib.error
import urllib.request

# Statuses the web interface allows an update to be launched against. Anything
# else -- in particular the busy states below, and "Unreachable" -- is refused.
UPDATABLE_STATES = ("stopped", "NA", "Software broken")

# A device mid-experiment must never be disturbed, whatever the flags say.
BUSY_STATES = ("running", "recording", "streaming")

STATE_LABELS = {
    "unknown": "unknown",
    "outdated": "outdated",
    "stale": "restart needed",
    "current": "up to date",
}

# The node runs a live `git fetch` against every device to answer /devices, which
# on a fleet of thirty Pis regularly takes a couple of minutes.
SCAN_TIMEOUT = 600
GROUP_TIMEOUT = 900
BARE_TIMEOUT = 300


class UpdaterError(Exception):
    """The update server could not be reached, or answered with an error."""


class UpdateServer:
    """Thin JSON client for the update server API."""

    def __init__(self, host: str, port: int = 8888):
        """
        Args:
            host (str): hostname or IP of the machine running the update server.
            port (int): port the update server listens on.
        """
        self.base = f"http://{host}:{port}"

    def _request(self, path, payload=None, timeout=30):
        url = self.base + path
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url=url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as f:
                body = f.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise UpdaterError(f"{url}: {e}") from e

        try:
            answer = json.loads(body)
        except ValueError as e:
            raise UpdaterError(f"{url}: response was not JSON") from e

        # Reason: bottle catches server-side exceptions and returns them as a 200
        # carrying an "error" key, so an HTTP status check alone would miss them.
        if isinstance(answer, dict) and "error" in answer:
            raise UpdaterError(f"{url}: {last_line(answer['error'])}")
        return answer

    def get(self, path, timeout=30):
        """Perform a GET and return the decoded JSON body."""
        return self._request(path, timeout=timeout)

    def post(self, path, payload, timeout=30):
        """Perform a POST of ``payload`` as JSON and return the decoded body."""
        return self._request(path, payload=payload, timeout=timeout)

    def alive(self, timeout=5) -> bool:
        """Return True if the update server answers /id."""
        try:
            return "id" in self.get("/id", timeout=timeout)
        except UpdaterError:
            return False

    def refresh_bare_repo(self, timeout=BARE_TIMEOUT) -> list:
        """
        Fetch the node's bare repository from its remote.

        Returns:
            list: names of the branches that were refreshed.
        """
        answer = self.get("/bare/update", timeout=timeout)
        return sorted(answer) if isinstance(answer, dict) else []

    def scan_devices(self, timeout=SCAN_TIMEOUT) -> list:
        """
        Ask the node for the state of every ethoscope it knows about.

        Returns:
            list: device entries, sorted by name.
        """
        devices_map = self.get("/devices", timeout=timeout)
        return sorted(
            devices_map.values(), key=lambda d: str(d.get("name") or d.get("id"))
        )

    def node_state(self, timeout=BARE_TIMEOUT) -> dict:
        """
        Describe the node itself in the same shape as a device entry.

        Returns:
            dict: the node's ip, status, branch and commit information.
        """
        node = dict(self.get("/node_info", timeout=30))
        node.update(self.get("/device/check_update/node", timeout=timeout))
        try:
            node.update(self.get("/device/active_branch/node", timeout=30))
        except UpdaterError:
            # Cosmetic only: the branch is shown in the table, nothing depends on it.
            pass
        node["name"] = "node"
        return node

    def group_update(self, entries, timeout=GROUP_TIMEOUT) -> tuple:
        """
        Fire ``POST /group/update`` and pull out whatever the node reported as failed.

        The node returns each device's own reply verbatim and a successful reply
        carries no device id, so only failures can be attributed here. Whether an
        update truly landed is settled by re-scanning, not by this response.

        Args:
            entries (list): device dicts, each needing at least 'id' and 'ip'.
            timeout (int): seconds to wait for the whole batch.

        Returns:
            tuple: (responses, failures) with failures as (device_id, message).
        """
        payload = {"devices": [{"id": d["id"], "ip": d["ip"]} for d in entries]}
        answer = self.post("/group/update", payload, timeout=timeout)
        responses = answer.get("response", []) if isinstance(answer, dict) else []

        failures = []
        for item in responses:
            if not isinstance(item, dict):
                continue
            if item.get("status") == "error" or "error" in item:
                failures.append(
                    (
                        item.get("device_id", "<unattributed>"),
                        last_line(item.get("error", "unknown error")),
                    )
                )
        return responses, failures


def last_line(value) -> str:
    """Reduce a traceback or message to its last, most informative line."""
    text = str(value).strip()
    return text.splitlines()[-1] if text else "unknown error"


def device_state(device: dict) -> str:
    """
    Classify a device (or the node) exactly as the web interface does.

    ``up_to_date`` describes the git checkout on disk; ``version`` is the commit
    the *running* process was started from. A device that was pulled but never
    restarted is therefore current on disk and stale in memory, and needs a
    restart rather than another pull.

    Args:
        device (dict): one entry of the device map.

    Returns:
        str: one of 'unknown', 'outdated', 'stale', 'current'.
    """
    if device.get("up_to_date") is None:
        return "unknown"
    if device["up_to_date"] is False:
        return "outdated"

    on_disk = (device.get("local_commit") or {}).get("id")
    running = (device.get("version") or {}).get("id")
    if on_disk and running and on_disk != running:
        return "stale"
    return "current"


def eligibility(device: dict, force: bool = False) -> tuple:
    """
    Decide whether a device may be updated now, and say why not when it may not.

    Args:
        device (dict): one entry of the device map.
        force (bool): also update devices that already look current. This never
            overrides the busy check -- a tracking device is left alone regardless.

    Returns:
        tuple: (eligible, reason). ``reason`` is the update state when eligible,
        and a human readable explanation when not.
    """
    status = device.get("status")

    if status in BUSY_STATES:
        return False, f"busy: {status}"
    if status not in UPDATABLE_STATES:
        return False, f"not updatable: {status}"

    state = device_state(device)
    if state == "current" and not force:
        return False, "already up to date"
    return True, state


def matches(device: dict, patterns) -> bool:
    """Return True if the device name or id matches any of the glob patterns."""
    candidates = [str(device.get("name") or ""), str(device.get("id") or "")]
    return any(
        fnmatch.fnmatch(c.lower(), p.lower()) for c in candidates for p in patterns
    )


def short(commit) -> str:
    """Render a commit dict as a short sha, or '-' when absent."""
    return ((commit or {}).get("id") or "-")[:8]
