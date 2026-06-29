"""Standalone server entry point — installed as ``ethoscope-incubator-server``.

Wires the SQLite storage, the Zeroconf scanner, the firmware client, the
reconciler, and the Bottle app into a single self-contained server. Run as::

    ethoscope-incubator-server --port 8090 --db-path /var/lib/incubators.db

No dependency on the rest of ``ethoscope_node`` — fresh venvs with only
``pip install bottle zeroconf requests`` (plus this package itself) can run it.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys

import bottle

from ethoscope_node.incubators.bottle_app import make_app
from ethoscope_node.incubators.firmware_client import IncubatorFirmwareClient
from ethoscope_node.incubators.reconciler import Reconciler
from ethoscope_node.incubators.routes import IncubatorRoutes
from ethoscope_node.incubators.scanner import IncubatorScanner
from ethoscope_node.incubators.storage import SQLiteIncubatorStorage

DEFAULT_PORT = 8090
DEFAULT_DB_PATH = os.path.expanduser("~/.ethoscope_incubators/incubators.db")
DEFAULT_HOST = "0.0.0.0"
DEFAULT_RECONCILE_INTERVAL_S = 60.0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone WiFi smart-incubator control server."
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST, help=f"Bind address (default: {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"HTTP port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"SQLite file path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--reconcile-interval",
        type=float,
        default=DEFAULT_RECONCILE_INTERVAL_S,
        help="Seconds between firmware drift checks (default: 60).",
    )
    parser.add_argument(
        "--no-reconcile",
        action="store_true",
        help="Disable the background reconciler (debug).",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Verbose logging + Bottle debug.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("ethoscope-incubator-server")

    os.makedirs(os.path.dirname(os.path.abspath(args.db_path)), exist_ok=True)

    storage = SQLiteIncubatorStorage(args.db_path)
    client = IncubatorFirmwareClient()
    scanner = IncubatorScanner()
    scanner.start()

    reconciler: Reconciler | None = None
    if not args.no_reconcile:
        reconciler = Reconciler(
            storage, scanner, client, interval_s=args.reconcile_interval
        )
        reconciler.start()

    routes = IncubatorRoutes(storage, scanner, client)
    app = make_app(routes)

    def _shutdown(signum, frame):  # noqa: ARG001
        logger.info("Received signal %s, shutting down", signum)
        try:
            if reconciler is not None:
                reconciler.stop()
        finally:
            scanner.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info(
        "Standalone incubator server: http://%s:%d (db=%s)",
        args.host,
        args.port,
        args.db_path,
    )
    try:
        bottle.run(
            app, host=args.host, port=args.port, debug=args.debug, quiet=not args.debug
        )
    finally:
        if reconciler is not None:
            reconciler.stop()
        scanner.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
