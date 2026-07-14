"""
Tests for the LED daylight controller daemon.

Covers the schedule algorithm (wall-clock + T-cycle), the JSON schedule
reader, the two backends (PinctrlBackend + PigpioBackend with auto-fallback),
the fade walker, the force-override state machine, and the Unix-socket
control protocol.
"""

import datetime
import json
import sys
import time
import types
from unittest.mock import MagicMock, call, patch

import pytest

from ethoscope.hardware.interfaces.light_daemon import (
    DEFAULT_FADE_IN_SECONDS,
    DEFAULT_FADE_OUT_SECONDS,
    DEFAULT_MAX_LIGHT,
    LIGHT_GAMMA,
    LightController,
    LightDaemonClient,
    LightDaemonUnavailable,
    PigpioBackend,
    PinctrlBackend,
)


def _expected_hw_duty(pct: int) -> int:
    """Mirror PigpioBackend's gamma curve for hardware_PWM (range 1_000_000)."""
    return int(round((pct / 100.0) ** LIGHT_GAMMA * 1_000_000))


def _expected_sw_duty(pct: int) -> int:
    """Mirror PigpioBackend's gamma curve for set_PWM_dutycycle (range 1000)."""
    return int(round((pct / 100.0) ** LIGHT_GAMMA * 1000))


def _pinctrl_controller(**kwargs):
    """Build a LightController forced onto the pinctrl backend.

    Tests that don't care about fades use this so they can assert against
    subprocess calls without dealing with the pigpio path.
    """
    kwargs.setdefault("gpio_pin", 17)
    kwargs.setdefault("backend", PinctrlBackend(kwargs["gpio_pin"]))
    return LightController(**kwargs)


def _fade_backend(name: str = "mock"):
    """A fade-capable MagicMock backend with a JSON-serialisable ``.name`` attr."""
    backend = MagicMock(supports_fade=True)
    backend.name = name
    return backend


class TestShouldLightBeOn:
    """Tests for the time-based schedule logic."""

    def test_normal_schedule_during_day(self):
        noon = datetime.time(12, 0)
        assert LightController.should_light_be_on("07:00", "19:00", now=noon) is True

    def test_normal_schedule_during_night(self):
        midnight = datetime.time(0, 0)
        assert (
            LightController.should_light_be_on("07:00", "19:00", now=midnight) is False
        )

    def test_normal_schedule_at_on_time(self):
        assert (
            LightController.should_light_be_on(
                "07:00", "19:00", now=datetime.time(7, 0)
            )
            is True
        )

    def test_normal_schedule_at_off_time(self):
        assert (
            LightController.should_light_be_on(
                "07:00", "19:00", now=datetime.time(19, 0)
            )
            is False
        )

    def test_midnight_crossing_during_night(self):
        assert (
            LightController.should_light_be_on(
                "22:00", "06:00", now=datetime.time(23, 0)
            )
            is True
        )

    def test_midnight_crossing_during_day(self):
        assert (
            LightController.should_light_be_on(
                "22:00", "06:00", now=datetime.time(12, 0)
            )
            is False
        )

    def test_midnight_crossing_early_morning(self):
        assert (
            LightController.should_light_be_on(
                "22:00", "06:00", now=datetime.time(3, 0)
            )
            is True
        )

    def test_equal_times_always_on(self):
        assert (
            LightController.should_light_be_on(
                "07:00", "07:00", now=datetime.time(12, 0)
            )
            is True
        )

    def test_short_photoperiod(self):
        assert (
            LightController.should_light_be_on(
                "08:00", "16:00", now=datetime.time(12, 0)
            )
            is True
        )
        assert (
            LightController.should_light_be_on(
                "08:00", "16:00", now=datetime.time(17, 0)
            )
            is False
        )

    def test_invalid_inputs_return_false(self):
        assert (
            LightController.should_light_be_on(
                "invalid", "19:00", now=datetime.time(12, 0)
            )
            is False
        )
        assert (
            LightController.should_light_be_on("07:00", "bad", now=datetime.time(12, 0))
            is False
        )
        assert (
            LightController.should_light_be_on("", "", now=datetime.time(12, 0))
            is False
        )


