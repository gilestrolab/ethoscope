#!/usr/bin/env python3
"""
Unit tests for the LIGHT_EVENTS log.

The light daemon is a separate process with its own lifetime, so the tracker
cannot be told when the panel changes - it has to ask, and it has to cope with
the daemon being absent, stopped or mid-fade. What the log has to guarantee:

* the state at the start of a run is always recorded, including "off";
* only genuine changes cost a row;
* an unreachable daemon is recorded as nothing at all, never as darkness -
  confusing the two is the single mistake this table exists to prevent.
"""

from unittest.mock import Mock

import pytest

from ethoscope.core.monitor import Monitor


def _monitor():
    """A Monitor with only the light state initialised.

    Built without __init__ on purpose: the constructor wants cameras and ROIs,
    and none of that bears on the light log.
    """
    monitor = Monitor.__new__(Monitor)
    monitor._diagnostics = {}
    monitor._last_light_pct = Monitor._LIGHT_UNSET
    monitor._light_client = None
    return monitor


def _writer():
    """A result writer that records the light events it was given."""
    writer = Mock()
    writer.events = []
    writer.write_light_event = Mock(
        side_effect=lambda t, pct, mode=None: writer.events.append((t, pct, mode))
    )
    return writer


class TestSampleLight:
    """Asking the daemon what the panel is doing."""

    def test_reads_level_and_mode(self, monkeypatch):
        """Expected use."""
        monitor = _monitor()
        client = Mock()
        client.status.return_value = {"led": 100, "mode": "schedule"}
        monitor._light_client = client

        assert monitor._sample_light() == (100.0, "schedule")

    def test_forced_mode_is_reported(self):
        """A light forced mid-run has to be distinguishable from the schedule."""
        monitor = _monitor()
        client = Mock()
        client.status.return_value = {"led": 40, "mode": "forced"}
        monitor._light_client = client

        assert monitor._sample_light() == (40.0, "forced")

    def test_unavailable_daemon_yields_nothing(self):
        """Edge case: no light module fitted, which is most ethoscopes."""
        from ethoscope.hardware.interfaces.light_daemon import LightDaemonUnavailable

        monitor = _monitor()
        client = Mock()
        client.status.side_effect = LightDaemonUnavailable("no socket")
        monitor._light_client = client

        assert monitor._sample_light() == (None, None)

    def test_malformed_status_yields_nothing(self):
        """Failure case: a daemon answering with something unexpected."""
        monitor = _monitor()
        client = Mock()
        client.status.return_value = "not a dict"
        monitor._light_client = client

        assert monitor._sample_light() == (None, None)

    def test_missing_level_yields_no_level(self):
        """Edge case: a status payload without the level field."""
        monitor = _monitor()
        client = Mock()
        client.status.return_value = {"mode": "schedule"}
        monitor._light_client = client

        assert monitor._sample_light() == (None, "schedule")

    def test_unexpected_error_does_not_propagate(self):
        """Failure case: nothing here may interrupt an experiment."""
        monitor = _monitor()
        client = Mock()
        client.status.side_effect = RuntimeError("boom")
        monitor._light_client = client

        assert monitor._sample_light() == (None, None)


