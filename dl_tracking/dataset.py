"""Training data: a packed snapshot store, label selection, targets, augmentation.

``pack()`` concatenates every extracted snapshot JPEG into one ``snaps.bin`` with an
index, so a data-loader worker reads a snapshot with one slice of a memory map.

A dataset item is one snapshot: its frame is decoded and downsampled once and a
canvas is cut for every tube that has a training label (:func:`training_rows`).
With probability ``p_swap`` a tube's canvas also receives a window cut from
another snapshot of the same run with similar lighting, in which that tube's fly
sits elsewhere. When the window covers the fly, the canvas becomes a negative (no
fly); otherwise it stays a positive. Positives and negatives therefore carry the
same seams, and a seam tells the network nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset

from . import preprocess as P

OUT_H, OUT_W = P.CANVAS_H // P.STRIDE, P.CANVAS_W // P.STRIDE
SIGMA_CELLS = (1.0, 0.7)  # heatmap Gaussian (x, y); a fly is ~3 x 1.3 cells
SWAP_HALF_WIDTH = 20  # half-res px on each side of the fly
SWAP_MIN_DISTANCE = 35  # half-res px between the two flies for a clean swap
MAX_LUM_RATIO = 1.15  # snapshots this close in mean brightness may be mixed
MIN_CANVAS_STD = 2.0  # grey levels; flatter canvases show nothing


# ---------------------------------------------------------------- packing


def pack(data: Path) -> None:
    """
    Concatenate the extracted snapshots into ``pack/snaps.bin`` plus an index, and
    all labels into ``pack/labels.parquet`` (with a ``sid`` column). Run
    :func:`canvas_contrast` afterwards.

    Args:
        data (Path): Extraction output root (``snaps/`` and ``labels/``).
    """
    out = data / "pack"
    out.mkdir(exist_ok=True)
    index, labels, offset = [], [], 0
    with (out / "snaps.bin").open("wb") as fh:
        for path in sorted((data / "labels").glob("*.parquet")):
            rid = path.stem
            snaps = pd.read_parquet(data / "snaps" / f"{rid}.parquet")
            lab = pd.read_parquet(path)
            sids = {}
            for rowid, t, blob in snaps.itertuples(index=False):
                sids[rowid] = len(index)
                img = cv2.imdecode(
                    np.frombuffer(blob, np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_8
                )
                index.append((rid, rowid, t, offset, len(blob), float(img.mean())))
                fh.write(blob)
                offset += len(blob)
            lab["sid"] = lab.snap_rowid.map(sids)
            labels.append(lab)
    cols = ["run_id", "snap_rowid", "t", "offset", "length", "lum"]
    pd.DataFrame(index, columns=cols).to_parquet(out / "snaps_index.parquet")
    pd.concat(labels, ignore_index=True).to_parquet(out / "labels.parquet")


class SnapshotStore:
    """Random access to packed snapshots (safe to share across worker processes)."""

    def __init__(self, pack_dir: Path) -> None:
        """
        Open a pack.

        Args:
            pack_dir (Path): Directory written by :func:`pack`.
        """
        self.index = pd.read_parquet(pack_dir / "snaps_index.parquet")
        self._path = pack_dir / "snaps.bin"
        self._blob: np.memmap | None = None

    def frame(self, sid: int) -> np.ndarray:
        """
        Decode one snapshot at full resolution.

        Args:
            sid (int): Snapshot id (row of the index).

        Returns:
            np.ndarray: Greyscale frame.
        """
        if self._blob is None:  # opened lazily, once per worker
            self._blob = np.memmap(self._path, dtype=np.uint8, mode="r")
        off, n = self.index.offset.iat[sid], self.index.length.iat[sid]
        return cv2.imdecode(np.asarray(self._blob[off : off + n]), cv2.IMREAD_GRAYSCALE)


# ---------------------------------------------------------------- labels


def fits_canvas(labels: pd.DataFrame) -> pd.Series:
    """
    Tell which label rows belong to a tube-shaped ROI that fits the canvas.

    Args:
        labels (pd.DataFrame): Label rows with ``roi_w`` and ``roi_h``.

    Returns:
        pd.Series: Boolean mask.
    """
    return (labels.roi_w <= 2 * P.CANVAS_W) & (labels.roi_h <= 2 * P.CANVAS_H + 16)


def training_rows(
    labels: pd.DataFrame,
    use_gapfill: bool = False,
    canvas_std: pd.DataFrame | None = None,
    min_canvas_std: float = MIN_CANVAS_STD,
    gap_contrast_ratio: float = 0.4,
    gap_contrast_floor: float = 10.0,
) -> pd.DataFrame:
    """
    Select the label rows usable as positives and mark which heads they train.

    ``confident`` rows train every head. ``gapfill`` rows are off by default: the
    v1 model disagreed with 75% of them, and contact sheets showed why. Most sit on
    a static dark object at a tube end (an end cap, the ROI edge) that the tracker
    picks up about once a day, loses and finds again in place, which the gap-fill
    rule took for a still fly. When enabled they train position only, and only on a
    dark point: at least ``gap_contrast_ratio`` of the median contrast of the same
    fly's confident labels (or ``gap_contrast_floor`` grey levels without any).

    Args:
        labels (pd.DataFrame): Packed labels.
        use_gapfill (bool): Include gap-filled labels.
        canvas_std (pd.DataFrame | None): Output of :func:`canvas_contrast`; rows on
            canvases flatter than ``min_canvas_std`` are dropped (a black frame, or
            a snapshot that shows nothing where the tracker saw a fly).
        min_canvas_std (float): Minimum canvas standard deviation, grey levels.
        gap_contrast_ratio (float): Relative contrast a gap fill needs.
        gap_contrast_floor (float): Minimum contrast in grey levels.

    Returns:
        pd.DataFrame: Positive rows with a boolean ``shape_ok`` column.
    """
    parts = [labels[labels.status == "confident"].assign(shape_ok=True)]
    if use_gapfill:
        typical = (
            parts[0].groupby(["run_id", "roi_idx"]).contrast.median().rename("typical")
        )
        gaps = labels[labels.status == "gapfill"].join(
            typical, on=["run_id", "roi_idx"]
        )
        need = np.maximum(
            gap_contrast_floor, gap_contrast_ratio * gaps.typical.fillna(0)
        )
        parts.append(
            gaps[gaps.contrast >= need].drop(columns="typical").assign(shape_ok=False)
        )
    out = pd.concat(parts)
    out = out[fits_canvas(out)]
    if canvas_std is not None:
        out = out.merge(canvas_std, on=["sid", "roi_idx"], how="left")
        out = out[out.canvas_std.fillna(0) >= min_canvas_std].drop(columns="canvas_std")
    return out.sort_values(["sid", "roi_idx"])


def _canvas_std_of_snapshot(args: tuple) -> list[tuple[int, int, float]]:
    """Pool worker for :func:`canvas_contrast`: one snapshot's canvas spreads."""
    store, sid, rois = args
    cv2.setNumThreads(1)
    img = store.frame(sid)
    if img is None:
        return [(sid, int(r[0]), -1.0) for r in rois]
    half = P.downsample(img)
    return [
        (
            sid,
            int(r[0]),
            float(
                P.cut(
                    half, *P.canvas_origin(*map(int, r[1:])), P.CANVAS_W, P.CANVAS_H
                ).std()
            ),
        )
        for r in rois
    ]