class TestAnchoredCycle:
    """Tests for T-cycle (period+anchor) mode."""

    def _now(self, anchor_ts, hours_after):
        return datetime.datetime.fromtimestamp(anchor_ts + hours_after * 3600)

    def test_t21_in_light_phase(self):
        anchor = 1_700_000_000.0
        assert (
            LightController.should_light_be_on(
                "00:00",
                "12:00",
                now=self._now(anchor, 3),
                period_minutes=21 * 60,
                anchor=anchor,
            )
            is True
        )

    def test_t21_in_dark_phase(self):
        anchor = 1_700_000_000.0
        assert (
            LightController.should_light_be_on(
                "00:00",
                "12:00",
                now=self._now(anchor, 15),
                period_minutes=21 * 60,
                anchor=anchor,
            )
            is False
        )

    def test_t21_wraps_into_next_cycle(self):
        anchor = 1_700_000_000.0
        assert (
            LightController.should_light_be_on(
                "00:00",
                "12:00",
                now=self._now(anchor, 22),
                period_minutes=21 * 60,
                anchor=anchor,
            )
            is True
        )

    def test_anchored_requires_anchor(self):
        assert (
            LightController.should_light_be_on(
                "00:00",
                "12:00",
                now=datetime.datetime(2026, 5, 1, 12),
                period_minutes=21 * 60,
                anchor=None,
            )
            is False
        )


class TestParseTime:
    def test_valid(self):
        assert LightController.parse_time("07:00") == datetime.time(7, 0)
        assert LightController.parse_time("23:59") == datetime.time(23, 59)

    def test_invalid(self):
        assert LightController.parse_time("") is None
        assert LightController.parse_time("invalid") is None
        assert LightController.parse_time("25:00") is None
        assert LightController.parse_time("12:60") is None


class TestReadScheduleFull:
    """The schedule reader includes the Phase-3 fade fields with safe defaults."""

    def test_missing_file_returns_inactive_with_defaults(self, tmp_path):
        controller = _pinctrl_controller(config_file=str(tmp_path / "missing.json"))
        sched = controller.read_schedule_full()
        assert sched["active"] is False
        assert sched["fade_in_seconds"] == DEFAULT_FADE_IN_SECONDS
        assert sched["fade_out_seconds"] == DEFAULT_FADE_OUT_SECONDS
        assert sched["max_light"] == DEFAULT_MAX_LIGHT

    def test_legacy_config_without_fade_fields(self, tmp_path):
        """A pre-Phase-3 schedule JSON parses cleanly with defaults filled in."""
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(
            json.dumps({"lights_on": "07:00", "lights_off": "19:00", "active": True})
        )
        controller = _pinctrl_controller(config_file=str(config_file))
        sched = controller.read_schedule_full()
        assert sched["active"] is True
        assert sched["lights_on"] == "07:00"
        assert sched["period_minutes"] == 1440
        assert sched["anchor"] is None
        assert sched["fade_in_seconds"] == 1
        assert sched["fade_out_seconds"] == 1
        assert sched["max_light"] == 100

    def test_tcycle_with_fade_fields(self, tmp_path):
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(
            json.dumps(
                {
                    "lights_on": "00:00",
                    "lights_off": "12:00",
                    "active": True,
                    "period_minutes": 1260,
                    "anchor": 1715000000.0,
                    "fade_in_seconds": 30,
                    "fade_out_seconds": 60,
                    "max_light": 75,
                    "crepuscular": True,
                }
            )
        )
        controller = _pinctrl_controller(config_file=str(config_file))
        sched = controller.read_schedule_full()
        assert sched["period_minutes"] == 1260
        assert sched["fade_in_seconds"] == 30
        assert sched["fade_out_seconds"] == 60
        assert sched["max_light"] == 75
        assert sched["crepuscular"] is True

    def test_crepuscular_defaults_to_false(self, tmp_path):
        """Schedules without the crepuscular field default to False (legacy hard on/off)."""
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(
            json.dumps({"lights_on": "07:00", "lights_off": "19:00", "active": True})
        )
        controller = _pinctrl_controller(config_file=str(config_file))
        sched = controller.read_schedule_full()
        assert sched["crepuscular"] is False

    def test_max_light_clamped(self, tmp_path):
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(
            json.dumps(
                {
                    "lights_on": "07:00",
                    "lights_off": "19:00",
                    "active": True,
                    "max_light": 9999,
                }
            )
        )
        controller = _pinctrl_controller(config_file=str(config_file))
        sched = controller.read_schedule_full()
        assert sched["max_light"] == 100

    def test_malformed_json_returns_inactive(self, tmp_path):
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text("{bad json")
        controller = _pinctrl_controller(config_file=str(config_file))
        assert controller.read_schedule_full()["active"] is False


