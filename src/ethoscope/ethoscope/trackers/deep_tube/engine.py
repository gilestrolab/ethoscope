"""Batched inference for :class:`DeepTubeTracker`: one network pass per frame for all tubes.

The Monitor asks each ROI's tracker for its position in turn. The network, though,
runs most cheaply on every tube of a frame at once, and the camera-shake correction
needs every tube's step to be known before any tube's movement is reported. So one
:class:`BatchLocator` per Monitor processes the whole frame on the first request
for it and serves the other tubes from that result.

Camera shake: a rig whose camera vibrates moves every fly in the image by the same
amount. The median step over the tubes is that common motion (most flies are still
at any moment), so it is subtracted from each tube's step; when it is large
(>= ``CM_GATE_PX``) no step on that frame is trusted. Positions are reported as
measured; only the movement value is corrected. Validated on a 2019 rig whose camera
shook by 1-1.5 px (``tasks/todo.dl-tracking.md``, ETHOSCOPE_109).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import preprocess as P

MODEL_CARD = Path(__file__).parent / "models" / "fly_locator_tiny_s2_v5.json"
FRAME_SIZE = (1280, 960)  # (width, height) of every training frame
PRESENCE_MIN = 0.5  # presence probability below which a tube has no fly
CM_MIN_ROIS = 5  # tubes needed to estimate the camera's own motion
CM_GATE_PX = 0.3  # camera motion above which a frame's steps are not trusted
ROI_MAX = (576, 80)  # largest ROI (w, h) in the training data, full resolution
MIN_ASPECT = 5  # a tube is at least 5 times longer than it is wide


@dataclass(frozen=True)
class Detection:
    """One tube's fly in one frame (full-resolution pixels, ROI-relative)."""

    x: float
    y: float
    w: float
    h: float
    phi: float  # degrees, 0-180
    step: float  # displacement since the tube's previous detection, shake removed
    presence: float


def setup_problems(frame_size: tuple[int, int], rects: list[tuple]) -> list[str]:
    """
    Tell why a camera and ROI layout cannot be tracked by the model, if it cannot.

    Args:
        frame_size (tuple[int, int]): Camera frame ``(width, height)``.
        rects (list[tuple]): ``(idx, x, y, w, h)`` per ROI, full resolution.

    Returns:
        list[str]: Human-readable problems; empty when the layout is supported.
    """
    problems = []
    if tuple(frame_size) != FRAME_SIZE:
        problems.append(
            f"frames are {frame_size[0]}x{frame_size[1]}, the model needs "
            f"{FRAME_SIZE[0]}x{FRAME_SIZE[1]}"
        )
    big = [str(r[0]) for r in rects if r[3] > ROI_MAX[0] or r[4] > ROI_MAX[1]]
    if big:
        problems.append(
            f"ROI {', '.join(big[:5])}{' ...' if len(big) > 5 else ''} larger than "
            f"{ROI_MAX[0]}x{ROI_MAX[1]} px"
        )
    wide = [str(r[0]) for r in rects if r[3] < MIN_ASPECT * r[4]]
    if wide:
        problems.append(
            f"ROI {', '.join(wide[:5])}{' ...' if len(wide) > 5 else ''} not tube-shaped "
            f"(length under {MIN_ASPECT} times the width)"
        )
    return problems


def corrected_steps(
    disp: np.ndarray,
    consecutive: np.ndarray,
    min_rois: int = CM_MIN_ROIS,
    gate_px: float = CM_GATE_PX,
) -> np.ndarray:
    """
    Remove the camera's own motion from every tube's step.

    Args:
        disp (np.ndarray): Complex displacement of each tube since its previous
            detection; NaN where there is none (no fly now, or never seen before).
        consecutive (np.ndarray): True where that previous detection was in the
            previous frame. Only those tubes estimate the camera's motion; a tube
            back from a gap moved over a longer interval.
        min_rois (int): Tubes needed for an estimate; with fewer, nothing changes.
        gate_px (float): Camera motion from which every step on the frame is 0.

    Returns:
        np.ndarray: Step lengths in px, NaN where ``disp`` is NaN.
    """
    steps = np.abs(disp)
    ok = consecutive & np.isfinite(disp)
    if ok.sum() < min_rois:
        return steps
    # Reason: dx and dy separately, so a few walking flies cannot drag the estimate
    common = complex(np.median(disp[ok].real), np.median(disp[ok].imag))
    if abs(common) >= gate_px:
        return np.where(np.isfinite(disp), 0.0, np.nan)
    steps[ok] = np.abs(disp[ok] - common)
    return steps


