"""Tests for run selection and machine-grouped splits."""

from __future__ import annotations

import numpy as np
import pandas as pd

from dl_tracking import select_runs as S

TUBES = [[i, 40, 100 + 64 * i, 560, 60] for i in range(1, 21)]
WELLS = [[i, 40, 100, 170, 165] for i in range(1, 25)]


def census_row(mid: str, name: str, dt: str = "2021-01-01_00-00-00", **kw) -> dict:
    """One usable census row, overridable field by field."""
    row = {
        "path": f"/r/{mid}/{name}/{dt}/x.db",
        "machine_id": mid,
        "machine_name": name,
        "run_dt": dt,
        "error": None,
        "monotonic": 1.0,
        "n_snap": 900,
        "roi_map": TUBES,
        "snap_shape": [960, 1280],
        "tracker": "AdaptiveBGModel",
    }
    return {**row, **kw}


def test_groups_join_shared_ids_and_names() -> None:
    """A cloned id joins its devices; a renamed device joins its ids."""
    ids = pd.Series(["clone", "clone", "a", "a2", "b"])
    names = pd.Series(["E_033", "E_034", "E_050", "E_050", "E_060"])
    g = S.split_groups(ids, names)
    assert g[0] == g[1]  # same cloned id
    assert g[2] == g[3]  # same name, new id
    assert len({g[0], g[2], g[4]}) == 3


def test_usable_filters() -> None:
    """Only clean, monotonic, tube-layout AdaptiveBGModel runs are kept."""
    df = pd.DataFrame(
        [
            census_row("a", "E1"),
            census_row("b", "E2", error="empty file"),
            census_row("c", "E3", monotonic=0.0),
            census_row("d", "E4", n_snap=10),
            census_row("e", "E5", roi_map=WELLS),
            census_row("f", "E6", snap_shape=None),
            census_row("g", "E7", roi_map=[]),
            census_row(
                "h", "E8", roi_map=np.nan, snap_shape=np.nan, error="empty file"
            ),
            census_row(
                "i", "E9", roi_map=np.array(TUBES), snap_shape=np.array([960, 1280])
            ),
        ]
    )
    assert S.usable(df).tolist() == [True] + [False] * 7 + [True]


def test_splits_never_share_a_group() -> None:
    """Every group lands in exactly one split, and video machines are test."""
    rows = [
        census_row(
            f"id{i % 40}", f"E_{i % 40:03d}", dt=f"2021-01-{1 + i // 40:02d}_00-00-00"
        )
        for i in range(400)
    ]
    rows.append(census_row("v", "ETHOSCOPE_044"))
    df = S.select(pd.DataFrame(rows), per_group_year=100)
    assert df.groupby("group").split.nunique().max() == 1
    assert df[df.machine_name == "ETHOSCOPE_044"].split.item() == "test"
    shares = df.split.value_counts(normalize=True)
    assert 0.05 < shares["test"] <= 0.2 and 0.05 < shares["val"] <= 0.15


def test_cap_per_group_year() -> None:
    """At most ``per_group_year`` runs per (group, year) survive."""
    rows = [census_row("a", "E1", dt=f"2021-01-{d:02d}_00-00-00") for d in range(1, 11)]
    rows += [census_row("a", "E1", dt=f"2022-01-{d:02d}_00-00-00") for d in range(1, 3)]
    df = S.select(pd.DataFrame(rows), per_group_year=3)
    assert df.year.value_counts().to_dict() == {2021: 3, 2022: 2}