def canvas_contrast(pack_dir: Path, workers: int = 16) -> pd.DataFrame:
    """
    Measure the standard deviation of every labelled tube canvas in a pack.

    Writes ``canvas_std.parquet`` next to the pack. A canvas with almost no spread
    shows nothing (a black frame, or a corrupt snapshot), whatever its label says.

    Args:
        pack_dir (Path): Directory written by :func:`pack`.
        workers (int): Parallel processes.

    Returns:
        pd.DataFrame: ``sid``, ``roi_idx``, ``canvas_std`` (-1 if undecodable).
    """
    store = SnapshotStore(pack_dir)
    lab = pd.read_parquet(pack_dir / "labels.parquet")
    lab = lab[fits_canvas(lab) & lab.sid.notna()]
    cols = ["roi_idx", "roi_x", "roi_y", "roi_w", "roi_h"]
    jobs = [(store, int(sid), g[cols].to_numpy()) for sid, g in lab.groupby("sid")]
    if workers <= 1:
        chunks = list(map(_canvas_std_of_snapshot, jobs))
    else:
        # Reason: forking a process that has started torch/OpenCV threads can
        # deadlock the children; spawned workers start clean.
        with get_context("spawn").Pool(workers) as pool:
            chunks = pool.map(_canvas_std_of_snapshot, jobs, chunksize=100)
    out = [x for chunk in chunks for x in chunk]
    df = pd.DataFrame(out, columns=["sid", "roi_idx", "canvas_std"])
    df.to_parquet(pack_dir / "canvas_std.parquet")
    return df


