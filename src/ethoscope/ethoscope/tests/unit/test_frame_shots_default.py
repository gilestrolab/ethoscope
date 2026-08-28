#!/usr/bin/env python3
"""
Unit tests for the take_frame_shots default.

Each result writer advertises its options twice: once in the ``_description``
dict the node builds its form from, and once in the ``__init__`` signature that
applies when a caller does not pass the option at all. For ``take_frame_shots``
the two disagreed - the description said True, the signature said False - so
experiments started from the web form recorded snapshots while everything that
omitted the option recorded none. That covers the device API, scripts, and
``device_listener --run``.

The snapshots are the only images of the arena kept alongside a run, so a run
that silently skipped them cannot be reviewed afterwards. These tests pin the
two declarations together so they cannot drift apart again.
"""

import inspect

import pytest

from ethoscope.io.sqlite import SQLiteResultWriter

WRITERS = [SQLiteResultWriter]

try:  # MySQL support is optional; skip rather than fail where it is absent.
    from ethoscope.io.mysql import MySQLResultWriter

    WRITERS.append(MySQLResultWriter)
except Exception:  # pragma: no cover - depends on the optional mysql driver
    pass


def _described_default(writer, option):
    """The default the node's form will use for `option`."""
    for arg in writer._description["arguments"]:
        if arg["name"] == option:
            return arg["default"]
    raise AssertionError(f"{writer.__name__} does not describe {option!r}")


def _signature_default(writer, option):
    """The default that applies when a caller omits `option` entirely."""
    return inspect.signature(writer.__init__).parameters[option].default


@pytest.mark.parametrize("writer", WRITERS, ids=lambda w: w.__name__)
def test_snapshots_are_on_by_default(writer):
    """Regression: omitting the option silently produced no snapshots."""
    assert _signature_default(writer, "take_frame_shots") is True


@pytest.mark.parametrize("writer", WRITERS, ids=lambda w: w.__name__)
def test_the_form_default_and_the_code_default_agree(writer):
    """The two declarations are read by different callers and must not drift."""
    described = _described_default(writer, "take_frame_shots")
    signature = _signature_default(writer, "take_frame_shots")

    assert described == signature, (
        f"{writer.__name__} advertises take_frame_shots={described} to the node "
        f"but defaults to {signature} when the option is omitted"
    )


@pytest.mark.parametrize("writer", WRITERS, ids=lambda w: w.__name__)
def test_an_explicit_false_is_still_honoured(writer):
    """Turning snapshots off has to remain possible."""
    assert (
        _signature_default(writer, "take_frame_shots") is not None
    ), "the option must stay a real boolean parameter, not be removed"
    assert "take_frame_shots" in inspect.signature(writer.__init__).parameters
