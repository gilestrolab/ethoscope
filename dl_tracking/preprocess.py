"""Tube-crop geometry and normalisation shared by training and the device.

The network sees each tube at half resolution, on a fixed canvas centred on the
ROI, so a fly has the same size in pixels in every tube and every layout. The
whole frame is area-downsampled once and every canvas is cut from it, by
:func:`canvases_from_frame`, both on the device and in training (where the
augmentations then act on the canvases). One path, so the two cannot drift.

Coordinates are continuous with pixel centres on integers, as in the tracker's
output. A half-resolution pixel ``j`` averages full-resolution pixels ``2j`` and
``2j + 1``, whose centres average to ``2j + 0.5``; hence ``u = (X - 0.5) / 2``.

This module is meant to move into the device package with the runtime tracker;
it depends only on numpy and OpenCV.
"""

from __future__ import annotations

import cv2
import numpy as np

CANVAS_H = 32  # half-resolution pixels
CANVAS_W = 288
STRIDE = 4  # network output stride, in half-resolution pixels
BLEND_LOGITS = 1.0  # see decode(): margin over which a competing neighbour fades out


def canvas_origin(x0: int, y0: int, w: int, h: int) -> tuple[int, int]:
    """
    Return the half-resolution frame coordinates of a ROI's canvas corner.

    Args:
        x0 (int): ROI left edge, full resolution.
        y0 (int): ROI top edge, full resolution.
        w (int): ROI width, full resolution.
        h (int): ROI height, full resolution.

    Returns:
        tuple[int, int]: ``(cx0, cy0)``, so that the canvas spans half-resolution
        columns ``cx0 .. cx0 + CANVAS_W`` and rows ``cy0 .. cy0 + CANVAS_H``.
    """
    cx0 = int(round((x0 + w / 2) / 2 - CANVAS_W / 2))
    cy0 = int(round((y0 + h / 2) / 2 - CANVAS_H / 2))
    return cx0, cy0


def full_to_canvas(x: float, y: float, origin: tuple[int, int]) -> tuple[float, float]:
    """
    Map a full-resolution frame position to canvas coordinates.

    Args:
        x (float): Frame x, full resolution.
        y (float): Frame y, full resolution.
        origin (tuple[int, int]): From :func:`canvas_origin`.

    Returns:
        tuple[float, float]: ``(u, v)`` on the canvas.
    """
    return (x - 0.5) / 2 - origin[0], (y - 0.5) / 2 - origin[1]


def canvas_to_full(u: float, v: float, origin: tuple[int, int]) -> tuple[float, float]:
    """
    Inverse of :func:`full_to_canvas`.

    Args:
        u (float): Canvas x.
        v (float): Canvas y.
        origin (tuple[int, int]): From :func:`canvas_origin`.

    Returns:
        tuple[float, float]: ``(x, y)`` in the full-resolution frame.
    """
    return 2 * (u + origin[0]) + 0.5, 2 * (v + origin[1]) + 0.5


def cut(img: np.ndarray, x0: int, y0: int, w: int, h: int) -> np.ndarray:
    """
    Cut a region from an image, padding with edge pixels where it leaves the frame.

    Args:
        img (np.ndarray): Greyscale image.
        x0 (int): Region left edge (may be negative).
        y0 (int): Region top edge (may be negative).
        w (int): Region width.
        h (int): Region height.

    Returns:
        np.ndarray: The ``h x w`` region.
    """
    H, W = img.shape[:2]
    xa, ya, xb, yb = max(x0, 0), max(y0, 0), min(x0 + w, W), min(y0 + h, H)
    region = img[ya:yb, xa:xb]
    if region.shape[:2] == (h, w):
        return region
    return cv2.copyMakeBorder(
        region, ya - y0, y0 + h - yb, xa - x0, x0 + w - xb, cv2.BORDER_REPLICATE
    )


