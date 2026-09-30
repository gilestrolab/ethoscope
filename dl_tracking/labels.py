"""Turn AdaptiveBGModel rows into position labels for snapshots.

Pure functions over the arrays returned by :func:`dl_tracking.db_io.rows_between`
(columns in :data:`dl_tracking.db_io.ROI_COLUMNS`). Two kinds of label exist:

- ``confident``: the tracker found the fly in the snapshot's own frame, at a
  plausible size, and nothing in the surrounding track looks like a hop to a second
  blob or a teleport.
- ``gapfill``: the tracker lost the fly and found it again in the same place, so it
  was there throughout, including in the snapshot. These are the still flies that
  background subtraction misses.

A detection that fails the checks is kept as ``rejected_size`` or ``rejected_hop``,
with the tracker's position, so that it can be recovered later (for example when a
trained model agrees with it); it is not a training label. Anything else is
unlabelled. A tube where the tracker saw nothing is never a
negative: to the tracker, an empty tube and a fly dead from the start look the same.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

T, X, Y, W, H, PHI, XY_DIST, INFERRED = range(8)
CONFIDENT = "confident"
REJECTED_SIZE = "rejected_size"
REJECTED_HOP = "rejected_hop"
GAPFILL = "gapfill"


@dataclass(frozen=True)
class LabelParams:
    """Thresholds of the label rules (px at full resolution, times in ms)."""

    window_ms: int = 30_000  # track examined on each side of a snapshot
    # Reason: at 1-2 fps a walking fly makes 4-9 px steps and wanders back near
    # where it started, and the centroid jitters by 4 px as the blob changes shape;
    # a 4 px threshold flagged ~22% of windows, nearly all of them walking.
    jump_px: float = 8.0  # a single step larger than this may be a hop
    return_px: float = 2.0  # a hop returns to within this of where it left
    max_hop_rows: int = 20  # longest excursion counted as a hop
    hop_guard_ms: int = 10_000  # a hop this close to the snapshot rejects its label
    v_max_px_s: float = 300.0  # faster than any walking fly (~35 mm/s)
    size_k: float = 3.0  # size bounds: median +/- k * MAD ...
    w_floor_px: float = 3.0  # ... but never tighter than these
    h_floor_px: float = 2.0
    gap_shift_px: float = 3.0  # lost and found again within this distance
    max_gap_ms: int = 24 * 3600 * 1000


@dataclass(frozen=True)
class SizeBounds:
    """Plausible blob size of one fly, from its own track."""

    w_lo: float
    w_hi: float
    h_lo: float
    h_hi: float

    def contains(self, w: float, h: float) -> bool:
        """
        Tell whether a blob size is plausible for this fly.

        Args:
            w (float): Blob width.
            h (float): Blob height.

        Returns:
            bool: True if both dimensions lie within the bounds.
        """
        return self.w_lo <= w <= self.w_hi and self.h_lo <= h <= self.h_hi


@dataclass(frozen=True)
class Label:
    """Position of the fly in one tube of one snapshot (ROI-relative, full res)."""

    kind: str
    x: float
    y: float
    w: float
    h: float
    phi: float
    gap_ms: int  # 0 for confident labels
    span_px: float  # farthest real position in the window (movement proxy)
    n_window: int  # real rows in the window


def size_bounds(
    rows: np.ndarray, params: LabelParams = LabelParams()
) -> SizeBounds | None:
    """
    Estimate the plausible blob size of a fly from a sample of its real rows.

    Args:
        rows (np.ndarray): ROI rows (any subset spread over the run).
        params (LabelParams): Thresholds.

    Returns:
        SizeBounds | None: The bounds, or None if there are too few real rows.
    """
    real = rows[rows[:, INFERRED] == 0]
    if len(real) < 20:
        return None

    def bounds(v: np.ndarray, floor: float) -> tuple[float, float]:
        med = float(np.median(v))
        spread = max(params.size_k * float(np.median(np.abs(v - med))), floor)
        return med - spread, med + spread

    w_lo, w_hi = bounds(real[:, W], params.w_floor_px)
    h_lo, h_hi = bounds(real[:, H], params.h_floor_px)
    return SizeBounds(w_lo, w_hi, h_lo, h_hi)


def suspicious_rows(
    real: np.ndarray, params: LabelParams = LabelParams()
) -> np.ndarray:
    """
    Flag the rows of a track that sit on a hop to a second blob or on a teleport.

    A hop leaves in one step larger than ``jump_px`` and comes back, again in one
    large step, to within ``return_px`` of where it left, staying away for at most
    ``max_hop_rows`` rows. A walking fly moves away gradually and does not land
    back on its starting pixel in one step, so the return distinguishes a hop from
    walking even when the step sizes overlap. A teleport is any step faster than
    ``v_max_px_s``; both of its rows are flagged.

    Args:
        real (np.ndarray): Real (non-inferred) rows, in time order.
        params (LabelParams): Thresholds.

    Returns:
        np.ndarray: Boolean mask, True for suspicious rows.
    """
    n = len(real)
    flags = np.zeros(n, dtype=bool)
    if n < 2:
        return flags
    xy = real[:, [X, Y]]
    step = np.hypot(*np.diff(xy, axis=0).T)
    dt_s = np.maximum(np.diff(real[:, T]), 1) / 1000.0
    fast = step / dt_s > params.v_max_px_s
    flags[:-1] |= fast
    flags[1:] |= fast
    for i in np.flatnonzero(step > params.jump_px) + 1:  # row i is the first one away
        home = xy[i - 1]
        stop = min(n, i + params.max_hop_rows)
        away = np.hypot(*(xy[i:stop] - home).T)
        for j in range(i + 1, stop):
            if away[j - i] <= params.return_px:
                if step[j - 1] > params.jump_px and np.all(
                    away[: j - i] > params.jump_px
                ):
                    flags[i - 1 : j + 1] = True
                break
    return flags


def detection_label(
    rows: np.ndarray,
    t_snap: int,
    bounds: SizeBounds | None,
    params: LabelParams = LabelParams(),
) -> Label | None:
    """
    Label a snapshot from the tracker's own detection in that frame.

    Args:
        rows (np.ndarray): ROI rows within ``t_snap +/- window_ms``, in time order.
        t_snap (int): Snapshot time in ms.
        bounds (SizeBounds | None): This fly's plausible size; None fails the size
            check.
        params (LabelParams): Thresholds.

    Returns:
        Label | None: None if the tracker has no real detection at ``t_snap``;
        otherwise a label of kind ``confident``, ``rejected_size`` or
        ``rejected_hop``, at the tracker's position.
    """
    real = rows[rows[:, INFERRED] == 0]
    hit = np.flatnonzero(real[:, T] == t_snap)
    if len(hit) == 0:
        return None
    row = real[hit[0]]
    near = np.abs(real[:, T] - t_snap) <= params.hop_guard_ms
    if bounds is None or not bounds.contains(row[W], row[H]):
        kind = REJECTED_SIZE
    elif suspicious_rows(real, params)[near].any():
        kind = REJECTED_HOP
    else:
        kind = CONFIDENT
    span = float(np.hypot(*(real[:, [X, Y]] - row[[X, Y]]).T).max())
    return Label(kind, row[X], row[Y], row[W], row[H], row[PHI], 0, span, len(real))


def gapfill_label(
    before: np.ndarray | None,
    after: np.ndarray | None,
    t_snap: int,
    params: LabelParams = LabelParams(),
) -> Label | None:
    """
    Label a snapshot the tracker missed, when the fly was lost and found in place.

    Args:
        before (np.ndarray | None): The last real row before ``t_snap``.
        after (np.ndarray | None): The first real row after ``t_snap``.
        t_snap (int): Snapshot time in ms.
        params (LabelParams): Thresholds.

    Returns:
        Label | None: A ``gapfill`` label at the mean of the two positions, or None.
        Size and angle are the last detection's, and are not reliable for training.
    """
    if before is None or after is None:
        return None
    if not before[T] < t_snap < after[T]:
        return None
    gap = int(after[T] - before[T])
    shift = float(np.hypot(after[X] - before[X], after[Y] - before[Y]))
    if gap > params.max_gap_ms or shift > params.gap_shift_px:
        return None
    x, y = (before[X] + after[X]) / 2, (before[Y] + after[Y]) / 2
    return Label(GAPFILL, x, y, before[W], before[H], before[PHI], gap, shift, 0)


def local_contrast(crop: np.ndarray, x: float, y: float, r: int = 2) -> float:
    """
    Tell how much darker the label point is than the tube it sits in.

    The flies are dark on a back-lit tube, so a label on a fly has clearly positive
    contrast. Used as a sanity filter on gap-filled labels.

    Args:
        crop (np.ndarray): Greyscale ROI crop.
        x (float): Label x, crop-relative.
        y (float): Label y, crop-relative.
        r (int): Half-size of the patch averaged at the label.

    Returns:
        float: Median of the crop's rows around ``y`` minus the patch mean, in grey
        levels; NaN if the point lies outside the crop.
    """
    xi, yi = int(round(x)), int(round(y))
    h, w = crop.shape[:2]
    if not (0 <= xi < w and 0 <= yi < h):
        return float("nan")
    band = crop[max(0, yi - 3) : yi + 4]
    patch = crop[max(0, yi - r) : yi + r + 1, max(0, xi - r) : xi + r + 1]
    return float(np.median(band)) - float(patch.mean())
