"""Unit tests for rootfs-expansion logic in ethoscope.utils.pi.

Regression coverage for the bug where expansion was gated on *free space inside
the filesystem* (`available > 1GB -> skip`) instead of *unallocated space on the
disk*. That heuristic silently skipped expansion on any medium larger than the
image partition — a big SD card or a USB SSD alike.
"""

from unittest import mock

from ethoscope.utils import pi


def _fake_popen(output="", close_ret=None):
    """Return a mock replacing os.popen (used as a context manager)."""
    handle = mock.MagicMock()
    handle.__enter__.return_value = handle
    handle.__exit__.return_value = False
    handle.read.return_value = output
    handle.close.return_value = close_ret  # None / 0 == success for os.popen
    return mock.Mock(return_value=handle)


class TestUnallocatedBytesAfterRoot:
    """Directly exercise the disk-geometry helper against a fake sysfs."""

    def _run(self, sysfs, listdir, findmnt="/dev/sda2", pkname="sda"):
        def fake_run(cmd, *a, **k):
            r = mock.Mock()
            r.stdout = (findmnt if cmd[0] == "findmnt" else pkname) + "\n"
            return r

        def fake_open(path, *a, **k):
            if path in sysfs:
                return mock.mock_open(read_data=str(sysfs[path]))()
            raise FileNotFoundError(path)

        with (
            mock.patch.object(pi.subprocess, "run", side_effect=fake_run),
            mock.patch.object(pi.os, "listdir", return_value=listdir),
            mock.patch.object(pi.os.path, "exists", side_effect=lambda p: p in sysfs),
            mock.patch("builtins.open", fake_open),
        ):
            return pi._unallocated_bytes_after_root()

    def test_reports_unallocated_tail_when_root_is_last(self):
        # 120 GB disk (234455040 sectors); root p2 ends at sector 61440000.
        sysfs = {
            "/sys/class/block/sda/size": 234455040,
            "/sys/class/block/sda/sda1/start": 16384,
            "/sys/class/block/sda/sda1/size": 1048576,
            "/sys/class/block/sda/sda2/start": 1064960,
            "/sys/class/block/sda/sda2/size": 60375040,
        }
        got = self._run(sysfs, listdir=["sda1", "sda2"])
        assert got == (234455040 - 61440000) * 512
        assert got > 80 * 1024**3  # ~82 GiB free -> expansion warranted

    def test_returns_zero_when_partition_fills_disk(self):
        # root p2 ends exactly at the end of the disk -> nothing to grow into.
        sysfs = {
            "/sys/class/block/sda/size": 61440000,
            "/sys/class/block/sda/sda2/start": 1064960,
            "/sys/class/block/sda/sda2/size": 60375040,
        }
        got = self._run(sysfs, listdir=["sda2"])
        assert got == 0

    def test_returns_zero_when_root_is_not_last_partition(self):
        # A p3 lies beyond root p2 -> growing p2 would be unsafe.
        sysfs = {
            "/sys/class/block/sda/size": 234455040,
            "/sys/class/block/sda/sda2/start": 1064960,
            "/sys/class/block/sda/sda2/size": 60375040,
            "/sys/class/block/sda/sda3/start": 61440000,
            "/sys/class/block/sda/sda3/size": 100000000,
        }
        got = self._run(sysfs, listdir=["sda2", "sda3"])
        assert got == 0

    def test_returns_zero_when_root_source_unknown(self):
        got = self._run({}, listdir=[], findmnt="")
        assert got == 0


class TestExpandRootfsDecision:
    """The public entry point should key off unallocated space, not free space."""

    def _on_pi(self, unallocated):
        """Context managers making expand_rootfs believe it is on a Pi with
        raspi-config present, and returning `unallocated` from the helper."""
        return (
            mock.patch.object(pi, "isMachinePI", return_value=True),
            mock.patch.object(
                pi.os.path, "isfile", side_effect=lambda p: p == "/usr/bin/raspi-config"
            ),
            mock.patch.object(pi.os, "access", return_value=True),
            mock.patch.object(
                pi, "_unallocated_bytes_after_root", return_value=unallocated
            ),
        )

    def test_skips_when_partition_already_fills_disk(self):
        p1, p2, p3, p4 = self._on_pi(unallocated=0)
        with p1, p2, p3, p4, mock.patch.object(pi.os, "popen") as popen:
            res = pi.expand_rootfs()
        assert res["success"] is True
        assert res["expanded"] is False
        assert "not needed" in res["message"]
        popen.assert_not_called()  # raspi-config must NOT run

    def test_skips_for_small_unallocated_tail(self):
        # Under the 1 GiB threshold -> not worth a resize.
        p1, p2, p3, p4 = self._on_pi(unallocated=500 * 1024**2)
        with p1, p2, p3, p4, mock.patch.object(pi.os, "popen") as popen:
            res = pi.expand_rootfs()
        assert res["expanded"] is False
        popen.assert_not_called()

    def test_expands_when_unallocated_space_available(self):
        p1, p2, p3, p4 = self._on_pi(unallocated=88 * 1024**3)
        with (
            p1,
            p2,
            p3,
            p4,
            mock.patch.object(
                pi.os, "popen", _fake_popen(output="done", close_ret=None)
            ),
        ):
            res = pi.expand_rootfs()
        assert res["success"] is True
        assert res["expanded"] is True

    def test_reports_raspi_config_failure(self):
        p1, p2, p3, p4 = self._on_pi(unallocated=88 * 1024**3)
        with (
            p1,
            p2,
            p3,
            p4,
            mock.patch.object(
                pi.os, "popen", _fake_popen(output="boom", close_ret=256)
            ),
        ):
            res = pi.expand_rootfs()
        assert res["expanded"] is False
        assert "failed" in res["message"].lower()

    def test_not_applicable_off_pi(self):
        with mock.patch.object(pi, "isMachinePI", return_value=False):
            res = pi.expand_rootfs()
        assert res["success"] is True
        assert res["expanded"] is False