class TestReadSchedule:
    """Legacy 3-tuple interface is preserved for backwards-compatible callers."""

    def test_missing_file(self, tmp_path):
        controller = _pinctrl_controller(config_file=str(tmp_path / "missing.json"))
        _, _, active = controller.read_schedule()
        assert active is False

    def test_valid(self, tmp_path):
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(
            json.dumps({"lights_on": "07:00", "lights_off": "19:00", "active": True})
        )
        controller = _pinctrl_controller(config_file=str(config_file))
        lights_on, lights_off, active = controller.read_schedule()
        assert (lights_on, lights_off, active) == ("07:00", "19:00", True)


class TestPinctrlBackend:
    """The legacy backend: binary on/off via the `pinctrl` shell-out."""

    @patch("subprocess.run")
    def test_set_pct_on_drives_high(self, mock_run):
        backend = PinctrlBackend(17)
        backend.set_pct(100)
        mock_run.assert_called_once_with(
            ["pinctrl", "set", "17", "op", "dh"],
            check=True,
            capture_output=True,
            timeout=5,
        )

    @patch("subprocess.run")
    def test_set_pct_off_drives_low(self, mock_run):
        backend = PinctrlBackend(17)
        backend.set_pct(0)
        mock_run.assert_called_once_with(
            ["pinctrl", "set", "17", "op", "dl"],
            check=True,
            capture_output=True,
            timeout=5,
        )

    @patch("subprocess.run")
    def test_threshold_at_50_percent(self, mock_run):
        backend = PinctrlBackend(17)
        # < 50 → off
        backend.set_pct(49)
        mock_run.assert_called_with(
            ["pinctrl", "set", "17", "op", "dl"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        mock_run.reset_mock()
        # >= 50 → on
        backend.set_pct(50)
        mock_run.assert_called_with(
            ["pinctrl", "set", "17", "op", "dh"],
            check=True,
            capture_output=True,
            timeout=5,
        )

    @patch("subprocess.run")
    def test_no_redundant_calls(self, mock_run):
        backend = PinctrlBackend(17)
        backend.set_pct(100)
        backend.set_pct(100)
        assert mock_run.call_count == 1

    def test_does_not_support_fade(self):
        assert PinctrlBackend(17).supports_fade is False


def _fake_pigpio_module(*, connected: bool = True):
    """Build a fake `pigpio` module sufficient for PigpioBackend.

    Stored on sys.modules so `import pigpio` inside PigpioBackend resolves
    to this fake. The single `pi` instance returned by `pigpio.pi()` is a
    MagicMock so call counts are inspectable.
    """
    mod = types.ModuleType("pigpio")
    mod.OUTPUT = 1
    pi_instance = MagicMock(name="pigpio.pi instance")
    pi_instance.connected = connected
    mod.pi = MagicMock(return_value=pi_instance)
    mod._instance = pi_instance  # test access
    return mod


class TestPigpioBackendDispatch:
    """The pigpio backend picks hardware vs DMA-software PWM by GPIO number."""

    def setup_method(self):
        self._fake = _fake_pigpio_module()
        sys.modules["pigpio"] = self._fake

    def teardown_method(self):
        sys.modules.pop("pigpio", None)

    def test_hardware_pwm_dispatch_on_gpio12(self):
        backend = PigpioBackend(12)
        backend.set_pct(50)
        pi = self._fake._instance
        # set_PWM_dutycycle should NOT have been used on a HW-PWM pin.
        pi.set_PWM_dutycycle.assert_not_called()
        # hardware_PWM called at least once (init writes 0, then 50%).
        assert pi.hardware_PWM.called
        last_call_args = pi.hardware_PWM.call_args
        assert last_call_args[0][0] == 12  # GPIO12
        # Duty is gamma-corrected to keep perceived brightness linear.
        assert last_call_args[0][2] == _expected_hw_duty(50)

    def test_hardware_pwm_dispatch_on_gpio18(self):
        backend = PigpioBackend(18)
        backend.set_pct(25)
        pi = self._fake._instance
        pi.hardware_PWM.assert_called()
        last = pi.hardware_PWM.call_args
        assert last[0][0] == 18
        assert last[0][2] == _expected_hw_duty(25)

    def test_software_pwm_dispatch_on_gpio17(self):
        """GPIO17 is the legacy LED pin — falls into DMA-software PWM."""
        backend = PigpioBackend(17)
        backend.set_pct(50)
        pi = self._fake._instance
        pi.hardware_PWM.assert_not_called()
        # init sets frequency, range, then writes 0, then the gamma-corrected duty for 50%.
        pi.set_PWM_frequency.assert_called_with(17, 5000)
        pi.set_PWM_range.assert_called_with(17, 1000)
        last = pi.set_PWM_dutycycle.call_args
        assert last[0] == (17, _expected_sw_duty(50))

    def test_pct_clamped_to_0_100(self):
        backend = PigpioBackend(17)
        backend.set_pct(-50)
        backend.set_pct(150)
        pi = self._fake._instance
        # Gamma preserves endpoints exactly: -50 → 0 duty, 150 → 1000 duty.
        assert pi.set_PWM_dutycycle.call_args_list[-2][0] == (17, 0)
        assert pi.set_PWM_dutycycle.call_args_list[-1][0] == (17, 1000)

    def test_skip_redundant_writes(self):
        backend = PigpioBackend(17)
        pi = self._fake._instance
        before = pi.set_PWM_dutycycle.call_count
        backend.set_pct(42)
        backend.set_pct(42)
        # Only one extra call despite two set_pct invocations.
        assert pi.set_PWM_dutycycle.call_count == before + 1

    def test_supports_fade(self):
        backend = PigpioBackend(17)
        assert backend.supports_fade is True


class TestBackendAutoFallback:
    """Daemon must auto-fall-back to pinctrl when pigpio is unavailable."""

    def setup_method(self):
        # Remove any cached pigpio module so the import inside PigpioBackend.__init__ fails.
        self._cached = sys.modules.pop("pigpio", None)

    def teardown_method(self):
        if self._cached is not None:
            sys.modules["pigpio"] = self._cached

    def test_falls_back_to_pinctrl_when_pigpio_missing(self):
        # Force the import to fail
        sys.modules["pigpio"] = None  # next import raises ImportError
        try:
            controller = LightController(gpio_pin=17, socket_path=None)
            assert isinstance(controller._backend, PinctrlBackend)
            assert controller.supports_fade is False
        finally:
            sys.modules.pop("pigpio", None)

    def test_falls_back_when_pigpiod_not_connected(self):
        sys.modules["pigpio"] = _fake_pigpio_module(connected=False)
        try:
            controller = LightController(gpio_pin=17, socket_path=None)
            assert isinstance(controller._backend, PinctrlBackend)
        finally:
            sys.modules.pop("pigpio", None)

    def test_uses_pigpio_when_available(self):
        sys.modules["pigpio"] = _fake_pigpio_module(connected=True)
        try:
            controller = LightController(gpio_pin=12, socket_path=None)
            assert isinstance(controller._backend, PigpioBackend)
            assert controller.supports_fade is True
        finally:
            sys.modules.pop("pigpio", None)


class TestRampWalker:
    """The fade walker steps the LED toward target at the configured rate."""

    def test_no_fade_when_backend_does_not_support(self):
        controller = _pinctrl_controller(gpio_pin=17, socket_path=None)
        with patch("subprocess.run"):
            controller.ramp_to(100, fade_seconds=5)
        # PinctrlBackend has _current_on True now
        assert controller._current_pct == 100

    def test_no_fade_when_target_equals_current(self):
        backend = _fade_backend()
        controller = LightController(gpio_pin=17, socket_path=None, backend=backend)
        controller._current_pct = 50
        controller.ramp_to(50, fade_seconds=10)
        # No writes when already at target
        backend.set_pct.assert_not_called()

    def test_no_fade_when_duration_zero(self):
        backend = _fade_backend()
        controller = LightController(gpio_pin=17, socket_path=None, backend=backend)
        controller._current_pct = 0
        controller.ramp_to(100, fade_seconds=0)
        backend.set_pct.assert_called_once_with(100)

    def test_ramp_up_visits_intermediate_values(self):
        backend = _fade_backend()
        controller = LightController(gpio_pin=17, socket_path=None, backend=backend)
        controller._current_pct = 0
        # Short fade so the test runs quickly.
        with patch("time.sleep"):
            controller.ramp_to(100, fade_seconds=0.5)
        # Last call should be the target.
        assert backend.set_pct.call_args_list[-1] == call(100)
        # Should have visited several intermediate values.
        assert backend.set_pct.call_count >= 50

    def test_ramp_down_visits_intermediate_values(self):
        backend = _fade_backend()
        controller = LightController(gpio_pin=17, socket_path=None, backend=backend)
        controller._current_pct = 100
        with patch("time.sleep"):
            controller.ramp_to(0, fade_seconds=0.5)
        assert backend.set_pct.call_args_list[-1] == call(0)
        # Should be monotonically non-increasing.
        # Reason: indexed rather than zip(values, values[1:]) — ruff targets
        # py311 and requires an explicit strict=, but the device package
        # supports 3.9, where zip() has no strict keyword at all.
        values = [c.args[0] for c in backend.set_pct.call_args_list]
        assert len(values) > 1
        for i in range(1, len(values)):
            assert values[i] <= values[i - 1]

    def test_ramp_follows_smoothstep_shape(self):
        """The walker should follow an S-curve, not a straight line.

        Smoothstep S(t)=3t²-2t³ has zero derivative at both endpoints, so
        the FIRST step from 0 should be much smaller than a LATE step (around
        the middle of the ramp). Sample three positions in the walk and
        verify the middle is moving faster than the edges.
        """
        backend = _fade_backend()
        controller = LightController(gpio_pin=17, socket_path=None, backend=backend)
        controller._current_pct = 0
        with patch("time.sleep"):
            controller.ramp_to(100, fade_seconds=1.0)
        values = [c.args[0] for c in backend.set_pct.call_args_list]
        n = len(values)
        assert n >= 20  # enough samples to look at deltas
        # Deltas between consecutive samples — middle should be largest.
        deltas = [values[i + 1] - values[i] for i in range(n - 1)]
        early = sum(deltas[: n // 4])
        mid = sum(deltas[n // 4 : 3 * n // 4])
        late = sum(deltas[3 * n // 4 :])
        # All three quarters together should sum to 100, and the middle half
        # (which is half the time) should contribute MORE than half — the
        # hallmark of an S-curve.
        assert mid > early + late, (
            f"Expected S-curve (mid={mid} > early+late={early + late}); "
            f"got linear-shaped {deltas}"
        )

    def test_shutdown_interrupts_long_fade(self):
        backend = _fade_backend()
        controller = LightController(gpio_pin=17, socket_path=None, backend=backend)
        controller._current_pct = 0
        controller._running = False  # pretend we've shut down before fade
        with patch("time.sleep"):
            controller.ramp_to(100, fade_seconds=100)
        # Loop exits immediately; only one step (we add the delta then check _running).
        # Either zero or one calls are acceptable; never the full ramp.
        assert backend.set_pct.call_count <= 2


class TestComputeTarget:
    """``_compute_target`` reads the schedule and decides the right pct/fade.

    For tests that need a stable "now" we use a T-cycle anchored at the
    desired wall-clock moment so we don't have to patch ``datetime.now``.
    """

    def test_active_schedule_uses_max_light(self, tmp_path):
        """Crepuscular ON + rising transition → fade_in_seconds, target = max_light."""
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(
            json.dumps(
                {
                    "lights_on": "00:00",
                    "lights_off": "23:59",  # almost always on
                    "active": True,
                    "max_light": 75,
                    "fade_in_seconds": 7,
                    "fade_out_seconds": 11,
                    "crepuscular": True,
                }
            )
        )
        backend = _fade_backend()
        controller = LightController(
            config_file=str(config_file),
            gpio_pin=17,
            socket_path=None,
            backend=backend,
        )
        controller._current_pct = 0  # rising
        target, fade = controller._compute_target()
        assert target == 75
        assert fade == 7  # fade_in chosen because rising

    def test_falling_uses_fade_out(self):
        """Use a T-cycle anchored such that 'now' is firmly in the dark phase
        to avoid having to patch datetime.now."""
        anchor = time.time() - 8 * 3600  # now is +8h into a 24h cycle
        backend = _fade_backend()
        # Build the controller with an inline schedule by writing the file.
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "lights_on": "00:00",
                    "lights_off": "06:00",  # cycle-relative
                    "active": True,
                    "period_minutes": 1440,
                    "anchor": anchor,
                    "max_light": 80,
                    "fade_in_seconds": 5,
                    "fade_out_seconds": 13,
                    "crepuscular": True,
                },
                f,
            )
            schedule_path = f.name

        controller = LightController(
            config_file=schedule_path,
            gpio_pin=17,
            socket_path=None,
            backend=backend,
        )
        controller._current_pct = 80  # falling
        target, fade = controller._compute_target()
        assert target == 0
        assert fade == 13

    def test_crepuscular_off_skips_fade(self, tmp_path):
        """Default behaviour: crepuscular off → fade=0 (hard transition)."""
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(
            json.dumps(
                {
                    "lights_on": "00:00",
                    "lights_off": "23:59",
                    "active": True,
                    "max_light": 75,
                    "fade_in_seconds": 30,
                    "fade_out_seconds": 30,
                    "crepuscular": False,
                }
            )
        )
        backend = _fade_backend()
        controller = LightController(
            config_file=str(config_file),
            gpio_pin=17,
            socket_path=None,
            backend=backend,
        )
        controller._current_pct = 0
        target, fade = controller._compute_target()
        assert target == 75
        assert fade == 0.0  # crepuscular off ignores fade_in/out

    def test_force_overrides_schedule(self, tmp_path):
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(
            json.dumps(
                {
                    "lights_on": "07:00",
                    "lights_off": "19:00",
                    "active": True,
                    "max_light": 80,
                    "crepuscular": True,
                }
            )
        )
        backend = _fade_backend()
        controller = LightController(
            config_file=str(config_file),
            gpio_pin=17,
            socket_path=None,
            backend=backend,
        )
        controller._force_pct = 30
        target, fade = controller._compute_target()
        assert target == 30
        assert fade == 0.0  # forced overrides bypass fades


class TestForceOverride:
    """Force-override state machine: True/False/None/int."""

    def test_force_true_drives_to_max_light(self, tmp_path):
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(
            json.dumps(
                {
                    "lights_on": "07:00",
                    "lights_off": "19:00",
                    "active": True,
                    "max_light": 60,
                }
            )
        )
        backend = _fade_backend()
        controller = LightController(
            config_file=str(config_file),
            gpio_pin=17,
            socket_path=None,
            backend=backend,
        )
        controller.set_force(True)
        assert controller._force_pct == 60
        backend.set_pct.assert_called_with(60)

    def test_force_false_drives_to_zero(self):
        backend = _fade_backend()
        controller = LightController(gpio_pin=17, socket_path=None, backend=backend)
        controller.set_force(False)
        assert controller._force_pct == 0
        backend.set_pct.assert_called_with(0)

    def test_force_pct_explicit(self):
        backend = _fade_backend()
        controller = LightController(gpio_pin=17, socket_path=None, backend=backend)
        controller.set_force(35)
        assert controller._force_pct == 35
        backend.set_pct.assert_called_with(35)

    def test_force_release_clears_without_writing_backend(self):
        backend = _fade_backend()
        controller = LightController(gpio_pin=17, socket_path=None, backend=backend)
        controller.set_force(50)
        backend.reset_mock()
        controller.set_force(None)
        assert controller._force_pct is None
        backend.set_pct.assert_not_called()


class TestHandleCommand:
    """Wire protocol: FORCE ON/OFF/PCT/RELEASE/STATUS."""

    def _controller(self):
        return LightController(gpio_pin=17, socket_path=None, backend=_fade_backend())

    def test_force_on(self):
        controller = self._controller()
        assert controller._handle_command("FORCE ON") == "OK"
        assert controller._force_pct == DEFAULT_MAX_LIGHT

    def test_force_off(self):
        controller = self._controller()
        assert controller._handle_command("force off") == "OK"
        assert controller._force_pct == 0

    def test_force_pct(self):
        controller = self._controller()
        assert controller._handle_command("force pct 42") == "OK"
        assert controller._force_pct == 42

    def test_force_pct_invalid_value(self):
        controller = self._controller()
        response = controller._handle_command("FORCE PCT banana")
        assert response.startswith("ERR")

    def test_release(self):
        controller = self._controller()
        controller._force_pct = 50
        assert controller._handle_command("release") == "OK"
        assert controller._force_pct is None

    def test_status_json_includes_phase3_fields(self):
        controller = self._controller()
        controller._current_pct = 25
        controller._force_pct = 25
        payload = json.loads(controller._handle_command("STATUS"))
        assert payload["led"] == 25
        assert payload["mode"] == "forced"
        assert payload["force"] == 25
        assert "fade_in_seconds" in payload
        assert "fade_out_seconds" in payload
        assert "max_light" in payload
        assert payload["backend"]  # backend name string

    def test_unknown_command_returns_error(self):
        controller = self._controller()
        response = controller._handle_command("BLINK")
        assert response.startswith("ERR")


class TestSocketRoundTrip:
    """End-to-end tests against a real listener thread on a tmp socket."""

    @pytest.fixture
    def running_controller(self, tmp_path):
        socket_path = str(tmp_path / "light_daemon.sock")
        backend = _fade_backend()
        controller = LightController(
            gpio_pin=17, socket_path=socket_path, backend=backend
        )
        controller._start_socket_listener()
        time.sleep(0.05)
        try:
            yield controller, socket_path
        finally:
            controller._running = False
            controller._stop_socket_listener()

    def test_force_on_round_trip(self, running_controller):
        controller, socket_path = running_controller
        client = LightDaemonClient(socket_path=socket_path)
        client.force_on()
        assert controller._force_pct == DEFAULT_MAX_LIGHT

    def test_force_pct_round_trip(self, running_controller):
        controller, socket_path = running_controller
        client = LightDaemonClient(socket_path=socket_path)
        client.force_pct(42)
        assert controller._force_pct == 42

    def test_release_round_trip(self, running_controller):
        controller, socket_path = running_controller
        controller.set_force(True)
        client = LightDaemonClient(socket_path=socket_path)
        client.release()
        assert controller._force_pct is None

    def test_status_round_trip(self, running_controller):
        _, socket_path = running_controller
        client = LightDaemonClient(socket_path=socket_path)
        payload = client.status()
        assert "mode" in payload
        assert payload["mode"] in {"forced", "schedule"}
        assert "backend" in payload


class TestClientUnavailable:
    def test_missing_socket_raises(self, tmp_path):
        client = LightDaemonClient(socket_path=str(tmp_path / "does_not_exist.sock"))
        with pytest.raises(LightDaemonUnavailable):
            client.force_on()

    def test_status_on_missing_socket_raises(self, tmp_path):
        client = LightDaemonClient(socket_path=str(tmp_path / "does_not_exist.sock"))
        with pytest.raises(LightDaemonUnavailable):
            client.status()


class TestShutdown:
    def test_shutdown_stops_running(self):
        controller = LightController(
            gpio_pin=17, socket_path=None, backend=PinctrlBackend(17)
        )
        assert controller._running is True
        controller.shutdown(signum=15)
        assert controller._running is False


class TestSetLedBackcompat:
    """``set_led(bool)`` continues to work as a thin wrapper for old callers."""

    def test_on_uses_max_light_from_schedule(self, tmp_path):
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(
            json.dumps(
                {
                    "lights_on": "07:00",
                    "lights_off": "19:00",
                    "active": True,
                    "max_light": 65,
                }
            )
        )
        backend = _fade_backend()
        controller = LightController(
            config_file=str(config_file),
            gpio_pin=17,
            socket_path=None,
            backend=backend,
        )
        controller.set_led(True)
        backend.set_pct.assert_called_with(65)

    def test_off_drives_to_zero(self):
        backend = _fade_backend()
        controller = LightController(gpio_pin=17, socket_path=None, backend=backend)
        controller.set_led(False)
        backend.set_pct.assert_called_with(0)
