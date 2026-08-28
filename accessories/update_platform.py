#!/usr/bin/env python3
"""
Update the whole ethoscope platform from the command line.

This is the command line equivalent of the web updater served by
``src/updater/update_server.py``: it drives the very same HTTP API, so the two
cannot drift apart, and every safety check the web page makes is made here too.

In order, it:

  1. refreshes the node's bare repository from its remote (``GET /bare/update``);
  2. surveys every ethoscope the node knows about, plus the node itself;
  3. updates and restarts every ethoscope that is out of date *and* idle --
     devices that are tracking, recording or streaming are never touched;
  4. re-surveys the fleet and confirms what actually landed;
  5. updates and restarts the node last, then waits for it to come back;
  6. prints a summary, and exits non-zero if anything failed.

The node is deliberately updated *after* the devices. Restarting the node also
restarts the update server this script is talking to, so doing it first would cut
the connection while the devices were still being worked on.

Examples:
    ./update_platform.py                                # run on the node itself
    ./update_platform.py --host node --dry-run          # see the plan and stop
    ./update_platform.py --host node --only 'ETHOSCOPE_35*' --yes
    ./update_platform.py --host node --devices-only --json
"""

import argparse
import json
import sys
import time
from datetime import datetime

from update_platform_api import (
    BARE_TIMEOUT,
    GROUP_TIMEOUT,
    STATE_LABELS,
    UpdaterError,
    UpdateServer,
    device_state,
    eligibility,
    matches,
    short,
)

# --------------------------------------------------------------------------- printing


class Console:
    """Plain, optionally coloured, output. Silenced entirely in --json mode."""

    COLORS = {
        "current": "\033[32m",
        "outdated": "\033[31m",
        "stale": "\033[33m",
        "unknown": "\033[90m",
        "bold": "\033[1m",
        "red": "\033[31m",
        "green": "\033[32m",
        "yellow": "\033[33m",
    }

    def __init__(self, quiet=False, color=None):
        self.quiet = quiet
        self.color = sys.stdout.isatty() if color is None else color

    def paint(self, text, style):
        """Wrap text in an ANSI colour, or return it untouched on a dumb terminal."""
        if not self.color or style not in self.COLORS:
            return text
        return f"{self.COLORS[style]}{text}\033[0m"

    def say(self, text=""):
        """Print a line unless output has been silenced."""
        if not self.quiet:
            print(text, flush=True)

    def step(self, text):
        """Print a phase heading."""
        self.say()
        self.say(self.paint(f"==> {text}", "bold"))


def device_row(device, extra=""):
    """Format one device as a fixed width table row."""
    return "  {:<18} {:<15} {:<8} {:>8} -> {:<8} {}".format(
        str(device.get("name") or device.get("id", "?"))[:18],
        str(device.get("status"))[:15],
        str(device.get("active_branch") or "-")[:8],
        short(device.get("local_commit")),
        short(device.get("origin_commit")),
        extra,
    )


def label(device):
    """The short human name of a device, falling back to its id."""
    return str(device.get("name") or device.get("id"))


# ----------------------------------------------------------------------------- phases


def survey(server, console, include_devices=True):
    """
    Ask the node for the state of every device and of itself (step 2).

    Args:
        server (UpdateServer): the client.
        console (Console): where to report progress.
        include_devices (bool): scan the fleet. Skipped for --node-only, where the
            scan costs minutes of git fetches whose answers are then thrown away.

    Returns:
        tuple: (devices, node) -- both in device-entry shape.
    """
    devices = []
    if include_devices:
        console.step("Surveying the fleet (this runs a git fetch on every device)")
        devices = server.scan_devices()
        console.say(f"  {len(devices)} device(s) known to the node")

    console.step("Checking the node")
    node = server.node_state()
    console.say(
        f"  node is on {node.get('active_branch', '?')} at "
        f"{short(node.get('local_commit'))}"
    )
    return devices, node