def load_model(card_path: Path = MODEL_CARD) -> tuple[cv2.dnn.Net, dict]:
    """
    Load the network named by a model card, after checking the card against the file.

    Args:
        card_path (Path): The model card (JSON) next to the ONNX file.

    Returns:
        tuple[cv2.dnn.Net, dict]: The network and the card.

    Raises:
        ValueError: If the file's checksum or the card's preprocessing does not match.
    """
    card = json.loads(Path(card_path).read_text())
    onnx = Path(card_path).parent / card["file"]
    digest = hashlib.sha256(onnx.read_bytes()).hexdigest()
    if digest != card["sha256"]:
        raise ValueError(f"{onnx.name}: checksum {digest} does not match its card")
    pre = card["preprocessing"]
    expected = ([P.CANVAS_H, P.CANVAS_W], P.STRIDE, P.BLEND_LOGITS)
    if (pre["canvas"], pre["stride"], pre["decode_blend_logits"]) != expected:
        raise ValueError(f"{card['name']}: preprocessing differs from this code")
    return cv2.dnn.readNetFromONNX(str(onnx)), card


class BatchLocator:
    """Locate the fly in every tube of a frame with one network pass."""

    def __init__(self, rects: list[tuple[int, int, int, int]], net=None) -> None:
        """
        Prepare the canvases of a fixed set of ROIs.

        Args:
            rects (list[tuple[int, int, int, int]]): ``(x, y, w, h)`` of each ROI's
                bounding rectangle, in the order of the slots used by :meth:`get`.
            net: A loaded network, or None to load the packaged model. Anything with
                ``setInput`` and ``forward`` will do (tests pass a fake).
        """
        if net is None:
            net, self.card = load_model()
        else:
            self.card = None
        self._net = net
        n = len(rects)
        self._origins = [P.canvas_origin(*map(int, r)) for r in rects]
        self._canvas_xy = np.array(self._origins, dtype=np.float64)
        self._roi_xy = np.array([(r[0], r[1]) for r in rects], dtype=np.float64)
        self._prev = np.full(n, complex(np.nan, np.nan))
        self._last_seen = np.full(n, -2)
        self._batch = 0
        self._t = None
        self._frame = None
        self._results: list[Detection | None] = [None] * n
        self.forward_passes = 0

    def get(self, t: int, frame: np.ndarray, slot: int) -> Detection | None:
        """
        Return one tube's detection in a frame, running the batch on the first call.

        Args:
            t (int): Frame time, ms.
            frame (np.ndarray): The whole frame.
            slot (int): Index of the ROI in the list given at construction.

        Returns:
            Detection | None: The fly, or None if the tube shows none.
        """
        # Reason: key on the frame object as well as t; a video camera stamps its
        # first two frames t = 0. Holding the frame keeps its id from being reused.
        if t != self._t or frame is not self._frame:
            self._run(frame)
            self._t, self._frame = t, frame
        return self._results[slot]

    def _run(self, frame: np.ndarray) -> None:
        """Run the network on every tube of ``frame`` and update the step state."""
        if frame.ndim == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if (frame.shape[1], frame.shape[0]) != FRAME_SIZE:
            raise ValueError(
                f"DeepTubeTracker needs {FRAME_SIZE[0]}x{FRAME_SIZE[1]} frames, got "
                f"{frame.shape[1]}x{frame.shape[0]}"
            )
        self._net.setInput(P.normalise(P.canvases_from_frame(frame, self._origins)))
        maps, presence = self._net.forward(["maps", "presence"])
        self.forward_passes += 1
        dec = P.decode(np.asarray(maps), np.asarray(presence))
        # canvas -> full frame (P.canvas_to_full, vectorised) -> ROI-relative
        x = 2 * (dec[:, 0] + self._canvas_xy[:, 0]) + 0.5 - self._roi_xy[:, 0]
        y = 2 * (dec[:, 1] + self._canvas_xy[:, 1]) + 0.5 - self._roi_xy[:, 1]
        found = np.isfinite(dec[:, :7]).all(axis=1) & (dec[:, 6] >= PRESENCE_MIN)
        pos = x + 1j * y
        disp = np.where(found, pos - self._prev, complex(np.nan, np.nan))
        consecutive = found & (self._last_seen == self._batch - 1)
        steps = corrected_steps(disp, consecutive)
        steps = np.where(found & ~np.isfinite(steps), 0.0, steps)  # first detection
        self._prev[found] = pos[found]
        self._last_seen[found] = self._batch
        self._batch += 1
        self._results = [
            (
                Detection(
                    x[k], y[k], dec[k, 2], dec[k, 3], dec[k, 4], steps[k], dec[k, 6]
                )
                if found[k]
                else None
            )
            for k in range(len(found))
        ]


def describe(card: dict) -> str:
    """
    Summarise the model for the experiment's METADATA.

    Args:
        card (dict): The model card.

    Returns:
        str: JSON with the model, the OpenCV version and threads, and the shake rule.
    """
    return json.dumps(
        {
            "model": card["name"],
            "sha256": card["sha256"],
            "opencv": cv2.__version__,
            "threads": cv2.getNumThreads(),
            "presence_min": PRESENCE_MIN,
            "shake_correction": {"min_rois": CM_MIN_ROIS, "gate_px": CM_GATE_PX},
        }
    )
