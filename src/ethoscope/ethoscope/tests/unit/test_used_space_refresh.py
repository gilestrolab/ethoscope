"""Unit tests for the used-space figure a device reports to the node.

Regression coverage for a reading that never moved. ``used_space`` was taken once
in ``ControlThread.__init__`` and never again, so the hard-drive icon in the web
interface showed whatever was true when the listener last started or the current
run began: a device whose card had been emptied an hour earlier still reported
93% full, and one that was recording — the activity that fills a card fastest —
reported nothing at all, because the video control thread never set the field.
"""

import time
from unittest import mock

import pytest

from ethoscope.control.record import ControlThreadVideoRecording
from ethoscope.control.tracking import ControlThread
from ethoscope.utils import pi


class TestUsedSpacePercent:
    """The reader itself: a df figure, or None, but never an exception."""

    def test_reads_the_percentage_without_its_sign(self):
        with mock.patch.object(pi, "get_partition_info", return_value={"Use%": "67%"}):
            assert pi.used_space_percent("/ethoscope_data") == "67"

    def test_a_df_that_cannot_be_read_gives_none(self):
        # Reason: get_partition_info returns None on failure, and the callers used
        # to subscript it immediately — a TypeError at construction time.
        with mock.patch.object(pi, "get_partition_info", return_value=None):
            assert pi.used_space_percent("/ethoscope_data") is None

    def test_an_unexpected_shape_gives_none(self):
        for bad in ({}, {"Use": "67%"}, "not a dict"):
            with mock.patch.object(pi, "get_partition_info", return_value=bad):
                assert pi.used_space_percent("/ethoscope_data") is None


def _thread_with(cls, folder_attr, used_now, checked_at):
    """
    A control thread with only the state the refresh touches.

    Built with __new__ so the test does not need a camera, a database or a
    writable /ethoscope_data.
    """
    thread = cls.__new__(cls)
    setattr(thread, folder_attr, "/ethoscope_data")
    thread._used_space_checked_at = checked_at
    thread._info = {"used_space": used_now}
    return thread


@pytest.mark.parametrize(
    "cls,folder_attr",
    [
        (ControlThread, "_ethoscope_dir"),
        (ControlThreadVideoRecording, "_video_root_dir"),
    ],
)
class TestRefreshUsedSpace:
    """Both control threads keep the figure fresh, and both throttle df."""

    def test_a_stale_reading_is_replaced(self, cls, folder_attr):
        thread = _thread_with(cls, folder_attr, "93", time.time() - 3600)

        with mock.patch.object(pi, "used_space_percent", return_value="67") as reader:
            thread._refresh_used_space()

        assert thread._info["used_space"] == "67"
        assert reader.called

    def test_a_fresh_reading_is_left_alone(self, cls, folder_attr):
        thread = _thread_with(cls, folder_attr, "67", time.time())

        with mock.patch.object(pi, "used_space_percent") as reader:
            thread._refresh_used_space()

        # df must stay off the poll path: info is read every few seconds.
        assert not reader.called
        assert thread._info["used_space"] == "67"

    def test_the_ttl_bounds_how_stale_it_can_get(self, cls, folder_attr):
        thread = _thread_with(
            cls, folder_attr, "93", time.time() - pi.USED_SPACE_TTL_S - 1
        )

        with mock.patch.object(pi, "used_space_percent", return_value="10") as reader:
            thread._refresh_used_space()

        assert reader.called
        assert thread._info["used_space"] == "10"

    def test_an_unreadable_df_keeps_the_last_known_figure(self, cls, folder_attr):
        thread = _thread_with(cls, folder_attr, "67", time.time() - 3600)

        with mock.patch.object(pi, "used_space_percent", return_value=None):
            thread._refresh_used_space()

        assert thread._info["used_space"] == "67"