def downsample(img: np.ndarray) -> np.ndarray:
    """
    Halve an image by 2x2 averaging (what ``INTER_AREA`` does at exactly 0.5).

    Args:
        img (np.ndarray): Image with even height and width.

    Returns:
        np.ndarray: The half-resolution image, same dtype.
    """
    return cv2.resize(
        img, (img.shape[1] // 2, img.shape[0] // 2), interpolation=cv2.INTER_AREA
    )


def canvases_from_frame(
    frame: np.ndarray, origins: list[tuple[int, int]]
) -> np.ndarray:
    """
    Device path: downsample the frame once and cut every canvas from it.

    Args:
        frame (np.ndarray): Full-resolution greyscale frame.
        origins (list[tuple[int, int]]): One canvas origin per ROI.

    Returns:
        np.ndarray: ``(n, CANVAS_H, CANVAS_W)`` uint8.
    """
    half = downsample(frame)
    return np.stack([cut(half, cx, cy, CANVAS_W, CANVAS_H) for cx, cy in origins])


def normalise(canvases: np.ndarray) -> np.ndarray:
    """
    Standardise each canvas to zero mean and unit spread.

    The fly covers ~1% of a canvas, so the mean and standard deviation describe the
    tube's lighting rather than the fly; the ``+ 1`` keeps a flat, dark canvas from
    amplifying sensor noise into apparent structure.

    Args:
        canvases (np.ndarray): ``(n, h, w)`` uint8 (or float) canvases.

    Returns:
        np.ndarray: ``(n, 1, h, w)`` float32, ready for the network.
    """
    # Reason: numpy's std() made this 6 ms of a Pi 3 frame (several passes and
    # temporaries); cv2.meanStdDev per canvas and in-place arithmetic do the same
    # (population statistics, ddof = 0) in a fraction of that.
    stats = np.array([cv2.meanStdDev(c) for c in canvases]).reshape(len(canvases), 2)
    x = canvases.astype(np.float32)
    x -= stats[:, 0, None, None].astype(np.float32)
    x *= (1.0 / (stats[:, 1] + 1.0))[:, None, None].astype(np.float32)
    return x[:, None]


def decode(
    maps: np.ndarray, presence: np.ndarray, blend_logits: float = BLEND_LOGITS
) -> np.ndarray:
    """
    Turn network outputs into one position per canvas (argmax, no NMS).

    A fly whose centre lies on a cell boundary gives two cells almost the same
    heatmap logit, and the argmax flips between them from frame to frame. Each
    cell's own estimate (cell + offset) is steady but the two disagree slightly, so
    a still fly appeared to jump by ~1 px. The position is therefore a mixture of
    the peak cell and its strongest 8-neighbour, weighted by
    ``w = 0.5 * max(0, 1 - margin / blend_logits)`` for the neighbour. At a tie
    the mixture is 50/50 whichever cell wins, so it is continuous across a flip;
    one ``blend_logits`` below the peak the neighbour has no say, so a clean single
    peak decodes exactly as before and a separate second blob is never averaged in.

    Args:
        maps (np.ndarray): ``(n, 7, h, w)``: heatmap logit, offset x/y, log w/h,
            sin/cos of twice the angle.
        presence (np.ndarray): ``(n, 1)`` presence logits.
        blend_logits (float): Logit margin over which the neighbour's weight goes
            from 0.5 to 0; 0 disables blending.

    Returns:
        np.ndarray: ``(n, 8)``: u, v (canvas), w, h (full resolution), phi
        (degrees, 0-180), peak probability, presence probability, peak index.
    """
    n, _, h, w = maps.shape
    rows = np.arange(n)
    flat = maps[:, 0].reshape(n, -1)
    idx = flat.argmax(axis=1)
    i, j = np.divmod(idx, w)
    at = maps[rows, :, i, j]  # (n, 7)
    u = STRIDE * (j + at[:, 1]) - 0.5
    v = STRIDE * (i + at[:, 2]) - 0.5
    if blend_logits > 0:
        # The strongest of the 8 neighbours (padding with -inf keeps edges out).
        heat = np.pad(maps[:, 0], ((0, 0), (1, 1), (1, 1)), constant_values=-np.inf)
        di, dj = np.meshgrid([-1, 0, 1], [-1, 0, 1], indexing="ij")
        di, dj = (
            di.ravel()[[0, 1, 2, 3, 5, 6, 7, 8]],
            dj.ravel()[[0, 1, 2, 3, 5, 6, 7, 8]],
        )
        nb = heat[rows[:, None], i[:, None] + 1 + di, j[:, None] + 1 + dj]  # (n, 8)
        k = nb.argmax(axis=1)
        ni, nj = i + di[k], j + dj[k]
        margin = flat[rows, idx] - nb[rows, k]
        wn = 0.5 * np.clip(1 - margin / blend_logits, 0, 1)
        ok = wn > 0
        if ok.any():
            nat = maps[rows[ok], :, ni[ok], nj[ok]]
            un = STRIDE * (nj[ok] + nat[:, 1]) - 0.5
            vn = STRIDE * (ni[ok] + nat[:, 2]) - 0.5
            u[ok] = (1 - wn[ok]) * u[ok] + wn[ok] * un
            v[ok] = (1 - wn[ok]) * v[ok] + wn[ok] * vn
    fw, fh = np.exp(at[:, 3]), np.exp(at[:, 4])
    phi = np.degrees(np.arctan2(at[:, 5], at[:, 6]) / 2) % 180
    peak = 1 / (1 + np.exp(-flat[rows, idx]))
    pres = 1 / (1 + np.exp(-presence[:, 0]))
    return np.column_stack([u, v, fw, fh, phi, peak, pres, idx]).astype(np.float64)
