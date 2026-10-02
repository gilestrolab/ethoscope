"""Time the locator's full device path on a Pi (numpy + OpenCV only, no torch).

Run from a folder holding this file, ``preprocess.py``, the ``.onnx`` model and
``frame.png`` / ``rois.json`` (one real snapshot and its ROI map)::

    python3 pi_bench.py fly_locator.onnx --threads 4 --repeats 50

Per frame it does what the tracker will do: area-downsample the frame once, cut
every tube's canvas, normalise them in one vectorised step, run one batched
``cv2.dnn`` forward pass, and decode. It reports the median time of each stage,
the frame rate this leaves for tracking, and the CPU temperature and throttle
state before and after.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import preprocess as P  # copied next to this file; numpy + OpenCV only


def read(path: str) -> str:
    """Read a sysfs value, or return '?' when it is not available."""
    try:
        return Path(path).read_text().strip()
    except OSError:
        return "?"


def temp_c() -> str:
    """CPU temperature in degrees C, or '?'."""
    raw = read("/sys/class/thermal/thermal_zone0/temp")
    return f"{int(raw) / 1000:.1f}" if raw.isdigit() else raw


def main() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--repeats", type=int, default=50)
    args = ap.parse_args()
    cv2.setNumThreads(args.threads)
    here = Path(__file__).parent
    frame = cv2.imread(str(here / "frame.png"), cv2.IMREAD_GRAYSCALE)
    rois = json.loads((here / "rois.json").read_text())
    origins = [P.canvas_origin(*r[1:]) for r in rois]
    net = cv2.dnn.readNetFromONNX(args.model)
    temp0 = temp_c()

    stages = {"downsample+cut": [], "normalise": [], "forward": [], "decode": []}
    for i in range(args.repeats + 3):
        t0 = time.perf_counter()
        canv = P.canvases_from_frame(frame, origins)
        t1 = time.perf_counter()
        x = P.normalise(canv)
        t2 = time.perf_counter()
        net.setInput(x)
        maps, pres = net.forward(["maps", "presence"])
        t3 = time.perf_counter()
        P.decode(maps, pres)
        t4 = time.perf_counter()
        if i >= 3:  # warm-up
            for k, dt in zip(stages, (t1 - t0, t2 - t1, t3 - t2, t4 - t3), strict=True):
                stages[k].append(1000 * dt)

    total = sum(np.median(v) for v in stages.values())
    print(
        f"OpenCV {cv2.__version__}, {args.threads} threads, {len(rois)} tubes, "
        f"model {Path(args.model).name}"
    )
    for k, v in stages.items():
        print(f"  {k:15s} {np.median(v):7.2f} ms (p95 {np.percentile(v, 95):6.2f})")
    print(
        f"  total           {total:7.2f} ms per frame -> at most {1000 / total:5.1f} fps"
    )
    print(
        f"CPU temp {temp0} -> {temp_c()} C; "
        f"throttled {read('/sys/devices/platform/soc/soc:firmware/get_throttled')}"
    )


if __name__ == "__main__":
    main()
