"""Write the reference the device tracker's parity test compares against.

One frame of the repository's 20-tube test video goes through the TRAINING
preprocessing (``dl_tracking.preprocess``) and the packaged ONNX model in
``cv2.dnn``; the frame, the ROI rectangles, the canvases, the network outputs and
the decoded positions are saved. ``test_deep_tube_tracker.py`` then checks that the
device copy (``ethoscope.trackers.deep_tube``) reproduces them, so a change on either
side that alters what the network sees shows up as a failing test.

Run from the repository root in the device venv (it builds the ROIs with the
device's own ROI builder):

    python -m dl_tracking.device_reference
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from dl_tracking import preprocess as P

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src/ethoscope/ethoscope"
VIDEO = PKG / "tests/static_files/videos/arena_10x2_sortTubes.mp4"
MODEL = PKG / "trackers/deep_tube/models/fly_locator_tiny_s2_v5.onnx"
OUT = PKG / "tests/static_files/deep_tube/reference_v5.npz"


def roi_rects(video: Path) -> np.ndarray:
    """
    Build the test video's ROIs as the device does.

    Args:
        video (Path): The 20-tube test video.

    Returns:
        np.ndarray: ``(n, 5)`` rows of idx, x, y, w, h.
    """
    from ethoscope.hardware.input.cameras import MovieVirtualCamera
    from ethoscope.roi_builders.file_based_roi_builder import FileBasedROIBuilder

    cam = MovieVirtualCamera(str(video))
    _, rois = FileBasedROIBuilder(template_name="sleep_monitor_20tube").build(cam)
    cam._close()
    return np.array([(r.idx, *r.rectangle) for r in rois], dtype=np.int64)


def grey_frame(video: Path, index: int) -> np.ndarray:
    """
    Read one frame as greyscale, as MovieVirtualCamera delivers it.

    Args:
        video (Path): The video.
        index (int): Frame number.

    Returns:
        np.ndarray: The frame, uint8.
    """
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"cannot read frame {index} of {video}")
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def main() -> None:
    """Write the reference file."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--frame", type=int, default=50)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    frame = grey_frame(VIDEO, args.frame)
    rects = roi_rects(VIDEO)
    origins = [P.canvas_origin(*map(int, r[1:])) for r in rects]
    canvases = P.canvases_from_frame(frame, origins)
    net = cv2.dnn.readNetFromONNX(str(MODEL))
    net.setInput(P.normalise(canvases))
    maps, presence = net.forward(["maps", "presence"])
    decoded = P.decode(maps, presence)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.out,
        frame=frame,
        rects=rects,
        canvases=canvases,
        maps=maps,
        presence=presence,
        decoded=decoded,
        opencv=np.array(cv2.__version__),
    )
    print(f"{args.out}: {args.out.stat().st_size / 1e3:.0f} kB, OpenCV {cv2.__version__}")


if __name__ == "__main__":
    main()