# ---------------------------------------------------------------- targets


@dataclass
class Target:
    """What the network should output for one canvas."""

    present: bool
    u: float = 0.0  # canvas coordinates
    v: float = 0.0
    w: float = 0.0  # full-resolution blob size
    h: float = 0.0
    phi: float = 0.0  # degrees, 0-180
    shape_ok: bool = False


def encode(t: Target) -> dict[str, np.ndarray]:
    """
    Turn a target into training tensors on the output grid.

    Args:
        t (Target): The target.

    Returns:
        dict[str, np.ndarray]: ``heat`` (OUT_H x OUT_W), ``cell`` (i, j),
        ``reg`` (offset x/y, log w/h, sin/cos 2phi), and 0/1 masks ``pos``
        (position heads) and ``shape`` (size and angle heads), plus ``present``.
    """
    heat = np.zeros((OUT_H, OUT_W), np.float32)
    reg = np.zeros(6, np.float32)
    cell = np.zeros(2, np.int64)
    pos = shape = 0.0
    cx, cy = (t.u + 0.5) / P.STRIDE, (t.v + 0.5) / P.STRIDE
    j, i = int(np.floor(cx)), int(np.floor(cy))
    if t.present and 0 <= i < OUT_H and 0 <= j < OUT_W:
        jj, ii = np.meshgrid(np.arange(OUT_W), np.arange(OUT_H))
        heat = np.exp(
            -(
                (jj - j) ** 2 / (2 * SIGMA_CELLS[0] ** 2)
                + (ii - i) ** 2 / (2 * SIGMA_CELLS[1] ** 2)
            )
        ).astype(np.float32)
        a = np.radians(2 * t.phi)
        reg[:] = (
            cx - j,
            cy - i,
            np.log(max(t.w, 1)),
            np.log(max(t.h, 1)),
            np.sin(a),
            np.cos(a),
        )
        cell[:] = (i, j)
        pos, shape = 1.0, float(t.shape_ok)
    present = float(t.present and pos > 0)
    return {
        "heat": heat,
        "reg": reg,
        "cell": cell,
        "pos": np.float32(pos),
        "shape": np.float32(shape),
        "present": np.float32(present),
    }


# ---------------------------------------------------------------- augmentation


