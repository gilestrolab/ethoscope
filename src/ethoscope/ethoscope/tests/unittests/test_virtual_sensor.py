"""
Unit tests for the standalone virtual sensor script.

The virtual sensor lives in ``accessories/hardware/etho_sensor/virtual_sensor.py``
(it is a standalone script, not part of either installable package), so it is
loaded here by file path. These tests cover the identity-stability and
single-snapshot reading behaviour, not the HTTP/zeroconf server itself.
"""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

# Resolve the script relative to the repository root (5 parents up from this file:
# unittests -> tests -> ethoscope -> ethoscope[src] -> src -> repo root).
_SCRIPT = (
    Path(__file__).resolve().parents[5]
    / "accessories"
    / "hardware"
    / "etho_sensor"
    / "virtual_sensor.py"
)


def _load_module():
    """Import the virtual_sensor script as a module by file path."""
    if not _SCRIPT.is_file():
        pytest.skip(f"virtual_sensor script not found at {_SCRIPT}")
    spec = importlib.util.spec_from_file_location("virtual_sensor", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as e:
        pytest.skip(f"virtual_sensor dependencies unavailable: {e}")
    return module


@pytest.fixture(scope="module")
def vs():
    """Loaded virtual_sensor module."""
    return _load_module()


class TestStableMacAddress:
    """The sensor /id must be stable across restarts (same hostname)."""

    def test_deterministic_for_same_hostname(self, vs):
        with patch("socket.gethostname", return_value="etho-test-host"):
            first = vs._stable_mac_address()
            second = vs._stable_mac_address()
        assert first == second

    def test_differs_for_different_hostnames(self, vs):
        with patch("socket.gethostname", return_value="host-a"):
            a = vs._stable_mac_address()
        with patch("socket.gethostname", return_value="host-b"):
            b = vs._stable_mac_address()
        assert a != b

    def test_format_is_six_hex_octets(self, vs):
        with patch("socket.gethostname", return_value="etho-test-host"):
            mac = vs._stable_mac_address()
        octets = mac.split(":")
        assert len(octets) == 6
        for octet in octets:
            assert len(octet) == 2
            int(octet, 16)  # raises ValueError if not hex


class TestHwSensorRead:
    """hwsensor.read() returns a single consistent snapshot."""

    def test_read_returns_all_fields_without_weather(self, vs):
        # Ensure dummy-data path (no weather fetcher configured).
        with patch.object(vs, "weather_fetcher", None):
            reading = vs.hwsensor().read()
        assert set(reading) == {"temperature", "humidity", "pressure", "light"}
        for value in reading.values():
            assert isinstance(value, (int, float))

    def test_read_uses_single_weather_fetch(self, vs):
        """With a weather fetcher, read() fetches exactly once for all fields."""

        class FakeFetcher:
            def __init__(self):
                self.calls = 0

            def fetch_weather_data(self):
                self.calls += 1
                return {
                    "temperature": 21.5,
                    "humidity": 55.0,
                    "pressure": 1010.0,
                    "light": 42000,
                }

        fetcher = FakeFetcher()
        with patch.object(vs, "weather_fetcher", fetcher):
            reading = vs.hwsensor().read()

        assert fetcher.calls == 1
        assert reading == {
            "temperature": 21.5,
            "humidity": 55.0,
            "pressure": 1010.0,
            "light": 42000,
        }


class TestLightFromWeather:
    """The dawn/dusk branch must be reachable (regression for dead code).

    Under clear skies the light estimate is base(50000) * 1.0 * time_factor,
    so daylight -> 50000, dawn/dusk -> 15000, night -> 2500. The previous
    overlapping ranges made the dawn/dusk branch unreachable at hours 6 and 18.
    """

    @pytest.mark.parametrize(
        "hour,expected_light",
        [
            (12, 50000),  # daylight, time_factor 1.0
            (6, 15000),  # dawn, time_factor 0.3 (was dead code before fix)
            (18, 15000),  # dusk, time_factor 0.3 (was dead code before fix)
            (2, 2500),  # night, time_factor 0.05
        ],
    )
    def test_time_factor_branches(self, vs, hour, expected_light):
        # No API key -> __init__ stays offline (no network call). Guard against a
        # real key leaking in from the environment.
        with patch.dict("os.environ", {"OPENWEATHER_API_KEY": ""}):
            fetcher = vs.WeatherDataFetcher(location="test-location")
        weather = {"weather": [{"main": "Clear"}], "clouds": {"all": 0}}

        with patch("datetime.datetime") as mock_dt:
            mock_dt.now.return_value.hour = hour
            value = fetcher._calculate_light_from_weather(weather)

        assert value == expected_light
