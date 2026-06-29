"""Background reconciliation: re-push storage schedules to drifted firmware.

Every ``interval_s`` we iterate the scanner's online units, look each one up
in storage by ``hostname``, and compare the firmware-reported schedule fields
against the storage record. On drift (or when a field is missing from
telemetry, which usually means the firmware is older or pre-reset), we push
the storage payload again. Failures are warn-only — we will retry on the next
tick.

Uses a self-rearming ``threading.Timer`` rather than a dedicated thread so
``stop()`` is immediate and there's no sleep loop to interrupt.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from ethoscope_node.incubators.firmware_client import IncubatorHTTPError
from ethoscope_node.incubators.schedule import (
    build_firmware_payload,
    schedule_drifted,
)

if TYPE_CHECKING:
    from ethoscope_node.incubators.firmware_client import IncubatorFirmwareClient
    from ethoscope_node.incubators.scanner import IncubatorScanner
    from ethoscope_node.incubators.storage import IncubatorStorage

DEFAULT_INTERVAL_S = 60.0


class Reconciler:
    """Periodically reconciles firmware schedules with storage records.

    The constructor takes the three collaborators by reference; nothing here
    cares whether storage is the standalone SQLite backend or the node's
    ``ExperimentalDBIncubatorStorage`` adapter.
    """

    def __init__(
        self,
        storage: IncubatorStorage,
        scanner: IncubatorScanner,
        client: IncubatorFirmwareClient,
        interval_s: float = DEFAULT_INTERVAL_S,
    ):
        self._storage = storage
        self._scanner = scanner
        self._client = client
        self._interval_s = interval_s
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._stopped = True
        self._logger = logging.getLogger(self.__class__.__name__)

    def start(self) -> None:
        with self._lock:
            if not self._stopped:
                return
            self._stopped = False
            self._schedule_next_tick()
        self._logger.info("Reconciler started (interval=%.1fs)", self._interval_s)

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._logger.info("Reconciler stopped")

    def _schedule_next_tick(self) -> None:
        # Caller holds self._lock or we're starting.
        timer = threading.Timer(self._interval_s, self._tick)
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _tick(self) -> None:
        try:
            self.run_once()
        except Exception as e:
            self._logger.warning("Reconciler tick failed: %s", e)
        finally:
            with self._lock:
                if not self._stopped:
                    self._schedule_next_tick()

    def run_once(self) -> int:
        """Walk online devices, push to any whose schedule has drifted.

        Returns the number of pushes attempted (whether or not they succeeded).
        Public so tests can drive it deterministically and the standalone
        UI's "reconcile now" button can hit it on demand.
        """
        pushed = 0
        live = self._scanner.get_all_devices_info() or {}
        for device_id, telemetry in live.items():
            if telemetry.get("status") != "online":
                continue
            hostname = telemetry.get("hostname") or device_id
            if not hostname:
                continue
            record = self._find_record_by_hostname(hostname)
            if record is None:
                continue
            # Identity convergence: keep the unit's sensor name/location in sync
            # with the incubator name (handles a rename done while it was offline).
            self._reconcile_identity(record, telemetry, hostname)
            if not schedule_drifted(record, telemetry):
                continue
            payload = build_firmware_payload(record)
            try:
                ip = telemetry.get("ip")
                if not ip:
                    continue
                self._client.push_config(ip, payload)
                pushed += 1
                self._logger.info(
                    "Reconciler re-pushed schedule to %s (%s)", hostname, ip
                )
            except IncubatorHTTPError as e:
                self._logger.warning(
                    "Reconciler push to %s failed (will retry next tick): %s",
                    hostname,
                    e,
                )
        return pushed

    def _reconcile_identity(self, record: dict, telemetry: dict, hostname: str) -> None:
        """Re-push the incubator name to the unit's sensor name/location on drift.

        Only acts when the firmware reports its identity (newer firmware exposes
        ``name``/``location`` in ``/telemetry``) and it differs from the record
        name — so older firmware that omits these fields is left untouched and
        the immediate push on rename is relied upon instead.
        """
        desired = record.get("name")
        if not desired:
            return
        dev_name = telemetry.get("name")
        dev_location = telemetry.get("location")
        if dev_name is None and dev_location is None:
            return
        if dev_name == desired and dev_location == desired:
            return
        try:
            self._scanner.set_identity(hostname, name=desired, location=desired)
            self._logger.info(
                "Reconciler re-pushed identity '%s' to %s", desired, hostname
            )
        except Exception as e:
            self._logger.warning(
                "Reconciler identity push to %s failed (will retry): %s", hostname, e
            )

    def _find_record_by_hostname(self, hostname: str) -> dict | None:
        """Linear scan over storage; cheap given small N (single-digit incubators)."""
        for record in self._storage.list_all().values():
            if record.get("hostname") == hostname:
                return record
        return None