def build_plan(devices, node, args):
    """
    Split the fleet into what will be updated and what will be left alone.

    Args:
        devices (list): device entries from the node.
        node (dict): the node's own entry.
        args: parsed command line.

    Returns:
        tuple: (targets, skipped, node_target). ``targets`` and ``skipped`` are
        lists of (device, reason) pairs; ``node_target`` is such a pair or None.
    """
    targets, skipped = [], []

    for device in devices:
        if args.only and not matches(device, args.only):
            continue
        if args.skip and matches(device, args.skip):
            skipped.append((device, "excluded by --skip"))
            continue

        ok, reason = eligibility(device, args.force)
        (targets if ok else skipped).append((device, reason))

    node_target = None
    if not args.devices_only:
        state = device_state(node)
        if state != "current" or args.force or args.restart_node:
            node_target = (node, state)
        else:
            skipped.append((node, "already up to date"))

    return targets, skipped, node_target


def show_plan(console, targets, skipped, node_target):
    """Print the table of what is about to happen (step 2b)."""
    console.step("Plan")

    if targets or node_target:
        console.say("  To be updated and restarted:")
        for device, state in targets:
            console.say(device_row(device, console.paint(STATE_LABELS[state], state)))
        if node_target:
            node, state = node_target
            console.say(
                device_row(node, console.paint(STATE_LABELS[state] + " (node)", state))
            )
    else:
        console.say("  Nothing to update.")

    if skipped:
        console.say()
        console.say("  Left alone:")
        for device, reason in skipped:
            style = "yellow" if reason.startswith("busy") else "unknown"
            console.say(device_row(device, console.paint(reason, style)))


def confirm(console, count, assume_yes):
    """Ask for confirmation unless --yes was given. Returns True to proceed."""
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        console.say(
            console.paint(
                "\nRefusing to update non-interactively without --yes.", "red"
            )
        )
        return False
    return input(f"\nUpdate {count} machine(s)? [y/N] ").strip().lower() in ("y", "yes")


def update_devices(server, console, targets, args):
    """
    Update every eligible ethoscope, in batches if asked (step 3).

    Returns:
        list: (device_id, message) pairs for everything the node reported failed.
    """
    console.step(f"Updating {len(targets)} ethoscope(s)")
    devices = [d for d, _ in targets]
    size = args.batch_size or len(devices)
    failures = []

    for start in range(0, len(devices), size):
        batch = devices[start : start + size]
        console.say(f"  Sending update for: {', '.join(label(d) for d in batch)}")
        try:
            _, batch_failures = server.group_update(batch, timeout=args.timeout)
        except UpdaterError as e:
            console.say(console.paint(f"  Batch failed: {e}", "red"))
            failures.extend((d["id"], str(e)) for d in batch)
            continue
        failures.extend(batch_failures)

    # Reason: the node reports one entry per sub-step, so a device that failed its
    # pull yields the identical error twice. Printing it twice just reads as noise.
    failures = list(dict.fromkeys(failures))
    names = {d["id"]: label(d) for d in devices}
    for device_id, message in failures:
        console.say(
            console.paint(f"  ! {names.get(device_id, device_id)}: {message}", "red")
        )
    return failures


def verify_devices(server, console, targets, args):
    """
    Re-survey the fleet until the updated devices report themselves current (step 4).

    Returns:
        dict: device id -> (state, latest device entry).
    """
    console.step("Confirming the devices came back")
    wanted = {d["id"] for d, _ in targets}
    observed = {}

    for attempt in range(args.verify_retries + 1):
        console.say(f"  Waiting {args.settle}s for services to restart...")
        time.sleep(args.settle)

        try:
            console.step("Re-surveying the fleet")
            devices = server.scan_devices()
        except UpdaterError as e:
            console.say(console.paint(f"  Survey failed: {e}", "red"))
            continue

        for device in devices:
            if device["id"] in wanted:
                observed[device["id"]] = (device_state(device), device)

        pending = [i for i in wanted if observed.get(i, ("unknown",))[0] != "current"]
        if not pending:
            break
        if attempt < args.verify_retries:
            console.say(f"  {len(pending)} device(s) not settled yet; re-checking.")

    return observed