def photometric(canvas: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """
    Vary lighting, contrast, noise, blur and compression, as between setups.

    Args:
        canvas (np.ndarray): uint8 canvas.
        rng (np.random.Generator): Random source.

    Returns:
        np.ndarray: uint8 canvas.
    """
    x = canvas.astype(np.float32) / 255
    if rng.random() < 0.2:  # very dim, as in the runs without IR
        x *= rng.uniform(0.15, 0.5)
    x = np.clip(
        x * rng.uniform(0.6, 1.4) + rng.uniform(-0.1, 0.1), 0, 1
    ) ** rng.uniform(0.7, 1.4)
    if rng.random() < 0.3:  # uneven illumination along the tube
        x *= np.linspace(1, rng.uniform(0.6, 1.4), x.shape[1])[None]
    if rng.random() < 0.3:
        x = cv2.GaussianBlur(x, (0, 0), rng.uniform(0.3, 0.9))
    x = x * 255 + rng.normal(0, rng.uniform(0, 6), x.shape)
    out = np.clip(x, 0, 255).astype(np.uint8)
    if rng.random() < 0.5:
        ok, buf = cv2.imencode(
            ".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(20, 96))]
        )
        out = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    return out


def flip(canvas: np.ndarray, t: Target, horizontal: bool, vertical: bool):
    """
    Mirror a canvas and its target. Either flip maps the angle to ``180 - phi``.

    Args:
        canvas (np.ndarray): Canvas.
        t (Target): Its target.
        horizontal (bool): Mirror left-right.
        vertical (bool): Mirror top-bottom.

    Returns:
        tuple[np.ndarray, Target]: The mirrored pair.
    """
    h, w = canvas.shape
    if horizontal:
        canvas, t = canvas[:, ::-1], Target(**{**t.__dict__, "u": w - 1 - t.u})
    if vertical:
        canvas, t = canvas[::-1], Target(**{**t.__dict__, "v": h - 1 - t.v})
    if horizontal != vertical:
        t = Target(**{**t.__dict__, "phi": (180 - t.phi) % 180})
    return np.ascontiguousarray(canvas), t


# ---------------------------------------------------------------- dataset


def match_gain(src: np.ndarray, dst: np.ndarray) -> tuple[float, float]:
    """
    Return the gain and offset that give ``src`` the mean and spread of ``dst``.

    Args:
        src (np.ndarray): Pixels to be corrected.
        dst (np.ndarray): Reference pixels (same region in the other image).

    Returns:
        tuple[float, float]: ``(a, b)`` with ``a * src + b`` matching ``dst``. A flat
        ``src`` (spread under one grey level) gets unit gain, so noise is not
        amplified.
    """
    s, d = src.astype(np.float64), dst.astype(np.float64)
    spread = s.std()
    a = d.std() / spread if spread >= 1.0 else 1.0
    return a, d.mean() - a * s.mean()


class TubeDataset(Dataset):
    """One item per snapshot: canvases and targets for its labelled tubes."""

    def __init__(
        self,
        store: SnapshotStore,
        rows: pd.DataFrame,
        augment: bool,
        p_swap: float = 0.5,
        seed: int = 0,
    ) -> None:
        """
        Build the dataset.

        Args:
            store (SnapshotStore): The packed snapshots.
            rows (pd.DataFrame): Output of :func:`training_rows` (one split).
            augment (bool): Apply shifts, flips and photometric changes.
            p_swap (float): Probability that a tube gets a window swapped in
                (independent of ``augment``, so validation can measure presence
                on swapped negatives without the other augmentations).
            seed (int): Base seed; each worker and item derives its own.
        """
        self.store, self.augment, self.p_swap, self.seed = store, augment, p_swap, seed
        self.rows = rows
        self.sids = rows.sid.unique()
        self.by_sid = dict(tuple(rows.groupby("sid")))
        self.by_run = {rid: g.sid.unique() for rid, g in rows.groupby("run_id")}
        self.lum = store.index.lum.to_numpy()

    def __len__(self) -> int:
        """Number of snapshots."""
        return len(self.sids)

    def _partner(self, sid: int, rid: str, rng: np.random.Generator) -> int | None:
        """Another snapshot of the same run with similar brightness, if any."""
        cands = self.by_run[rid]
        ratio = self.lum[cands] / max(self.lum[sid], 1)
        ok = cands[
            (cands != sid) & (ratio < MAX_LUM_RATIO) & (ratio > 1 / MAX_LUM_RATIO)
        ]
        return int(rng.choice(ok)) if len(ok) else None

    def __getitem__(self, k: int) -> dict[str, torch.Tensor]:
        """
        Build the canvases and targets of one snapshot.

        Args:
            k (int): Item index.

        Returns:
            dict[str, torch.Tensor]: Batched per tube: ``x`` (n, 1, H, W) and the
            fields of :func:`encode`.
        """
        rng = np.random.default_rng((self.seed, k, torch.initial_seed() % 2**31))
        sid = int(self.sids[k])
        rows = self.by_sid[sid]
        rid = rows.run_id.iat[0]
        half = P.downsample(self.store.frame(sid))
        partner = self._partner(sid, rid, rng) if self.p_swap > 0 else None
        other = self.by_sid.get(partner) if partner is not None else None
        half2 = P.downsample(self.store.frame(partner)) if other is not None else None
        canv, targets = [], []
        for r in rows.itertuples(index=False):
            origin = P.canvas_origin(r.roi_x, r.roi_y, r.roi_w, r.roi_h)
            if self.augment:  # jitter the canvas along the tube and across it
                # Reason: +/-12 keeps the next tube across the divider (~24 half-res
                # px beyond the canvas) out of view, so no unlabelled fly enters.
                origin = (
                    origin[0] + int(rng.integers(-12, 13)),
                    origin[1] + int(rng.integers(-2, 3)),
                )
            # Reason: human-verified empty tubes arrive as rows with present=False.
            present = bool(getattr(r, "present", True))
            if present:
                u, v = P.full_to_canvas(r.roi_x + r.x, r.roi_y + r.y, origin)
                t = Target(True, u, v, r.w, r.h, r.phi, bool(r.shape_ok))
            else:
                t = Target(False)
            c = P.cut(half, *origin, P.CANVAS_W, P.CANVAS_H).copy()
            if present and half2 is not None and rng.random() < self.p_swap:
                c, t = self._swap(c, t, half2, origin, other, r, rng)
            if self.augment:
                c, t = flip(c, t, rng.random() < 0.5, rng.random() < 0.5)
                c = photometric(c, rng)
            canv.append(c)
            targets.append(encode(t))
        batch = {
            key: torch.from_numpy(np.stack([t[key] for t in targets]))
            for key in targets[0]
        }
        batch["x"] = torch.from_numpy(P.normalise(np.stack(canv)))
        return batch

    def _swap(self, c, t, half2, origin, other, r, rng):
        """Paste a window from the partner snapshot; a negative if it covers the fly."""
        match = other[other.roi_idx == r.roi_idx]
        if match.empty or not match.shape_ok.iat[0]:
            return c, t
        u2, _ = P.full_to_canvas(r.roi_x + match.x.iat[0], 0, origin)
        if abs(u2 - t.u) < SWAP_MIN_DISTANCE:
            return c, t
        src = P.cut(half2, *origin, P.CANVAS_W, P.CANVAS_H)
        cover = rng.random() < 0.5
        if cover:
            centre = t.u
        else:  # a window that avoids both flies
            free = [
                x
                for x in range(SWAP_HALF_WIDTH, P.CANVAS_W - SWAP_HALF_WIDTH)
                if abs(x - t.u) > SWAP_HALF_WIDTH + 8
                and abs(x - u2) > SWAP_HALF_WIDTH + 8
            ]
            if not free:
                return c, t
            centre = float(rng.choice(free))
        cols = np.arange(P.CANVAS_W)
        dist = np.abs(cols - centre)
        alpha = np.clip((SWAP_HALF_WIDTH - dist) / 4, 0, 1)[None]
        # Reason: two snapshots with the same overall brightness still differ
        # locally (IR drift, exposure), so a raw paste shows as a bright or dark band.
        # Match src to c on the columns just outside the window. A mean-and-spread
        # match has a closed form; np.polyfit failed to converge on flat rings.
        ring = (dist > SWAP_HALF_WIDTH) & (dist <= SWAP_HALF_WIDTH + 10)
        a, b = match_gain(src[:, ring], c[:, ring])
        if not 0.5 < a < 2.0:
            return c, t
        mixed = (1 - alpha) * c + alpha * np.clip(a * src.astype(float) + b, 0, 255)
        return mixed.astype(np.uint8), (Target(False) if cover else t)


def collate(items: list[dict[str, torch.Tensor]]) -> dict[str, torch.Tensor]:
    """
    Concatenate per-snapshot batches along the tube axis.

    Args:
        items (list[dict[str, torch.Tensor]]): Dataset items.

    Returns:
        dict[str, torch.Tensor]: One batch of tubes.
    """
    return {k: torch.cat([it[k] for it in items]) for k in items[0]}
