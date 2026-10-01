"""Soak test of the locator's device path on a Pi: hours of frames, logged every 10 s.

Run next to ``preprocess.py``, the ``.onnx`` model, ``frame.png`` and ``rois.json``::

    python3 pi_soak.py fly_locator_tiny_s2_v3.onnx --minutes 240 --threads 4 \\
        --out soak.csv [--camera]

Without ``--camera`` every frame is the stored ``frame.png``; with it, frames come
from picamera2 at 1280x960 (the Y plane of YUV420, as the device grabs them), so
capture time is included. Every 10 s one CSV row records the frames processed,
median / p95 / max ms per frame, CPU frequency, temperature and
``vcgencmd get_throttled``, so slow episodes can be attributed to heat, frequency
scaling or contention.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess  # nosec B404 - fixed command, no user input
import time
from pathlib import Path

import cv2
import numpy as np
import preprocess as P  # copied next to this file; numpy + OpenCV only

LOG_EVERY_S = 10.0


def sysfs(path: str) -> str:
    """Read a sysfs value, or '' if unavailable."""
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def throttled() -> str:
    """``vcgencmd get_throttled`` as hex, or ''."""
    try:
        out = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True,  # nosec
            text=True,
            timeout=5,
            check=False,
        ).stdout
        return out.strip().split("=")[-1]
    except (OSError, subprocess.TimeoutExpired):
        return ""


def frames(use_camera: bool, still: np.ndarray):
    """Yield greyscale 1280x960 frames, from picamera2 or the stored frame."""
    if not use_camera:
        while True:
            yield still
    from picamera2 import Picamera2  # only on the device

    cam = Picamera2()
    cam.configure(
        cam.create_video_configuration(main={"size": (1280, 960), "format": "YUV420"})
    )
    cam.start()
    try:
        while True:
            yield cam.capture_array("main")[:960, :1280]  # the Y plane
    finally:
        cam.stop()


def main() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model")
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--camera", action="store_true")
    ap.add_argument("--out", default="soak.csv")
    args = ap.parse_args()
    cv2.setNumThreads(args.threads)
    here = Path(__file__).parent
    still = cv2.imread(str(here / "frame.png"), cv2.IMREAD_GRAYSCALE)
    origins = [
        P.canvas_origin(*r[1:]) for r in json.loads((here / "rois.json").read_text())
    ]
    net = cv2.dnn.readNetFromONNX(args.model)
    end = time.time() + 60 * args.minutes
    fields = [
        "time",
        "frames",
        "median_ms",
        "p95_ms",
        "max_ms",
        "cpu_mhz",
        "temp_c",
        "throttled",
    ]
    with open(args.out, "w", newline="") as fh:
        log = csv.DictWriter(fh, fields)
        log.writeheader()
        times, next_log = [], time.time() + LOG_EVERY_S
        source = frames(args.camera, still)
        while time.time() < end:
            t0 = time.perf_counter()
            frame = next(source)
            net.setInput(P.normalise(P.canvases_from_frame(frame, origins)))
            maps, pres = net.forward(["maps", "presence"])
            P.decode(maps, pres)
            times.append(1000 * (time.perf_counter() - t0))
            if time.time() >= next_log:
                freq, temp = sysfs(
                    "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"
                ), sysfs("/sys/class/thermal/thermal_zone0/temp")
                log.writerow(
                    {
                        "time": time.strftime("%H:%M:%S"),
                        "frames": len(times),
                        "median_ms": round(float(np.median(times)), 1),
                        "p95_ms": round(float(np.percentile(times, 95)), 1),
                        "max_ms": round(max(times), 1),
                        "cpu_mhz": int(freq) // 1000 if freq.isdigit() else "",
                        "temp_c": int(temp) / 1000 if temp.isdigit() else "",
                        "throttled": throttled(),
                    }
                )
                fh.flush()
                times, next_log = [], next_log + LOG_EVERY_S
    print(f"done: {args.out}")


if __name__ == "__main__":
    main()