def update_node(server, console, node_target, args):
    """
    Update the node and wait for its update server to come back (step 5).

    Returns:
        tuple: (failures, node entry after the restart or None).
    """
    node, _ = node_target
    console.step("Updating the node (this restarts the node and update services)")

    try:
        responses, failures = server.group_update([node], timeout=args.timeout)
    except UpdaterError as e:
        console.say(console.paint(f"  Node update failed: {e}", "red"))
        return [("node", str(e))], None

    for item in responses:
        if isinstance(item, dict) and "new_commit" in item:
            console.say(
                f"  node {short(item.get('old_commit'))} -> "
                f"{short(item.get('new_commit'))}"
            )
    for device_id, message in failures:
        console.say(console.paint(f"  ! {device_id}: {message}", "red"))
    if failures:
        return failures, None

    # Reason: the node schedules its restart a few seconds out so it can answer us
    # first, so it is still reachable for a moment after this reply -- polling
    # immediately would see the old server and declare victory too early.
    console.say("  Waiting for the update server to restart...")
    time.sleep(10)
    deadline = time.time() + args.node_restart_timeout
    while time.time() < deadline:
        if server.alive():
            break
        time.sleep(5)
    else:
        return [("node", "update server did not come back")], None

    try:
        return [], server.node_state(timeout=BARE_TIMEOUT)
    except UpdaterError as e:
        return [("node", f"came back but could not be queried: {e}")], None


# ---------------------------------------------------------------------------- summary


def summarise(console, targets, skipped, observed, node_after, failures, args):
    """
    Print the closing report and work out the exit status (step 6).

    Returns:
        tuple: (exit_code, machine readable summary dict).
    """
    console.step("Summary")

    confirmed, unconfirmed = [], []
    for device, _ in targets:
        state, latest = observed.get(device["id"], (None, device))
        if state == "current":
            confirmed.append((device, latest))
        else:
            why = "not re-checked" if state is None else STATE_LABELS[state]
            unconfirmed.append((device, latest, why))

    if confirmed:
        console.say(console.paint(f"  Updated ({len(confirmed)}):", "green"))
        for before, after in confirmed:
            console.say(
                f"    {label(before):<18} {short(before.get('local_commit'))}"
                f" -> {short(after.get('local_commit'))}"
            )

    if unconfirmed:
        console.say(console.paint(f"  Not confirmed ({len(unconfirmed)}):", "red"))
        for before, after, why in unconfirmed:
            console.say(
                f"    {label(before):<18} {why} "
                f"(on disk {short(after.get('local_commit'))})"
            )

    if node_after is not None:
        state = device_state(node_after)
        console.say(
            f"  Node: {console.paint(STATE_LABELS[state], state)} "
            f"at {short(node_after.get('local_commit'))}"
        )

    busy = [d for d, r in skipped if r.startswith("busy")]
    if busy:
        console.say(
            console.paint(
                f"  Untouched because they are working ({len(busy)}): "
                + ", ".join(label(d) for d in busy),
                "yellow",
            )
        )

    others = [(d, r) for d, r in skipped if not r.startswith("busy")]
    if others:
        console.say(f"  Skipped for other reasons: {len(others)}")

    names = {d["id"]: label(d) for d, _ in targets}
    if failures:
        console.say(console.paint(f"  Errors reported ({len(failures)}):", "red"))
        for device_id, message in failures:
            console.say(f"    {names.get(device_id, device_id)}: {message}")

    exit_code = 1 if (failures or unconfirmed) else 0
    if exit_code == 0:
        console.say(console.paint("  All good.", "green"))

    summary = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "host": args.host,
        "updated": [
            {
                "id": b["id"],
                "name": b.get("name"),
                "from": short(b.get("local_commit")),
                "to": short(a.get("local_commit")),
            }
            for b, a in confirmed
        ],
        "not_confirmed": [
            {"id": b["id"], "name": b.get("name"), "state": w}
            for b, _, w in unconfirmed
        ],
        "busy": [{"id": d["id"], "name": d.get("name")} for d in busy],
        "skipped": [
            {"id": d["id"], "name": d.get("name"), "reason": r} for d, r in others
        ],
        "errors": [
            {"device_id": i, "name": names.get(i), "error": m} for i, m in failures
        ],
        "node": (
            {
                "state": device_state(node_after),
                "commit": short(node_after.get("local_commit")),
            }
            if node_after is not None
            else None
        ),
        "exit_code": exit_code,
    }
    return exit_code, summary


