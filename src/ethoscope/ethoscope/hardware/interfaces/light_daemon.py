#!/usr/bin/env python3
"""
Ethoscope LED Daylight Controller Daemon.

Standalone service that controls a white LED via GPIO to simulate daylight
conditions during experiments. Reads a schedule config file written by the
device tracking server and toggles the LED accordingly.

Hardware: GPIO -> BS170 MOSFET -> LED -> 100ohm -> 5Vdc.
GPIO HIGH = MOSFET on = LED on, GPIO LOW = LED off.

Backends
--------
The daemon supports three GPIO backends with the same external behaviour:

* ``PigpioBackend`` — DMA-software-PWM via ``pigpio`` on any GPIO, or *true*
  hardware PWM on GPIO12/13/18/19. Provides smooth ``fade_in_seconds`` /
  ``fade_out_seconds`` ramps to ``max_light`` percent. Requires ``pigpiod``
  to be running (``systemctl enable --now pigpiod``). Only available on
  Bookworm and earlier.
* ``LgpioBackend`` — PWM via ``gpiozero`` over ``lgpio``, same fade support,
  **hardware-PWM pins only** (GPIO12/13/18/19). ``pigpio`` ships no package
  from Debian Trixie onwards and never supported the Pi 5, so this is the only
  PWM route on modern images. It is restricted to hardware-PWM pins because
  lgpio times software PWM on the CPU rather than off the DMA engine, and a
  tracking ethoscope keeps its Pi saturated: on GPIO17 that flickers visibly,
  which is worse for the animals than not dimming at all.
* ``PinctrlBackend`` — legacy binary on/off via the ``pinctrl`` CLI. Fade
  requests collapse to instant transitions at the 50 % threshold. Last-resort
  fallback, so older deployments keep working unchanged.

Backend selection happens at init, in that order, each falling through to the
next on any error (import failure, daemon not running, connection refused).
The choice is logged at startup so it's self-evident in the journal which
backend is in use.
"""

import datetime
import json
import logging
import os
import signal
import socket
import subprocess
import threading
import time
from optparse import OptionParser

DEFAULT_CONFIG_FILE = "/run/ethoscope/light_schedule.json"
DEFAULT_SOCKET_PATH = "/run/ethoscope/light_daemon.sock"
DEFAULT_POLL_INTERVAL = 30
DEFAULT_GPIO_PIN = 17
DEFAULT_MAX_LIGHT = 100
DEFAULT_FADE_IN_SECONDS = 1
DEFAULT_FADE_OUT_SECONDS = 1
DEFAULT_PWM_FREQUENCY_HZ = 5000

# Where to reach pigpiod. Deliberately NOT pigpio's default port 8888: on an
# ethoscope that belongs to ethoscope_update.service, so pigpiod cannot bind it
# and - worse - a client using the default connects to the update server, is
# told the connection succeeded, and then sends GPIO commands to an HTTP server.
# pigpiod must therefore be started with a matching `-p` (see the systemd unit).
PIGPIO_HOST = os.environ.get("ETHOSCOPE_PIGPIO_HOST", "localhost")
PIGPIO_PORT = int(os.environ.get("ETHOSCOPE_PIGPIO_PORT", "8889"))

# Gamma correction for the LED PWM duty cycle. Human brightness perception is
# roughly logarithmic, so a linear duty looks crammed at the bottom and plateaus
# at the top. ~2.2 matches the sRGB convention and gives a visually even ramp.
# Endpoints (0 and 100) are preserved exactly. Applied only by the PigpioBackend
# (PWM); the PinctrlBackend is binary and is unaffected.
LIGHT_GAMMA = 2.2

# Pi hardware-PWM-capable GPIOs (BCM): PWM0 ∈ {12, 18}, PWM1 ∈ {13, 19}.
_HW_PWM_GPIOS = frozenset({12, 13, 18, 19})

# How often the fade walker steps while transitioning (ms). 100 steps over
# fade_in_ms/fade_out_ms gives a perceptually smooth ramp without overloading
# the pigpiod request rate.
_FADE_STEPS = 100
_FADE_STEP_FLOOR_MS = 1

_CLIENT_TIMEOUT = 1.0
_LISTENER_ACCEPT_TIMEOUT = 0.5
_MAX_CMD_BYTES = 128


def smoothstep(t: float) -> float:
    """Perlin smoothstep ``S(t) = 3t² − 2t³`` on ``t`` in ``[0, 1]``.

    Zero derivative at both endpoints, so a brightness ramp mapped through it
    eases gently in and out (dawn-/dusk-like) and moves fastest in the middle.
    Shared by the daemon's ``ramp_to`` and the CLI's client-side fade so both
    draw the identical curve.
    """
    return (3 * t * t) - (2 * t * t * t)


