"""Tests for the dark-night flagging."""

from __future__ import annotations

import numpy as np
import pandas as pd

from dl_tracking import flag_no_ir as F


def test_commit_date_from_git() -> None:
    """Known commits get their date; anything else gets None without calling git."""
    assert F.commit_date("e2e74f64") == "2023-06-30"
    assert F.commit_date("0" * 40) is None
    assert F.commit_date(None) is None
    assert F.commit_date("abc; ls") is None


def test_luminance_handles_missing_samples() -> None:
    """Runs without samples get NaN; others their min / median / max and ratio."""
    census = pd.DataFrame({"snap_lum": [[10.0, 40.0, 20.0], np.nan, np.array([5.0])]})
    lum = F.luminance(census)
    assert lum.iloc[0].tolist() == [10, 20, 40, 0.25]
    assert lum.iloc[1].isna().all()
    assert lum.iloc[2].tolist() == [5, 5, 5, 1]


def test_flag_keeps_dark_nights_only() -> None:
    """Dark nights are flagged; uniformly dim runs and failed DBs are not."""
    census = pd.DataFrame(
        {
            "error": [None, None, None, "empty file"],
            "snap_lum": [
                [127.5, 33.0, 115.7, 37.2],
                [40.0, 38.0, 41.0, 39.0],
                [110.0, 95.0, 104.0, 99.0],
                np.nan,
            ],
            "machine_name": ["E285", "E1", "E2", "E3"],
            "machine_id": list("abcd"),
            "run_dt": ["2025-07-22_13-03-43"] * 4,
            "user": ["u"] * 4,
            "version": ["e2e74f64", None, None, None],
            "n_snap": [501] * 4,
            "path": list("wxyz"),
        }
    )
    out = F.flag(census)
    assert out.machine_name.tolist() == ["E285"]
    assert out.commit_date.item() == "2023-06-30"