class TestRecordLightChange:
    """Turning sampled levels into an edge-triggered log."""

    def test_first_observation_is_always_written(self):
        """Expected use: the state at the start of a run must be known."""
        monitor = _monitor()
        writer = _writer()
        monitor._diagnostics = {"light_pct": 100.0, "light_mode": "schedule"}

        monitor._record_light_change(1000, writer)

        assert writer.events == [(1000, 100.0, "schedule")]

    def test_first_observation_of_darkness_is_written(self):
        """A run beginning in the dark is information, not an absent event."""
        monitor = _monitor()
        writer = _writer()
        monitor._diagnostics = {"light_pct": 0.0, "light_mode": "schedule"}

        monitor._record_light_change(1000, writer)

        assert writer.events == [(1000, 0.0, "schedule")]

    def test_unchanged_level_costs_nothing(self):
        """Edge-triggered: a 12:12 cycle is a handful of rows, not 1440."""
        monitor = _monitor()
        writer = _writer()
        monitor._diagnostics = {"light_pct": 100.0, "light_mode": "schedule"}

        for t in (1000, 2000, 3000, 4000):
            monitor._record_light_change(t, writer)

        assert writer.events == [(1000, 100.0, "schedule")]

    def test_transition_is_written(self):
        """The whole point: lights-off produces a row."""
        monitor = _monitor()
        writer = _writer()

        monitor._diagnostics = {"light_pct": 100.0, "light_mode": "schedule"}
        monitor._record_light_change(1000, writer)
        monitor._diagnostics = {"light_pct": 0.0, "light_mode": "schedule"}
        monitor._record_light_change(2000, writer)

        assert writer.events == [
            (1000, 100.0, "schedule"),
            (2000, 0.0, "schedule"),
        ]

    def test_a_fade_is_recorded_as_its_steps(self):
        """Crepuscular ramps are real intermediate levels, not one edge."""
        monitor = _monitor()
        writer = _writer()

        for t, pct in enumerate([0.0, 25.0, 50.0, 75.0, 100.0, 100.0]):
            monitor._diagnostics = {"light_pct": pct, "light_mode": "schedule"}
            monitor._record_light_change(t, writer)

        assert [pct for _, pct, _ in writer.events] == [0.0, 25.0, 50.0, 75.0, 100.0]

    def test_returning_to_a_previous_level_is_a_change(self):
        """Only the *last* level is the comparison, not any level ever seen."""
        monitor = _monitor()
        writer = _writer()

        for t, pct in enumerate([100.0, 0.0, 100.0]):
            monitor._diagnostics = {"light_pct": pct, "light_mode": "schedule"}
            monitor._record_light_change(t, writer)

        assert len(writer.events) == 3

    def test_unreachable_daemon_is_not_an_event(self):
        """The mistake this table exists to prevent: null read as darkness."""
        monitor = _monitor()
        writer = _writer()

        monitor._diagnostics = {"light_pct": 100.0, "light_mode": "schedule"}
        monitor._record_light_change(1000, writer)
        monitor._diagnostics = {"light_pct": None, "light_mode": None}
        monitor._record_light_change(2000, writer)

        assert writer.events == [(1000, 100.0, "schedule")]

    def test_daemon_returning_keeps_the_previous_level(self):
        """A gap in reachability must not fabricate a transition either side."""
        monitor = _monitor()
        writer = _writer()

        for t, pct in enumerate([100.0, None, 100.0]):
            monitor._diagnostics = {"light_pct": pct, "light_mode": "schedule"}
            monitor._record_light_change(t, writer)

        assert len(writer.events) == 1

    def test_no_writer_is_harmless(self):
        """Edge case: monitors run without a result writer."""
        monitor = _monitor()
        monitor._diagnostics = {"light_pct": 100.0}

        monitor._record_light_change(1000, None)  # must not raise

    def test_writer_without_the_method_is_harmless(self):
        """Failure case: writers predating this table must still work."""
        monitor = _monitor()
        writer = Mock(spec=[])  # no write_light_event
        monitor._diagnostics = {"light_pct": 100.0}

        monitor._record_light_change(1000, writer)  # must not raise


class TestWriteLightEvent:
    """The writer side."""

    def _writer_stub(self):
        """A result writer with just enough of the base class to insert a row."""
        from ethoscope.io.base import BaseResultWriter

        writer = BaseResultWriter.__new__(BaseResultWriter)
        writer._database_type = "SQLite3"
        writer.commands = []
        writer._write_async_command = lambda command, args=None: writer.commands.append(
            (command, args)
        )
        return writer

    def test_insert_targets_the_light_table(self):
        """Expected use."""
        writer = self._writer_stub()
        writer.write_light_event(1234, 100.0, "schedule")

        command, args = writer.commands[0]
        assert "INSERT INTO LIGHT_EVENTS" in command
        assert args == (1234, 100.0, "schedule")

    def test_missing_mode_is_null(self):
        """Edge case: level known, mode not."""
        writer = self._writer_stub()
        writer.write_light_event(1234, 0.0)

        assert writer.commands[0][1] == (1234, 0.0, None)

    def test_never_raises(self):
        """Failure case: the light log must not interrupt an experiment."""
        writer = self._writer_stub()

        def explode(command, args=None):
            raise RuntimeError("db gone")

        writer._write_async_command = explode
        writer.write_light_event(1234, 100.0, "schedule")  # must not raise


class TestSchema:
    """The table has to exist, and the backup has to know how to sync it."""

    def test_fields_match_the_insert_list(self):
        """A mismatch here would fail only at runtime, once per event."""
        from ethoscope.io.base import BaseResultWriter

        declared = [
            f.strip().split()[0]
            for f in BaseResultWriter.LIGHT_EVENTS_FIELDS.split(",")
        ]
        assert declared == list(BaseResultWriter.LIGHT_EVENTS_INSERT_FIELDS)
