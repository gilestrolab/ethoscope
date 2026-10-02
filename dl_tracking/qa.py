"""Contact sheets of labelled tube crops, for checking labels by eye.

Usage::

    python -m dl_tracking.qa --data /mnt/cache/dl_tracking/data --status gapfill \\
        --n 32 --out sheet.jpg
"""

from __future__ import annotations

import argparse
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

TILE_W = 580  # wide enough for a 20-tube ROI; wider ROIs are scaled down
TILE_H = 72


@lru_cache(maxsize=64)
def _snaps(path: Path) -> pd.DataFrame:
    """Load (and cache) one run's snapshot table, indexed by rowid."""
    return pd.read_parquet(path).set_index("snap_rowid")


def load_crop(data: Path, row: pd.Series) -> np.ndarray:
    """
    Decode the snapshot of one label row and cut out its ROI.

    Args:
        data (Path): Extraction output root.
        row (pd.Series): One label row.

    Returns:
        np.ndarray: Greyscale ROI crop at full resolution.
    """
    blob = _snaps(data / "snaps" / f"{row.run_id}.parquet").loc[row.snap_rowid, "jpeg"]
    img = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_GRAYSCALE)
    return img[row.roi_y : row.roi_y + row.roi_h, row.roi_x : row.roi_x + row.roi_w]


def tile(crop: np.ndarray, row: pd.Series) -> np.ndarray:
    """
    Render one crop with its label marked by ticks that leave the fly visible.

    Args:
        crop (np.ndarray): Greyscale ROI crop.
        row (pd.Series): Its label row.

    Returns:
        np.ndarray: A ``TILE_H x TILE_W`` BGR tile.
    """
    scale = min(1.0, TILE_W / crop.shape[1], (TILE_H - 12) / crop.shape[0])
    small = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    out = np.zeros((TILE_H, TILE_W, 3), np.uint8)
    out[12 : 12 + small.shape[0], : small.shape[1]] = small[..., None]
    if pd.notna(row.get("x")):
        cx, cy = int(row.x * scale), int(row.y * scale) + 12
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p0 = (cx + 8 * dx, cy + 8 * dy)
            p1 = (cx + 14 * dx, cy + 14 * dy)
            cv2.line(out, p0, p1, (0, 0, 255), 1)
    text = f"{row.status} {row.run_id[-19:-9]} roi{row.roi_idx}"
    if pd.notna(row.get("contrast")):
        text += f" c={row.contrast:.0f}"
    if pd.notna(row.get("gap_ms")) and row.get("gap_ms", 0) > 0:
        text += f" gap={row.gap_ms / 60000:.0f}min"
    cv2.putText(out, text, (2, 10), cv2.FONT_HERSHEY_PLAIN, 0.8, (0, 255, 255), 1)
    return out


def contact_sheet(
    data: Path, rows: pd.DataFrame, n: int, cols: int = 2, seed: int = 0
) -> np.ndarray:
    """
    Tile ``n`` random label rows into one image.

    Args:
        data (Path): Extraction output root.
        rows (pd.DataFrame): Label rows to sample from.
        n (int): Number of tiles.
        cols (int): Tiles per row.
        seed (int): Sampling seed.

    Returns:
        np.ndarray: The sheet (BGR).
    """
    pick = rows.sample(min(n, len(rows)), random_state=seed)
    tiles = [tile(load_crop(data, r), r) for _, r in pick.iterrows()]
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    grid = [np.hstack(tiles[i : i + cols]) for i in range(0, len(tiles), cols)]
    return np.vstack(grid)


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--data", type=Path, default=Path("/mnt/cache/dl_tracking/data")
    )
    parser.add_argument("--status", default=None, help="only rows with this status")
    parser.add_argument("--query", default=None, help="extra pandas query on the rows")
    parser.add_argument("--n", type=int, default=32)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = pd.concat(
        pd.read_parquet(p) for p in (args.data / "labels").glob("*.parquet")
    )
    if args.status:
        rows = rows[rows.status == args.status]
    if args.query:
        rows = rows.query(args.query)
    cv2.imwrite(str(args.out), contact_sheet(args.data, rows, args.n, seed=args.seed))


if __name__ == "__main__":
    main()