class LightDaemonUnavailable(RuntimeError):
    """Raised by LightDaemonClient when the daemon socket cannot be reached."""


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class _LedBackend:
    """Interface every LED backend must satisfy.

    The daemon talks to one of these via ``set_pct(0..100)`` and ``close()``.
    Backends that can't actually dim (PinctrlBackend) are expected to threshold.
    """

    supports_fade: bool = False
    name: str = "base"

    def set_pct(self, pct: int) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class PinctrlBackend(_LedBackend):
    """Legacy ``pinctrl set N op dh/dl`` backend. Binary on/off, no fade.

    Kept as the universal fallback so an ethoscope without ``pigpiod`` still
    drives its LED — just without smooth ramps. Threshold at 50 % matches a
    safe interpretation of a partial brightness request.
    """

    supports_fade = False
    name = "pinctrl"

    def __init__(self, gpio_pin: int):
        self._gpio_pin = str(gpio_pin)
        self._current_on: bool | None = None

    def set_pct(self, pct: int) -> None:
        target_on = pct >= 50
        if target_on == self._current_on:
            return
        drive = "dh" if target_on else "dl"
        try:
            subprocess.run(
                ["pinctrl", "set", self._gpio_pin, "op", drive],
                check=True,
                capture_output=True,
                timeout=5,
            )
            self._current_on = target_on
            logging.info(
                "LED %s via pinctrl (GPIO%s %s)",
                "ON" if target_on else "OFF",
                self._gpio_pin,
                drive,
            )
        except FileNotFoundError:
            logging.error("pinctrl command not found. Is this a Raspberry Pi?")
            raise
        except subprocess.CalledProcessError as e:
            logging.error("pinctrl failed: %s", e.stderr.decode().strip())
        except subprocess.TimeoutExpired:
            logging.error("pinctrl command timed out")

    def close(self) -> None:
        # Best-effort: drive low on shutdown so the LED doesn't latch on.
        try:
            self.set_pct(0)
        except Exception:
            pass


class PigpioBackend(_LedBackend):
    """pigpio-driven PWM backend with automatic hardware/software pick.

    For pins on PWM0/PWM1 (GPIO 12/13/18/19) uses ``hardware_PWM`` for
    jitter-free DMA-clocked PWM. For any other pin (notably GPIO17 on the
    legacy boards) uses ``set_PWM_dutycycle`` — still DMA-based via pigpio's
    waveform engine, smooth enough that flies cannot perceive flicker
    (Drosophila CFF ≈ 150–200 Hz; we run at 5 kHz).
    """

    supports_fade = True
    name = "pigpio"

    def __init__(
        self,
        gpio_pin: int,
        frequency_hz: int = DEFAULT_PWM_FREQUENCY_HZ,
        host: str = PIGPIO_HOST,
        port: int = PIGPIO_PORT,
    ):
        # Late import so importing this module on a dev box without pigpio
        # succeeds; falls back to PinctrlBackend at the call site.
        import pigpio  # noqa: F401 (validated by the caller)

        self._pigpio = pigpio
        self._pi = pigpio.pi(host, port)
        if not self._pi.connected:
            raise RuntimeError(f"pigpiod is not running on {host}:{port}")

        # A bare TCP connect proves nothing: pigpio's own default port (8888)
        # is the ethoscope update server's, and connecting to *that* reports
        # success, after which every GPIO call would be sent to an HTTP server
        # and silently do nothing. Ask for a version to confirm the peer really
        # is pigpiod before this backend is accepted.
        try:
            version = self._pi.get_pigpio_version()
        except Exception as e:
            self._pi.stop()
            raise RuntimeError(f"{host}:{port} did not answer as pigpiod: {e}") from e

        if not isinstance(version, int) or version <= 0:
            self._pi.stop()
            raise RuntimeError(
                f"{host}:{port} is not pigpiod (bad version response: {version!r})"
            )
        self._gpio_pin = int(gpio_pin)
        self._frequency_hz = int(frequency_hz)
        self._hardware = self._gpio_pin in _HW_PWM_GPIOS
        self._current_pct = -1  # force first write

        # Configure
        self._pi.set_mode(self._gpio_pin, pigpio.OUTPUT)
        if not self._hardware:
            self._pi.set_PWM_frequency(self._gpio_pin, self._frequency_hz)
            self._pi.set_PWM_range(self._gpio_pin, 1000)  # 0..1000 = 0..100.0%
        self.set_pct(0)

        logging.info(
            "LED backend = pigpio (GPIO%d, %s PWM @ %d Hz)",
            self._gpio_pin,
            "hardware" if self._hardware else "DMA-software",
            self._frequency_hz,
        )

    def set_pct(self, pct: int) -> None:
        pct = max(0, min(100, int(pct)))
        if pct == self._current_pct:
            return
        # Gamma-correct the linear 0..100 percent to a perceptually even duty.
        # pow(0, g) == 0 and pow(1, g) == 1, so the endpoints stay exact.
        norm = pct / 100.0
        corrected = norm**LIGHT_GAMMA
        if self._hardware:
            # hardware_PWM duty cycle is 0..1_000_000 (1 = 0.0001%)
            duty = int(round(corrected * 1_000_000))
            self._pi.hardware_PWM(self._gpio_pin, self._frequency_hz, duty)
        else:
            # set_PWM_dutycycle uses the configured range (1000 → 0..100.0%)
            duty = int(round(corrected * 1000))
            self._pi.set_PWM_dutycycle(self._gpio_pin, duty)
        self._current_pct = pct

    def close(self) -> None:
        try:
            self.set_pct(0)
        except Exception:
            pass
        try:
            self._pi.stop()
        except Exception:
            pass


