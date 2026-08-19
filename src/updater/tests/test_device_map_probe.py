"""
Tests for the device discovery probe in helpers.generate_new_device_map.

A device whose services are restarting -- which is precisely what an update does to it
-- cannot answer the probe on port 8888. The old code dropped such a device from the map
entirely (`if id is None: continue`), so it disappeared from the update table with no row
and no log line: the devices most in need of attention were the ones being erased.

These tests pin the two behaviours that replaced it: one retry before giving up, and a
visible "Unreachable" row for whatever is still silent afterwards.
"""

import os
import sys
from unittest import mock

import pytest

# The updater package is a standalone script directory (no installable package), so make it
# importable directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import helpers  # noqa: E402

KNOWN = [
    ("id-aaa", "ETHOSCOPE_001", "http://192.168.1.1"),
    ("id-bbb", "ETHOSCOPE_002", "http://192.168.1.2"),
]


@pytest.fixture(autouse=True)
def no_sleep():
    """The retry pause is real seconds; tests should not pay for it."""
    with mock.patch.object(helpers.time, "sleep"):
        yield


@pytest.fixture(autouse=True)
def known_devices():
    with mock.patch.object(helpers, "receive_known_devices", return_value=KNOWN):
        yield


@pytest.fixture(autouse=True)
def no_enrichment():
    """Isolate discovery from the follow-up rounds that query each device."""
    with mock.patch.object(helpers, "_enrich_device_map"):
        yield


def _answers(mapping):
    """Build a scan_one_device stub from {url: id or None}."""

    def scan(url, **kwargs):
        return mapping.get(url), url

    return scan


def test_all_devices_answering(known_devices, no_enrichment, no_sleep):
    with mock.patch.object(
        helpers,
        "scan_one_device",
        side_effect=_answers(
            {"http://192.168.1.1": "id-aaa", "http://192.168.1.2": "id-bbb"}
        ),
    ):
        devices_map = helpers.generate_new_device_map()

    assert set(devices_map) == {"id-aaa", "id-bbb"}
    assert all(d["status"] != "Unreachable" for d in devices_map.values())


def test_silent_device_is_listed_not_dropped(known_devices, no_enrichment, no_sleep):
    """The regression: a device that never answers must still get a row."""
    with mock.patch.object(
        helpers,
        "scan_one_device",
        side_effect=_answers({"http://192.168.1.1": "id-aaa"}),
    ):
        devices_map = helpers.generate_new_device_map()

    assert set(devices_map) == {"id-aaa", "id-bbb"}, "the silent device was dropped"
    assert devices_map["id-bbb"]["status"] == "Unreachable"
    # Keyed and named from the node's own knowledge, so the row is identifiable.
    assert devices_map["id-bbb"]["name"] == "ETHOSCOPE_002"
    assert devices_map["id-bbb"]["ip"] == "http://192.168.1.2"


def test_device_answering_only_on_retry_is_not_marked_unreachable(
    known_devices, no_enrichment, no_sleep
):
    """A device mid-restart misses the first probe and answers the second."""
    calls = {"http://192.168.1.2": 0}

    def scan(url, **kwargs):
        if url == "http://192.168.1.1":
            return "id-aaa", url
        calls[url] += 1
        return ("id-bbb" if calls[url] > 1 else None), url

    with mock.patch.object(helpers, "scan_one_device", side_effect=scan):
        devices_map = helpers.generate_new_device_map()

    assert devices_map["id-bbb"]["status"] != "Unreachable"
    assert calls["http://192.168.1.2"] == 2


def test_healthy_scan_does_not_retry(known_devices, no_enrichment, no_sleep):
    """The retry pause must not be paid when nothing was silent."""
    with mock.patch.object(
        helpers,
        "scan_one_device",
        side_effect=_answers(
            {"http://192.168.1.1": "id-aaa", "http://192.168.1.2": "id-bbb"}
        ),
    ) as scan:
        helpers.generate_new_device_map()

    assert scan.call_count == len(KNOWN)
    helpers.time.sleep.assert_not_called()


def test_probe_exception_counts_as_silent(known_devices, no_enrichment, no_sleep):
    """A raising probe must not lose the device either."""

    def scan(url, **kwargs):
        if url == "http://192.168.1.2":
            raise OSError("network down")
        return "id-aaa", url

    with mock.patch.object(helpers, "scan_one_device", side_effect=scan):
        devices_map = helpers.generate_new_device_map()

    assert devices_map["id-bbb"]["status"] == "Unreachable"


def test_unreachable_devices_are_not_queried_further(
    known_devices, no_enrichment, no_sleep
):
    """Querying a device that never answered would only add timeouts to the scan."""
    with mock.patch.object(
        helpers,
        "scan_one_device",
        side_effect=_answers({"http://192.168.1.1": "id-aaa"}),
    ):
        helpers.generate_new_device_map()

    for call in helpers._enrich_device_map.call_args_list:
        assert call.args[1] == ["id-aaa"]
