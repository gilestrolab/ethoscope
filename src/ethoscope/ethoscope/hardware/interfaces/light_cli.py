#!/usr/bin/env python3
"""
Command-line client for the Ethoscope light daemon.

Talks to ``ethoscope_light.service`` over its Unix control socket.
Useful for diagnostics, manual override during maintenance, and scripts.

Examples:
    ethoscope-light on
    ethoscope-light off
    ethoscope-light release
    ethoscope-light status
"""
import argparse
import json
import sys

from ethoscope.hardware.interfaces.light_daemon import (
    DEFAULT_SOCKET_PATH,
    LightDaemonClient,
    LightDaemonUnavailable,
)


def _cmd_on(client, _args):
    client.force_on()
    print("LED forced ON")


def _cmd_off(client, _args):
    client.force_off()
    print("LED forced OFF")


def _cmd_release(client, _args):
    client.release()
    print("Force released; following schedule")


def _cmd_status(_client, _args):
    # status() raises if the daemon isn't reachable; caught in main()
    print(json.dumps(_client.status(), indent=2))


_HANDLERS = {
    "on": _cmd_on,
    "off": _cmd_off,
    "release": _cmd_release,
    "status": _cmd_status,
}


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="ethoscope-light",
        description="Control the Ethoscope light daemon.",
    )
    parser.add_argument(
        "-s",
        "--socket",
        default=DEFAULT_SOCKET_PATH,
        help=f"Path to the light daemon's control socket (default: {DEFAULT_SOCKET_PATH})",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("on", help="Force the LED on")
    sub.add_parser("off", help="Force the LED off")
    sub.add_parser("release", help="Release any force; resume the schedule")
    sub.add_parser("status", help="Print daemon status as JSON")
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    client = LightDaemonClient(socket_path=args.socket)
    try:
        _HANDLERS[args.cmd](client, args)
    except LightDaemonUnavailable as e:
        print(
            f"ethoscope-light: light daemon not reachable ({e}). "
            "Is ethoscope_light.service running?",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