class LgpioBackend(_LedBackend):
    """PWM via ``gpiozero`` over the ``lgpio`` pin factory.

    The successor to pigpio on modern Raspberry Pi OS: ``pigpio`` ships no
    package from Debian Trixie onwards, and does not support the Pi 5 at all,
    so without this backend every recent image silently degraded to binary
    on/off. Software PWM here runs inside this process, which is fine because
    the daemon is long-lived, but means the LED reverts when it exits.
    """

    supports_fade = True
    name = "lgpio"

    def __init__(self, gpio_pin: int, frequency_hz: int = DEFAULT_PWM_FREQUENCY_HZ):
        from gpiozero import PWMLED

        self._gpio_pin = int(gpio_pin)
        self._frequency_hz = int(frequency_hz)
        self._led = PWMLED(self._gpio_pin, frequency=self._frequency_hz)
        self._current_pct = None

        logging.info(
            "LED backend: lgpio PWM on GPIO%s at %s Hz",
            self._gpio_pin,
            self._frequency_hz,
        )

    def set_pct(self, pct: int) -> None:
        pct = max(0, min(100, int(pct)))
        if pct == self._current_pct:
            return
        # Same gamma correction as the pigpio backend, so a given percentage
        # looks the same whichever backend a device happens to be using.
        self._led.value = (pct / 100.0) ** LIGHT_GAMMA
        self._current_pct = pct

    def close(self) -> None:
        try:
            self._led.value = 0
        except Exception:
            pass
        try:
            self._led.close()
        except Exception:
            pass


def _try_make_pigpio_backend(gpio_pin: int) -> _LedBackend | None:
    """Return a working PigpioBackend, or None on any failure (logged once)."""
    try:
        return PigpioBackend(gpio_pin)
    except ImportError:
        logging.info(
            "pigpio Python module not available — trying the lgpio backend. "
            "(pigpio has no package on Debian Trixie and later.)"
        )
        return None
    except Exception as e:
        logging.info(
            "Could not open pigpio (%s) — trying the lgpio backend. "
            "Is pigpiod running? systemctl enable --now pigpiod",
            e,
        )
        return None


