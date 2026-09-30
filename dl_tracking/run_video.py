"""Run a trained locator over a recorded video, one row per frame and tube.

Frames are stamped like ``MovieVirtualCamera`` stamps them (``CAP_PROP_POS_MSEC``,
integer ms), so the output lines up with an offline AdaptiveBGModel DB of the same
video. Positions are ROI-relative and at full resolution, as in the DBs.

Usage::

    python -m dl_tracking.run_video VIDEO ROI_DB CKPT OUT.parquet [--start S --end S]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import torch

from . import db_io
from . import model as M
from . import preprocess as P

BATCH_FRAMES = 32


def load_net(ckpt: Path, device: str) -> torch.nn.Module:
    """
    Load a training checkpoint for inference.

    Args:
        ckpt (Path): ``best.pt`` or ``last.pt`` from :mod:`dl_tracking.train`.
        device (str): Torch device.

    Returns:
        torch.nn.Module: The network, in eval mode.
    """
    state = torch.load(ckpt, map_location=device)
    net = M.build(state["variant"])
    net.load_state_dict(state["state_dict"])
    return net.to(device).eval()


def locate(
    net: torch.nn.Module, frames: list[np.ndarray], rois: np.ndarray, device: str
) -> np.ndarray:
    """
    Locate the fly in every ROI of every frame.

    Args:
        net (torch.nn.Module): The network.
        frames (list[np.ndarray]): Full-resolution greyscale frames.
        rois (np.ndarray): ``(n, 5)`` ROI map rows (idx, x, y, w, h).
        device (str): Torch device.

    Returns:
        np.ndarray: ``(len(frames), n, 7)``: x, y (ROI-relative, full res), w, h,
        phi, peak and presence probabilities.
    """
    origins = [P.canvas_origin(*map(int, r[1:])) for r in rois]
    batch = np.concatenate(
        [P.normalise(P.canvases_from_frame(f, origins)) for f in frames]
    )
    with torch.no_grad():
        maps, pres = net(torch.from_numpy(batch).to(device))
    dec = P.decode(maps.float().cpu().numpy(), pres.float().cpu().numpy())
    dec = dec.reshape(len(frames), len(rois), -1)
    out = np.empty((len(frames), len(rois), 7))
    for k, (origin, roi) in enumerate(zip(origins, rois, strict=True)):
        x, y = P.canvas_to_full(dec[:, k, 0], dec[:, k, 1], origin)
        out[:, k, 0], out[:, k, 1] = x - roi[1], y - roi[2]
    out[..., 2:7] = dec[..., 2:7]
    return out


def run(
    video: Path,
    roi_db: Path,
    ckpt: Path,
    out: Path,
    start_s: float = 0.0,
    end_s: float | None = None,
    device: str = "cuda",
) -> int:
    """
    Process a video (or a time segment of it) and write the positions to parquet.

    Args:
        video (Path): The video file.
        roi_db (Path): A tracking DB of the same video, for its ROI_MAP.
        ckpt (Path): Model checkpoint.
        out (Path): Output parquet.
        start_s (float): Segment start, seconds of video time.
        end_s (float | None): Segment end (exclusive), or None for the end.
        device (str): Torch device.

    Returns:
        int: Frames processed.
    """
    with db_io.connect(roi_db) as conn:
        rois = db_io.roi_map(conn)
    net = load_net(ckpt, device)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(start_s * fps))
    parts, frames, stamps, n = [], [], [], 0

    def flush() -> None:
        res = locate(net, frames, rois, device)
        t = np.repeat(np.array(stamps), len(rois))
        parts.append(
            pd.DataFrame(
                {
                    "t": t,
                    "roi_idx": np.tile(rois[:, 0], len(frames)),
                    **{
                        c: res[..., i].ravel()
                        for i, c in enumerate(
                            ["x", "y", "w", "h", "phi", "peak", "presence"]
                        )
                    },
                }
            )
        )
        frames.clear()
        stamps.clear()

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t_ms = int(cap.get(cv2.CAP_PROP_POS_MSEC))
        if end_s is not None and t_ms >= 1000 * end_s:
            break
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        stamps.append(t_ms)
        n += 1
        if len(frames) == BATCH_FRAMES:
            flush()
            if n % (BATCH_FRAMES * 100) == 0:
                logging.info("%d frames, t = %.0f s", n, t_ms / 1000)
    if frames:
        flush()
    pd.concat(parts, ignore_index=True).to_parquet(out)
    return n


def main() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video", type=Path)
    ap.add_argument("roi_db", type=Path)
    ap.add_argument("ckpt", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    n = run(
        args.video, args.roi_db, args.ckpt, args.out, args.start, args.end, args.device
    )
    logging.info("done: %d frames", n)


if __name__ == "__main__":
    main()
