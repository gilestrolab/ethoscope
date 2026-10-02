"""Tests for flagging runs recorded on picamera2 before the NoIR tuning fix."""

from __future__ import annotations

import numpy as np
import pandas as pd

from dl_tracking import flag_no_ir as F


def test_code_window_uses_git_ancestry() -> None:
    """Commits before, inside and after the window, and non-commits."""
    assert F.code_window("e2e74f64") == "before"  # 2023, legacy picamera
    assert F.code_window(F.WINDOW_START) == "window"
    assert F.code_window("217084d9") == "window"  # tuning "always on", still ignored
    assert F.code_window(F.WINDOW_END) == "fixed"
    assert F.code_window(None) == "unknown"
    assert F.code_window("0" * 40) == "unknown"
    assert F.code_window("abc; ls") == "unknown"  # never reaches git


def test_camera_stack_from_kernel() -> None:
    """Arch Linux ARM kept legacy picamera; Raspberry Pi OS has only picamera2."""
    assert F.camera_stack("6.1.14-1-rpi-ARCH") == "picamera"
    assert F.camera_stack("6.12.75+rpt-rpi-v8") == "picamera2"
    assert F.camera_stack("6.6.51-v8") == "picamera2"
    assert F.camera_stack("4.19.0-generic") == "unknown"
    assert F.camera_stack(None) == "unknown"


def test_night_day_ratio() -> None:
    """Darkest over brightest sample; NaN without samples."""
    census = pd.DataFrame({"snap_lum": [[10.0, 40.0, 20.0], np.nan, np.array([5.0])]})
    assert F.night_day_ratio(census).tolist()[0] == 0.25
    assert np.isnan(F.night_day_ratio(census).iloc[1])


def test_flag_needs_window_code_and_picamera2() -> None:
    """Only window-code runs not on legacy picamera are flagged, with a certainty."""
    kernels = {
        "a": "6.12.75+rpt-rpi-v8",
        "b": "6.1.14-1-rpi-ARCH",
        "c": None,
        "d": "6.12.75+rpt-rpi-v8",
        "e": "6.12.75+rpt-rpi-v8",
    }
    census = pd.DataFrame(
        {
            "error": [None, None, None, None, "empty file"],
            "version": ["217084d9", "217084d9", "217084d9", "e2e74f64", "217084d9"],
            "path": list("abcde"),
            "machine_name": list("ABCDE"),
            "machine_id": list("abcde"),
            "run_dt": ["2025-07-22_13-03-43"] * 5,
            "user": ["u"] * 5,
            "n_snap": [500] * 5,
            "snap_lum": [[120.0, 36.0]] * 5,
        }
    )
    out = F.flag(census, kernel_of=kernels.get)
    assert dict(zip(out.path, out.certainty, strict=True)) == {
        "a": "picamera2",
        "c": "stack unknown",
    }
    assert out.night_day_ratio.iloc[0] == 0.3