def _try_make_lgpio_backend(gpio_pin: int) -> _LedBackend | None:
    """Return a working LgpioBackend, or None if unsuitable (logged once).

    Restricted to hardware-PWM pins on purpose. Unlike pigpio, which clocked
    software PWM off the DMA engine and so was immune to CPU load, lgpio times
    its pulses on the CPU: on a tracking ethoscope - which runs its Pi at
    saturation, and thermally throttled when enclosed - that produces visibly
    flickering light. Flicker is a salient visual stimulus to the animals, so a
    steady lamp that cannot dim beats a dimmable one that flickers.
    """
    if gpio_pin not in _HW_PWM_GPIOS:
        logging.warning(
            "GPIO%s is not hardware-PWM capable and pigpio is unavailable, so "
            "PWM would be CPU-timed and visibly flicker under tracking load. "
            "Falling back to steady on/off. For dimming and fades, wire the LED "
            "to a hardware-PWM GPIO (%s).",
            gpio_pin,
            ", ".join(str(p) for p in sorted(_HW_PWM_GPIOS)),
        )
        return None

    try:
        return LgpioBackend(gpio_pin)
    except ImportError:
        logging.warning(
            "gpiozero/lgpio not available — falling back to pinctrl backend "
            "(no fade support). Install with: "
            "apt-get install python3-gpiozero python3-lgpio"
        )
        return None
    except Exception as e:
        logging.warning(
            "Could not open lgpio (%s) — falling back to pinctrl backend "
            "(no fade support)",
            e,
        )
        return None


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class LightController:
    """
    Controls a GPIO-connected LED based on a time-of-day schedule.

    Reads a JSON config file at regular intervals and ramps the LED toward
    the schedule's target brightness, honouring the schedule's
    ``fade_in_seconds`` / ``fade_out_seconds`` / ``max_light``.

    Args:
        config_file: Path to the JSON schedule config file.
        poll_interval: Seconds between config file checks at steady state.
        gpio_pin: BCM GPIO pin number (default 17 for legacy boards; 12 is
            the recommended pin for new boards because it's PWM0).
        socket_path: Unix socket path for the control API.
        backend: Optional explicit backend instance. If omitted, attempts
            ``PigpioBackend`` first and falls back to ``PinctrlBackend``.
    """

    def __init__(
        self,
        config_file=DEFAULT_CONFIG_FILE,
        poll_interval=DEFAULT_POLL_INTERVAL,
        gpio_pin=DEFAULT_GPIO_PIN,
        socket_path=DEFAULT_SOCKET_PATH,
        backend: _LedBackend | None = None,
    ):
        self.config_file = config_file
        self.poll_interval = poll_interval
        self.gpio_pin = int(gpio_pin)
        self.socket_path = socket_path
        self._backend: _LedBackend = backend or self._select_backend(self.gpio_pin)
        self._current_pct: int = 0  # last value written to the backend
        self._target_pct: int = 0  # commanded value (schedule or force)
        self._force_pct: int | None = None  # None = follow schedule
        self._running = True
        self._lock = threading.Lock()
        self._server_sock = None
        self._listener_thread = None

    @staticmethod
    def _select_backend(gpio_pin: int) -> _LedBackend:
        backend = _try_make_pigpio_backend(gpio_pin)
        if backend is not None:
            return backend
        backend = _try_make_lgpio_backend(gpio_pin)
        if backend is not None:
            return backend
        return PinctrlBackend(gpio_pin)

    @property
    def supports_fade(self) -> bool:
        return self._backend.supports_fade

    def set_led_pct(self, pct: int) -> None:
        """Drive the backend to ``pct`` immediately (no ramp). Use ``ramp_to`` for fades."""
        pct = max(0, min(100, int(pct)))
        self._backend.set_pct(pct)
        self._current_pct = pct

    # Backwards-compatible wrapper for external callers that think in terms of on/off.
    def set_led(self, on: bool) -> None:
        target = self._effective_max_light() if on else 0
        self.set_led_pct(target)

    def ramp_to(self, target_pct: int, fade_seconds: float) -> None:
        """Ramp the LED from its current pct to ``target_pct`` along a sunset-like curve.

        Uses Perlin smoothstep ``S(t) = 3t² − 2t³`` for the time→brightness
        mapping: zero derivative at both endpoints, which makes the start and
        end of the transition feel gentle (dawn-/dusk-like) and the middle
        the fastest. Symmetric for both fade-in and fade-out.

        Backends without fade support, or any call with ``fade_seconds <= 0``,
        jump straight to the target (hard transition). Honours
        ``self._running`` so a shutdown signal interrupts long fades.
        """
        target_pct = max(0, min(100, int(target_pct)))
        start_pct = self._current_pct
        if target_pct == start_pct:
            return
        if not self._backend.supports_fade or fade_seconds <= 0:
            self.set_led_pct(target_pct)
            return

        span = abs(target_pct - start_pct)
        steps = min(_FADE_STEPS, span)
        if steps <= 1:
            self.set_led_pct(target_pct)
            return
        step_ms = max(_FADE_STEP_FLOOR_MS, int(round((fade_seconds * 1000) / steps)))

        # Walk the curve. At each step, evaluate smoothstep(t/steps) and map
        # to the [start, target] range.
        for i in range(1, steps + 1):
            if not self._running:
                break
            t = i / steps
            smooth = smoothstep(t)  # 0 → 0, 1 → 1, S-shaped
            pct = int(round(start_pct + (target_pct - start_pct) * smooth))
            # Clamp inside the [start, target] envelope (rounding can overshoot by 1).
            if target_pct > start_pct:
                pct = min(pct, target_pct)
            else:
                pct = max(pct, target_pct)
            self.set_led_pct(pct)
            time.sleep(step_ms / 1000.0)

        # Final write guarantees we land exactly on the target even after early-exit rounding.
        if self._running and self._current_pct != target_pct:
            self.set_led_pct(target_pct)

    def _effective_max_light(self) -> int:
        """Read max_light from the schedule file (defaults to 100). Safe to call often."""
        full = self.read_schedule_full()
        return int(full.get("max_light", DEFAULT_MAX_LIGHT))

    def read_schedule(self):
        """
        Read and parse the schedule config file.

        Returns:
            Tuple of (lights_on, lights_off, active) where times are
            strings in HH:MM format and active is a boolean.
            Returns ("", "", False) on any error.

        Note: kept as a 3-tuple for backwards compatibility. For the full
        schedule including period, anchor and fade, use ``read_schedule_full()``.
        """
        full = self.read_schedule_full()
        if not full.get("active"):
            return ("", "", False)
        return (full["lights_on"], full["lights_off"], True)

    def read_schedule_full(self):
        """
        Read and parse the schedule config file, including T-cycle + fade fields.

        Returns:
            Dict with keys:
              - active (bool)
              - lights_on, lights_off (HH:MM strings)
              - period_minutes (int, 1440 = wall-clock 24h)
              - anchor (float unix ts, or None for wall-clock midnight mode)
              - fade_in_seconds, fade_out_seconds (int >= 0; default 1)
              - max_light (int 0..100; default 100)
            Returns ``{"active": False, ...defaults}`` on any error or inactive schedule.
        """
        defaults_inactive = {
            "active": False,
            "fade_in_seconds": DEFAULT_FADE_IN_SECONDS,
            "fade_out_seconds": DEFAULT_FADE_OUT_SECONDS,
            "max_light": DEFAULT_MAX_LIGHT,
            "crepuscular": False,
        }
        try:
            if not os.path.exists(self.config_file):
                return defaults_inactive

            with open(self.config_file) as f:
                data = json.load(f)

            fade_in = _coerce_int(
                data.get("fade_in_seconds"), DEFAULT_FADE_IN_SECONDS, lo=0
            )
            fade_out = _coerce_int(
                data.get("fade_out_seconds"), DEFAULT_FADE_OUT_SECONDS, lo=0
            )
            max_light = _coerce_int(
                data.get("max_light"), DEFAULT_MAX_LIGHT, lo=0, hi=100
            )
            crepuscular = bool(data.get("crepuscular", False))

            extras = {
                "fade_in_seconds": fade_in,
                "fade_out_seconds": fade_out,
                "max_light": max_light,
                "crepuscular": crepuscular,
            }

            if not data.get("active", False):
                return {**defaults_inactive, **extras}

            lights_on = data.get("lights_on", "")
            lights_off = data.get("lights_off", "")
            if not lights_on or not lights_off:
                return {**defaults_inactive, **extras}

            period_minutes = _coerce_int(data.get("period_minutes"), 1440, lo=1)

            anchor_raw = data.get("anchor")
            try:
                anchor = float(anchor_raw) if anchor_raw is not None else None
            except (TypeError, ValueError):
                anchor = None

            return {
                "active": True,
                "lights_on": lights_on,
                "lights_off": lights_off,
                "period_minutes": period_minutes,
                "anchor": anchor,
                **extras,
            }

        except (json.JSONDecodeError, OSError) as e:
            logging.warning("Failed to read schedule config: %s", e)
            return defaults_inactive

    @staticmethod
    def parse_time(time_str):
        """
        Parse an HH:MM time string into a datetime.time object.

        Args:
            time_str: Time string in HH:MM format.

        Returns:
            datetime.time object, or None if parsing fails.
        """
        try:
            parts = time_str.strip().split(":")
            return datetime.time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return None

    @staticmethod
    def should_light_be_on(
        lights_on_str,
        lights_off_str,
        now=None,
        period_minutes=None,
        anchor=None,
    ):
        """
        Determine if the light should be on for the given schedule.

        Two modes, picked automatically:

        - **Wall-clock mode** (default, used when ``anchor`` is None and
          period_minutes is None or 1440): lights_on/lights_off are HH:MM
          times of day, cycle repeats every 24 h anchored to local midnight.
          Handles schedules that cross midnight (e.g. 22:00–06:00).
        - **Anchored / T-cycle mode**: lights_on/lights_off are HH:MM
          *offsets* into a cycle of length ``period_minutes`` starting at
          unix timestamp ``anchor``. Used for non-24 h cycles or to
          phase-lock a 24 h cycle to a chosen wall-clock moment.

        Args:
            lights_on_str: HH:MM string for lights-on.
            lights_off_str: HH:MM string for lights-off.
            now: Optional override for the current moment. In wall-clock
                mode accepts a ``datetime.time``; in anchored mode accepts a
                ``datetime.datetime`` or a unix timestamp (float).
            period_minutes: Cycle length in minutes. None or 1440 with no
                anchor → wall-clock mode.
            anchor: Unix timestamp marking the start of the cycle (ZT0).
                Required for non-24 h periods.

        Returns:
            True if the light should be on, False otherwise (including any
            unparseable inputs).
        """
        on_time = LightController.parse_time(lights_on_str)
        off_time = LightController.parse_time(lights_off_str)
        if on_time is None or off_time is None:
            return False

        on_seconds = on_time.hour * 3600 + on_time.minute * 60
        off_seconds = off_time.hour * 3600 + off_time.minute * 60

        # Pick mode. Anchored mode is used iff an anchor is supplied or the
        # period is non-24 h. A non-24 h period without an anchor is invalid
        # — refuse rather than silently fall back to a phase nobody asked for.
        use_anchored = anchor is not None or (
            period_minutes is not None and int(period_minutes) != 1440
        )

        if use_anchored:
            if anchor is None:
                return False
            try:
                period_s = int(period_minutes) * 60 if period_minutes else 86400
            except (TypeError, ValueError):
                return False
            if period_s <= 0:
                return False
            if isinstance(now, datetime.datetime):
                now_ts = now.timestamp()
            elif isinstance(now, (int, float)):
                now_ts = float(now)
            else:
                now_ts = time.time()
            phase = (now_ts - float(anchor)) % period_s
            current_seconds = phase
        else:
            if isinstance(now, datetime.datetime):
                t = now.time()
            elif isinstance(now, datetime.time):
                t = now
            else:
                t = datetime.datetime.now().time()
            current_seconds = t.hour * 3600 + t.minute * 60 + t.second

        if on_seconds == off_seconds:
            # Same on/off time means always on (24h light).
            return True
        if on_seconds < off_seconds:
            return on_seconds <= current_seconds < off_seconds
        # Wrap-around (crosses cycle end): e.g. 22:00 → 06:00 in 24 h mode,
        # or 18:00 → 02:00 within a 21 h cycle.
        return current_seconds >= on_seconds or current_seconds < off_seconds

    def set_force(self, value):
        """
        Override the schedule.

        ``value`` accepts ``True`` (force to max_light), ``False`` (force off),
        ``None`` (release), or an integer 0..100 for an explicit brightness.
        Applies immediately, in addition to being honoured by the next loop
        tick. Force overrides don't use a fade — they're for bench testing or
        emergency-on during target detection.
        """
        with self._lock:
            if value is None:
                self._force_pct = None
            elif value is True:
                self._force_pct = self._effective_max_light()
            elif value is False:
                self._force_pct = 0
            else:
                pct = max(0, min(100, int(value)))
                self._force_pct = pct
            applied = self._force_pct
        if applied is not None:
            self.set_led_pct(applied)

    def _status_dict(self):
        with self._lock:
            force = self._force_pct
            current = self._current_pct
        sched = self.read_schedule_full()
        return {
            "led": current,  # 0..100 (true level)
            "mode": "forced" if force is not None else "schedule",
            "force": force,  # None or 0..100
            "schedule_active": sched.get("active", False),
            "lights_on": sched.get("lights_on", ""),
            "lights_off": sched.get("lights_off", ""),
            "period_minutes": sched.get("period_minutes"),
            "anchor": sched.get("anchor"),
            "fade_in_seconds": sched.get("fade_in_seconds", DEFAULT_FADE_IN_SECONDS),
            "fade_out_seconds": sched.get("fade_out_seconds", DEFAULT_FADE_OUT_SECONDS),
            "max_light": sched.get("max_light", DEFAULT_MAX_LIGHT),
            "crepuscular": sched.get("crepuscular", False),
            "backend": str(self._backend.name),
            "fade_supported": self._backend.supports_fade,
        }

    def _handle_command(self, cmd):
        """Translate one wire command into a one-line response (no trailing newline).

        Protocol:
          FORCE ON          — ramp to max_light immediately (no fade)
          FORCE OFF         — drive to 0 immediately
          FORCE PCT <0-100> — drive to explicit percent
          RELEASE           — release any force, resume schedule
          STATUS            — JSON status dict
        """
        upper = cmd.upper().split()
        if not upper:
            return "ERR empty command"
        head = upper[0]
        if head == "FORCE" and len(upper) >= 2:
            sub = upper[1]
            if sub == "ON":
                self.set_force(True)
                return "OK"
            if sub == "OFF":
                self.set_force(False)
                return "OK"
            if sub == "PCT" and len(upper) >= 3:
                try:
                    pct = int(upper[2])
                except ValueError:
                    return f"ERR bad pct: {upper[2]!r}"
                self.set_force(pct)
                return "OK"
        if head == "RELEASE":
            self.set_force(None)
            return "OK"
        if head == "STATUS":
            return json.dumps(self._status_dict())
        return f"ERR unknown command: {cmd!r}"

    def _start_socket_listener(self):
        """Bind the Unix socket and spawn a daemon thread to accept commands."""
        if not self.socket_path:
            return
        try:
            os.makedirs(os.path.dirname(self.socket_path), exist_ok=True)
        except OSError as e:
            logging.warning("Could not create socket directory: %s", e)

        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logging.warning("Could not remove stale socket %s: %s", self.socket_path, e)

        try:
            self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._server_sock.bind(self.socket_path)
            # Reason: single-tenant ethoscope; allow any local user (e.g. ethoscope-light CLI) to connect
            os.chmod(self.socket_path, 0o666)
            self._server_sock.listen(4)
            self._server_sock.settimeout(_LISTENER_ACCEPT_TIMEOUT)
        except OSError as e:
            logging.error("Could not bind control socket %s: %s", self.socket_path, e)
            self._server_sock = None
            return

        self._listener_thread = threading.Thread(
            target=self._listener_loop, name="light-daemon-listener", daemon=True
        )
        self._listener_thread.start()
        logging.info("Light daemon control socket: %s", self.socket_path)

    def _listener_loop(self):
        while self._running and self._server_sock is not None:
            try:
                conn, _ = self._server_sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                conn.settimeout(_CLIENT_TIMEOUT)
                data = conn.recv(_MAX_CMD_BYTES)
                cmd = data.decode("utf-8", errors="replace").strip()
                response = self._handle_command(cmd)
                conn.sendall((response + "\n").encode("utf-8"))
            except Exception as e:
                logging.warning("Light daemon socket handler error: %s", e)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _stop_socket_listener(self):
        sock = self._server_sock
        self._server_sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=1.0)
            self._listener_thread = None
        if self.socket_path:
            try:
                os.unlink(self.socket_path)
            except FileNotFoundError:
                pass
            except OSError as e:
                logging.warning("Could not remove socket on shutdown: %s", e)

    def _compute_target(self) -> tuple[int, float]:
        """Decide the target pct and fade duration for the current tick.

        Returns ``(target_pct, fade_seconds)``. Forced state bypasses the
        fade (fade_seconds = 0).
        """
        with self._lock:
            force = self._force_pct
        if force is not None:
            return force, 0.0

        sched = self.read_schedule_full()
        if not sched.get("active"):
            # No schedule = off, use fade_out so the LED dims off gracefully on stop.
            return 0, float(sched.get("fade_out_seconds", DEFAULT_FADE_OUT_SECONDS))

        on = self.should_light_be_on(
            sched["lights_on"],
            sched["lights_off"],
            period_minutes=sched.get("period_minutes"),
            anchor=sched.get("anchor"),
        )
        max_light = int(sched.get("max_light", DEFAULT_MAX_LIGHT))
        target = max_light if on else 0
        # Crepuscular toggle off → instant transition (no fade), matching the
        # legacy hard on/off behaviour. Keeps fade_in/out fields configurable
        # but inert until the operator opts in.
        if not sched.get("crepuscular", False):
            return target, 0.0
        # Choose the fade direction based on whether we're going up or down.
        rising = target > self._current_pct
        fade_field = "fade_in_seconds" if rising else "fade_out_seconds"
        default = DEFAULT_FADE_IN_SECONDS if rising else DEFAULT_FADE_OUT_SECONDS
        fade_s = float(sched.get(fade_field, default))
        return target, fade_s

    def run(self):
        """
        Main polling loop. Reads schedule and controls LED until stopped.
        Honours any force override set via the control socket.
        """
        logging.info(
            "Light daemon started. Config: %s, Poll: %ds, GPIO: %d, backend: %s",
            self.config_file,
            self.poll_interval,
            self.gpio_pin,
            self._backend.name,
        )
        self._start_socket_listener()

        try:
            while self._running:
                target, fade_s = self._compute_target()
                self.ramp_to(target, fade_s)

                # Sleep in small increments so we can respond to signals promptly
                for _ in range(self.poll_interval):
                    if not self._running:
                        break
                    time.sleep(1)
        finally:
            self._stop_socket_listener()
            try:
                self.set_led_pct(0)
            except Exception:
                pass
            try:
                self._backend.close()
            except Exception:
                pass
            logging.info("Light daemon stopped.")

    def shutdown(self, signum=None, frame=None):
        """
        Signal handler: stop the main loop (LED turned off in run()).
        """
        logging.info("Received signal %s, shutting down...", signum)
        self._running = False


