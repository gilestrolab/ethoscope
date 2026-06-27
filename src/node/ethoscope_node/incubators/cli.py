"""Command-line interface for the smart-incubator firmware.

Wraps :class:`IncubatorFirmwareClient` with subcommands for reading state,
pushing config, monitoring over time, and sending control commands::

    ethoscope-incubator status incubator-51
    ethoscope-incubator set incubator-51 set_temp=22 max_light=80
    ethoscope-incubator monitor incubator-51 --interval 60 --duration 30m
    ethoscope-incubator light incubator-51 50
    ethoscope-incubator i2c incubator-51
    ethoscope-incubator time sync incubator-51

Hostname shorthand: a bare name (``incubator-51``) gets ``.local`` appended;
anything containing ``.`` or ``:`` (FQDN, IPv4, IPv6) is passed through.

The module depends only on the firmware client (which depends only on
``requests``), so it runs on the same stripped-down venv as the standalone
incubator server.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import signal
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import IO, Any

from ethoscope_node.incubators.firmware_client import (
    IncubatorFirmwareClient,
    IncubatorHTTPError,
)

DEFAULT_TIMEOUT_S = 5.0
DEFAULT_INTERVAL_S = 60.0


# ---------- Argument coercion ----------

_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$", re.IGNORECASE)
_DURATION_UNIT_S = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str) -> float:
    """Parse ``30s`` / ``5m`` / ``2h`` / ``1d`` / bare-seconds → seconds (float)."""
    m = _DURATION_RE.match(text)
    if not m:
        raise argparse.ArgumentTypeError(f"invalid duration: {text!r}")
    return float(m.group(1)) * _DURATION_UNIT_S[m.group(2).lower()]


def resolve_host(host: str) -> str:
    """Append ``.local`` to bare hostnames; pass IPs / FQDNs through unchanged."""
    if "." in host or ":" in host:
        return host
    return f"{host}.local"


def coerce_value(text: str) -> Any:
    """Try ``true``/``false``/``null`` → bool/None, then int → float → str."""
    low = text.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low == "null":
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def parse_kv(arg: str) -> tuple[str, Any]:
    """Parse ``KEY=VALUE`` into a typed pair; raises ``ArgumentTypeError`` on bad form."""
    if "=" not in arg:
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, got {arg!r}")
    k, v = arg.split("=", 1)
    return k.strip(), coerce_value(v.strip())


# ---------- Output helpers ----------


def emit(obj: Any, *, as_json: bool, out: IO[str] | None = None) -> None:
    """Print ``obj`` as either pretty JSON or a ``key: value`` table.

    Resolves ``sys.stdout`` lazily so test harnesses (capsys, redirect_stdout)
    that swap stdout after import see the writes.
    """
    if out is None:
        out = sys.stdout
    if as_json:
        json.dump(obj, out, indent=2, default=str)
        out.write("\n")
        return
    if isinstance(obj, dict):
        keylen = max((len(k) for k in obj), default=0)
        for k, v in obj.items():
            out.write(f"{k:<{keylen}}  {v}\n")
        return
    out.write(str(obj) + "\n")


def _fmt(v: Any, spec: str, na: str = "N/A") -> str:
    if v is None:
        return na
    try:
        return format(v, spec)
    except (TypeError, ValueError):
        return str(v)


def fmt_status_human(t: dict[str, Any]) -> str:
    """Render /telemetry as a compact multi-line status block."""
    nid = t.get("node_id", "?")
    fw = t.get("fw", "?")
    build = t.get("build", "?")
    uptime = int(t.get("uptime_s", 0))
    lines = [
        f"incubator-{nid}  fw {fw} build {build}  up {uptime}s",
        f"  temp {_fmt(t.get('temperature'), '6.2f')} C   "
        f"hum {_fmt(t.get('humidity'), '5.1f')} %   "
        f"lux {_fmt(t.get('lux'), '6.1f')}",
        f"  setpoint {t.get('set_temp', '?')} C  "
        f"duty {_fmt(t.get('peltier_duty'), '+d')}  "
        f"dir {t.get('peltier_dir', '?')}  "
        f"fan {'on' if t.get('fan_on') else 'off'}",
        f"  light {t.get('light_level', 0)}%/{t.get('max_light', 0)}%  "
        f"schedule {t.get('lights_on', '?')}-{t.get('lights_off', '?')} min  "
        f"period {t.get('light_period_minutes', '?')}m  "
        f"anchor {t.get('light_cycle_anchor', 0)}",
        f"  rtc {'ok' if t.get('rtc') else 'MISSING'}  "
        f"time_valid {'yes' if t.get('time_valid') else 'no'}  "
        f"sensor_fault {'YES' if t.get('sensor_fault') else 'no'}",
    ]
    when = t.get("time")
    if when:
        lines.append(
            f"  clock {datetime.fromtimestamp(int(when)).isoformat(timespec='seconds')}  "
            f"rssi {t.get('rssi', '?')} dBm  "
            f"wifi {'up' if t.get('wifi') else 'down'}"
        )
    return "\n".join(lines)


# ---------- Subcommand handlers ----------


def _report_error(e: Exception) -> int:
    print(f"error: {e}", file=sys.stderr)
    return 2


def cmd_status(args, client: IncubatorFirmwareClient) -> int:
    host = resolve_host(args.host)
    interval = float(args.watch) if args.watch else None
    while True:
        try:
            data = client.get_telemetry(host)
        except IncubatorHTTPError as e:
            return _report_error(e)
        if args.json:
            emit(data, as_json=True)
        else:
            if interval is not None:
                sys.stdout.write("\x1b[2J\x1b[H")  # clear + home
            print(fmt_status_human(data))
        if interval is None:
            return 0
        time.sleep(max(0.5, interval))


def cmd_config(args, client: IncubatorFirmwareClient) -> int:
    try:
        data = client.get_config(resolve_host(args.host))
    except IncubatorHTTPError as e:
        return _report_error(e)
    emit(data, as_json=args.json)
    return 0


def cmd_set(args, client: IncubatorFirmwareClient) -> int:
    payload = dict(args.assignments)
    try:
        result = client.push_config(resolve_host(args.host), payload)
    except IncubatorHTTPError as e:
        return _report_error(e)
    emit(result, as_json=args.json)
    return 0


def cmd_monitor(args, client: IncubatorFirmwareClient) -> int:
    host = resolve_host(args.host)
    end_at = (time.monotonic() + args.duration) if args.duration else None
    sink: IO[str] | None = None
    csv_writer = None
    if args.output:
        sink = open(args.output, "w", newline="", encoding="utf-8")
        if args.csv:
            csv_writer = csv.writer(sink)
            csv_writer.writerow(
                ["timestamp", "t", "h", "lux", "duty", "dir", "fan", "light"]
            )

    if args.csv and sink is None:
        # CSV to stdout: write header.
        csv_writer = csv.writer(sys.stdout)
        csv_writer.writerow(
            ["timestamp", "t", "h", "lux", "duty", "dir", "fan", "light"]
        )
    elif not args.csv:
        dur = "unlimited" if args.duration is None else f"{args.duration:.0f}s"
        print(
            f"# monitor {host}  interval={args.interval}s  duration={dur}"
            "  (Ctrl-C to stop)"
        )
        print(
            f"{'time':19}  {'T':>6}  {'H':>5}  {'lux':>6}  {'duty':>5}  "
            f"{'dir':<4}  fan  light"
        )

    stop = False

    def _on_sigint(_sig, _frm):
        nonlocal stop
        stop = True

    prev = signal.signal(signal.SIGINT, _on_sigint)

    try:
        while not stop:
            ts = datetime.now().isoformat(timespec="seconds")
            try:
                d = client.get_telemetry(host)
            except IncubatorHTTPError as e:
                print(f"# {ts}  error: {e}", file=sys.stderr)
                d = None
            if d is not None:
                row = (
                    ts,
                    d.get("temperature"),
                    d.get("humidity"),
                    d.get("lux"),
                    d.get("peltier_duty"),
                    d.get("peltier_dir"),
                    bool(d.get("fan_on")),
                    d.get("light_level"),
                )
                if args.csv:
                    csv_writer.writerow(row)
                    (sink or sys.stdout).flush()
                else:
                    line = (
                        f"{ts}  {_fmt(row[1], '6.2f')}  {_fmt(row[2], '5.1f')}  "
                        f"{_fmt(row[3], '6.1f')}  {_fmt(row[4], '+5d')}  "
                        f"{str(row[5] or ''):<4}  "
                        f"{'on ' if row[6] else 'off'}  {row[7]}%"
                    )
                    print(line, flush=True)
                    if sink and not args.csv:
                        sink.write(line + "\n")
                        sink.flush()
            if end_at is not None and time.monotonic() >= end_at:
                break
            # Sleep in small slices so SIGINT remains responsive.
            slept = 0.0
            while slept < args.interval and not stop:
                step = min(0.5, args.interval - slept)
                time.sleep(step)
                slept += step
    finally:
        signal.signal(signal.SIGINT, prev)
        if sink:
            sink.close()
    return 0


def cmd_light(args, client: IncubatorFirmwareClient) -> int:
    pct = max(0, min(100, args.pct))
    try:
        result = client.set_light_override(resolve_host(args.host), pct)
    except IncubatorHTTPError as e:
        return _report_error(e)
    emit(result, as_json=args.json)
    return 0


def cmd_reboot(args, client: IncubatorFirmwareClient) -> int:
    try:
        result = client.reboot(resolve_host(args.host))
    except IncubatorHTTPError as e:
        return _report_error(e)
    emit(result, as_json=args.json)
    return 0


def cmd_time_sync(args, client: IncubatorFirmwareClient) -> int:
    try:
        result = client.sync_time(resolve_host(args.host))
    except IncubatorHTTPError as e:
        return _report_error(e)
    emit(result, as_json=args.json)
    return 0


def cmd_time_set(args, client: IncubatorFirmwareClient) -> int:
    epoch_arg = args.epoch
    epoch = int(time.time()) if epoch_arg.lower() == "now" else None
    if epoch is None:
        try:
            epoch = int(epoch_arg)
        except ValueError:
            print(
                f"error: epoch must be an integer or 'now', got {epoch_arg!r}",
                file=sys.stderr,
            )
            return 2
    try:
        result = client.set_time(resolve_host(args.host), epoch)
    except IncubatorHTTPError as e:
        return _report_error(e)
    emit(result, as_json=args.json)
    return 0


def cmd_i2c(args, client: IncubatorFirmwareClient) -> int:
    try:
        data = client.get_i2c_scan(resolve_host(args.host))
    except IncubatorHTTPError as e:
        return _report_error(e)
    if args.json:
        emit(data, as_json=True)
        return 0
    devs = data.get("devices", [])
    print(f"{data.get('count', len(devs))} device(s) on I2C:")
    for d in devs:
        print(f"  {d.get('addr', '??')}  {d.get('name', '(unknown)')}")
    return 0


def cmd_health(args, client: IncubatorFirmwareClient) -> int:
    try:
        data = client.get_health(resolve_host(args.host))
    except IncubatorHTTPError as e:
        return _report_error(e)
    emit(data, as_json=args.json)
    return 0


# ---------- argparse wiring ----------


def _add_host(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "host",
        help="Incubator hostname or IP (bare names get '.local' appended).",
    )


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of human text."
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser. Exposed for testing."""
    p = argparse.ArgumentParser(
        prog="ethoscope-incubator",
        description=(
            "Control and read remote smart-incubator devices over HTTP. "
            "Use subcommands for status, config, monitoring, and control."
        ),
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help=f"HTTP timeout seconds (default: {DEFAULT_TIMEOUT_S}).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("status", help="Show live telemetry.")
    _add_host(sp)
    _add_json(sp)
    sp.add_argument(
        "--watch",
        type=float,
        metavar="SECS",
        help="Refresh display every SECS seconds (Ctrl-C to stop).",
    )
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("config", help="Show persisted configuration.")
    _add_host(sp)
    _add_json(sp)
    sp.set_defaults(func=cmd_config)

    sp = sub.add_parser(
        "set", help="Push config changes (one or more KEY=VALUE pairs)."
    )
    _add_host(sp)
    sp.add_argument(
        "assignments",
        nargs="+",
        type=parse_kv,
        metavar="KEY=VALUE",
        help="e.g. set_temp=22 max_light=80 lights_on=540",
    )
    _add_json(sp)
    sp.set_defaults(func=cmd_set)

    sp = sub.add_parser("monitor", help="Log telemetry samples over time.")
    _add_host(sp)
    sp.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_S,
        metavar="SECS",
        help=f"Seconds between samples (default: {DEFAULT_INTERVAL_S:.0f}).",
    )
    sp.add_argument(
        "--duration",
        type=parse_duration,
        default=None,
        metavar="DUR",
        help="Stop after DUR (e.g. 30m, 2h, 90s). Default: run until Ctrl-C.",
    )
    sp.add_argument("--output", metavar="FILE", help="Also write each sample to FILE.")
    sp.add_argument(
        "--csv",
        action="store_true",
        help="Emit CSV (header + rows). Pairs with --output for file logging.",
    )
    sp.set_defaults(func=cmd_monitor)

    sp = sub.add_parser("light", help="Override LED brightness (transient).")
    _add_host(sp)
    sp.add_argument("pct", type=int, help="Brightness percent 0..100.")
    _add_json(sp)
    sp.set_defaults(func=cmd_light)

    sp = sub.add_parser("reboot", help="Reboot the device.")
    _add_host(sp)
    _add_json(sp)
    sp.set_defaults(func=cmd_reboot)

    sp = sub.add_parser("time", help="Time-related commands.")
    sub_time = sp.add_subparsers(dest="time_cmd", required=True)
    spa = sub_time.add_parser("sync", help="Force NTP→RTC sync.")
    _add_host(spa)
    _add_json(spa)
    spa.set_defaults(func=cmd_time_sync)
    spa = sub_time.add_parser(
        "set", help="Manually set clock (epoch seconds or 'now')."
    )
    _add_host(spa)
    spa.add_argument("epoch", help="Epoch seconds or the literal 'now'.")
    _add_json(spa)
    spa.set_defaults(func=cmd_time_set)

    sp = sub.add_parser("i2c", help="Scan the I2C bus and list responders.")
    _add_host(sp)
    _add_json(sp)
    sp.set_defaults(func=cmd_i2c)

    sp = sub.add_parser("health", help="Quick health snapshot.")
    _add_host(sp)
    _add_json(sp)
    sp.set_defaults(func=cmd_health)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = IncubatorFirmwareClient(timeout=args.timeout)
    handler: Callable[[argparse.Namespace, IncubatorFirmwareClient], int] = args.func
    return handler(args, client)


if __name__ == "__main__":
    sys.exit(main())