# ------------------------------------------------------------------------------- main


def parse_args(argv=None):
    """Build and parse the command line."""
    p = argparse.ArgumentParser(
        description="Update the ethoscope platform (node + devices) from the CLI.",
        epilog="Devices that are running, recording or streaming are never updated.",
    )
    p.add_argument("--host", default="localhost", help="host running the node updater")
    p.add_argument("--port", type=int, default=8888, help="update server port")
    p.add_argument(
        "-n", "--dry-run", action="store_true", help="show the plan and stop"
    )
    p.add_argument("-y", "--yes", action="store_true", help="do not ask to confirm")
    p.add_argument("--only", action="append", metavar="GLOB", help="only these devices")
    p.add_argument(
        "--skip", action="append", metavar="GLOB", help="never these devices"
    )
    p.add_argument("--devices-only", action="store_true", help="do not update the node")
    p.add_argument("--node-only", action="store_true", help="update only the node")
    p.add_argument(
        "--restart-node",
        action="store_true",
        help="update and restart the node even if it already looks up to date",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="also update machines that look up to date (never the busy ones)",
    )
    p.add_argument(
        "--no-verify", action="store_true", help="skip the confirmation re-survey"
    )
    p.add_argument(
        "--batch-size", type=int, default=0, help="devices per batch (0 = all at once)"
    )
    p.add_argument(
        "--settle", type=int, default=20, help="seconds to wait before re-checking"
    )
    p.add_argument(
        "--verify-retries", type=int, default=2, help="extra re-surveys if not settled"
    )
    p.add_argument(
        "--timeout", type=int, default=GROUP_TIMEOUT, help="group update timeout (s)"
    )
    p.add_argument(
        "--node-restart-timeout",
        type=int,
        default=300,
        help="seconds to wait for the node to come back",
    )
    p.add_argument("--json", action="store_true", help="print only a JSON summary")

    args = p.parse_args(argv)
    if args.devices_only and args.node_only:
        p.error("--devices-only and --node-only are mutually exclusive")
    return args


def main(argv=None):
    """Run the whole update and return a shell exit code."""
    args = parse_args(argv)
    console = Console(quiet=args.json)
    server = UpdateServer(args.host, args.port)

    try:
        if not server.alive(timeout=10):
            raise UpdaterError(
                f"no update server answering on {server.base} "
                "(is ethoscope_update_node running?)"
            )
        console.step("Refreshing the bare repository on the node")
        branches = server.refresh_bare_repo()
        console.say(f"  {len(branches)} branch(es) refreshed: {', '.join(branches)}")

        devices, node = survey(server, console, include_devices=not args.node_only)
    except UpdaterError as e:
        console.say(console.paint(f"Fatal: {e}", "red"))
        if args.json:
            print(json.dumps({"error": str(e), "exit_code": 2}, indent=2))
        return 2

    targets, skipped, node_target = build_plan(devices, node, args)
    show_plan(console, targets, skipped, node_target)

    total = len(targets) + (1 if node_target else 0)
    if args.dry_run or not total:
        if args.json:
            would = [d["id"] for d, _ in targets] + (["node"] if node_target else [])
            print(json.dumps({"dry_run": True, "would_update": would}, indent=2))
        return 0

    if not confirm(console, total, args.yes):
        console.say("Aborted.")
        return 0

    failures, observed = [], {}
    if targets:
        failures += update_devices(server, console, targets, args)
        if not args.no_verify:
            observed = verify_devices(server, console, targets, args)

    node_after = None
    if node_target:
        node_failures, node_after = update_node(server, console, node_target, args)
        failures += node_failures

    exit_code, summary = summarise(
        console, targets, skipped, observed, node_after, failures, args
    )
    if args.json:
        print(json.dumps(summary, indent=2))
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Devices already sent an update will finish on their own.")
        sys.exit(130)