def _coerce_int(
    value, default: int, *, lo: int | None = None, hi: int | None = None
) -> int:
    """Best-effort int coercion with optional clamping. Falls back to ``default``."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if lo is not None and result < lo:
        return lo
    if hi is not None and result > hi:
        return hi
    return result


class LightDaemonClient:
    """
    Tiny client for the light daemon's Unix-socket control API.

    Each method opens a fresh connection, sends one line, reads one line, closes.
    Raises LightDaemonUnavailable if the daemon isn't reachable.
    """

    def __init__(self, socket_path=DEFAULT_SOCKET_PATH, timeout=_CLIENT_TIMEOUT):
        self.socket_path = socket_path
        self.timeout = timeout

    def _request(self, command):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            try:
                sock.connect(self.socket_path)
                sock.sendall((command + "\n").encode("utf-8"))
                chunks = []
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    if b"\n" in chunk:
                        break
            finally:
                sock.close()
        except (FileNotFoundError, ConnectionRefusedError) as e:
            raise LightDaemonUnavailable(str(e)) from e
        except TimeoutError as e:
            raise LightDaemonUnavailable("timeout talking to light daemon") from e
        except OSError as e:
            raise LightDaemonUnavailable(str(e)) from e

        response = b"".join(chunks).decode("utf-8", errors="replace").strip()
        if response.startswith("ERR"):
            raise LightDaemonUnavailable(response)
        return response

    def force_on(self):
        return self._request("FORCE ON")

    def force_off(self):
        return self._request("FORCE OFF")

    def force_pct(self, pct: int):
        return self._request(f"FORCE PCT {int(pct)}")

    def release(self):
        return self._request("RELEASE")

    def status(self):
        response = self._request("STATUS")
        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            raise LightDaemonUnavailable(
                f"unparseable status response: {response!r}"
            ) from e


def main():
    parser = OptionParser(description="Ethoscope LED daylight controller daemon")
    parser.add_option(
        "-c",
        "--config-file",
        dest="config_file",
        default=DEFAULT_CONFIG_FILE,
        help=f"Path to light schedule JSON config file (default: {DEFAULT_CONFIG_FILE})",
    )
    parser.add_option(
        "-p",
        "--poll-interval",
        dest="poll_interval",
        type="int",
        default=DEFAULT_POLL_INTERVAL,
        help=f"Seconds between schedule checks (default: {DEFAULT_POLL_INTERVAL})",
    )
    parser.add_option(
        "-g",
        "--gpio",
        dest="gpio_pin",
        type="int",
        default=DEFAULT_GPIO_PIN,
        help=f"BCM GPIO pin number (default: {DEFAULT_GPIO_PIN}; "
        "GPIO12/13/18/19 enable hardware PWM)",
    )
    parser.add_option(
        "-s",
        "--socket",
        dest="socket_path",
        default=DEFAULT_SOCKET_PATH,
        help=f"Path to the control socket (default: {DEFAULT_SOCKET_PATH}). "
        "Pass an empty string to disable the socket listener.",
    )
    parser.add_option(
        "--backend",
        dest="backend",
        default="auto",
        help="LED backend: 'auto' (default; pigpio with pinctrl fallback), "
        "'pigpio', or 'pinctrl'.",
    )
    parser.add_option(
        "-D",
        "--debug",
        dest="debug",
        default=False,
        action="store_true",
        help="Enable debug logging",
    )

    options, args = parser.parse_args()

    log_level = logging.DEBUG if options.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    backend: _LedBackend | None
    if options.backend == "pigpio":
        backend = _try_make_pigpio_backend(options.gpio_pin)
        if backend is None:
            logging.error(
                "Explicit --backend=pigpio requested but not available. Aborting."
            )
            raise SystemExit(2)
    elif options.backend == "pinctrl":
        backend = PinctrlBackend(options.gpio_pin)
    elif options.backend == "auto":
        backend = None  # let LightController auto-select
    else:
        parser.error(f"unknown --backend: {options.backend!r}")
        return

    controller = LightController(
        config_file=options.config_file,
        poll_interval=options.poll_interval,
        gpio_pin=options.gpio_pin,
        socket_path=options.socket_path or None,
        backend=backend,
    )

    # Register signal handlers for clean shutdown
    signal.signal(signal.SIGTERM, controller.shutdown)
    signal.signal(signal.SIGINT, controller.shutdown)

    controller.run()


if __name__ == "__main__":
    main()
