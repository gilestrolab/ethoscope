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
    ethoscope-light fade 100            # ease up to full over 3 s, hold
    ethoscope-light fade 0 -t 5         # ease down to off over 5 s, hold
    ethoscope-light test                # fade in/out a few times, then release
    ethoscope-light test -n 5 -t 1.5    # 5 cycles, 1.5 s each ramp
"""

import argparse
import json
import sys
import time

from ethoscope.hardware.interfaces.light_daemon import (
    DEFAULT_SOCKET_PATH,
    LightDaemonClient,
    LightDaemonUnavailable,
    smoothstep,
)

# Client-side ramps are drawn with a bounded number of steps: enough for a
# visually smooth fade, few enough to keep the per-step socket round-trips
# cheap. A ramp never uses more steps than it has percent points to cross.
_CLI_FADE_STEPS = 60
_CLI_STEP_FLOOR_S = 0.01


def _clamp_pct(value: int) -> int:
    return max(0, min(100, int(value)))


def _ramp_via_force(client, start, target, seconds):
    """Ease the forced LED level from ``start`` to ``target`` over ``seconds``.

    Steps ``FORCE PCT`` along the daemon's own smoothstep curve. Each step sets
    a force, so the daemon's schedule loop sees ``current == force`` and leaves
    the transition alone. The force is left held at ``target`` on return.
    """
    start = _clamp_pct(start)
    target = _clamp_pct(target)
    if start == target or seconds <= 0:
        client.force_pct(target)
        return

    span = abs(target - start)
    steps = min(_CLI_FADE_STEPS, span)
    step_delay = max(_CLI_STEP_FLOOR_S, seconds / steps)
    for i in range(1, steps + 1):
        t = i / steps
        pct = round(start + (target - start) * smoothstep(t))
        # Rounding can nudge a step just past the target; keep it in-envelope.
        pct = min(pct, target) if target > start else max(pct, target)
        client.force_pct(pct)
        if i < steps:
            time.sleep(step_delay)
    client.force_pct(target)  # land exactly on target


def _cmd_on(client, _args):
    client.force_on()
    print("LED forced ON")


def _cmd_off(client, _args):
    client.force_off()
    print("LED forced OFF")


def _cmd_release(client, _args):
    client.release()
    print("Force released; following schedule")


def _cmd_status(client, _args):
    # status() raises if the daemon isn't reachable; caught in main()
    print(json.dumps(client.status(), indent=2))


def _cmd_fade(client, args):
    target = _clamp_pct(args.percent)
    start = _clamp_pct(client.status().get("led", 0))
    _ramp_via_force(client, start, target, args.seconds)
    print(
        f"Faded {start}% -> {target}% over {args.seconds:g}s (force held; 'release' to resume schedule)"
    )


def _cmd_test(client, args):
    """Visible wiring/PWM check: fade fully in and out a few times, then release."""
    print(
        f"LED test on the light daemon — {args.cycles} cycle(s), {args.seconds:g}s per ramp. Watch the ethoscope."
    )
    client.force_off()  # start from a known dark state
    for c in range(1, args.cycles + 1):
        print(
            f"  cycle {c}/{args.cycles}: fade in 0->100%, fade out 100->0%",
            flush=True,
        )
        _ramp_via_force(client, 0, 100, args.seconds)
        _ramp_via_force(client, 100, 0, args.seconds)
    client.release()
    print("Test complete; force released, schedule resumed")


_HANDLERS = {
    "on": _cmd_on,
    "off": _cmd_off,
    "release": _cmd_release,
    "status": _cmd_status,
    "fade": _cmd_fade,
    "test": _cmd_test,
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

    p_fade = sub.add_parser(
        "fade", help="Ease the LED to a brightness over a few seconds, then hold it"
    )
    p_fade.add_argument("percent", type=int, help="Target brightness, 0-100")
    p_fade.add_argument(
        "-t",
        "--seconds",
        type=float,
        default=3.0,
        help="Ramp duration in seconds (default: 3)",
    )

    p_test = sub.add_parser(
        "test",
        help="Fade the LED in and out a few times to check wiring/PWM, then release",
    )
    p_test.add_argument(
        "-n",
        "--cycles",
        type=int,
        default=3,
        help="Number of fade in/out cycles (default: 3)",
    )
    p_test.add_argument(
        "-t",
        "--seconds",
        type=float,
        default=2.5,
        help="Seconds per fade ramp (default: 2.5)",
    )
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
