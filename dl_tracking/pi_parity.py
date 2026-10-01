"""Check a locator ONNX against PyTorch's outputs with this device's cv2.dnn.

The fleet runs several OpenCV versions (4.7 to 4.14 seen in October 2026), so
the exported model has to give the same answer on each. ``make_reference`` (run
where torch is installed) stores fixed inputs and the PyTorch outputs; on the
device, with numpy and OpenCV only::

    python3 pi_parity.py fly_locator.onnx parity_reference.npz
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def make_reference(net, path: Path, n: int = 40, seed: int = 0) -> Path:
    """
    Store random normalised canvases and the network's outputs for them.

    Args:
        net: A torch FlyLocator in eval mode.
        path (Path): Output ``.npz``.
        n (int): Number of canvases.
        seed (int): Random seed.

    Returns:
        Path: ``path``.
    """
    import torch

    from .preprocess import CANVAS_H, CANVAS_W

    x = (
        np.random.default_rng(seed)
        .normal(size=(n, 1, CANVAS_H, CANVAS_W))
        .astype(np.float32)
    )
    with torch.no_grad():
        maps, pres = (t.numpy() for t in net.eval()(torch.from_numpy(x)))
    np.savez_compressed(path, x=x, maps=maps, presence=pres)
    return path


def main() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model")
    ap.add_argument("reference")
    args = ap.parse_args()
    ref = np.load(args.reference)
    net = cv2.dnn.readNetFromONNX(args.model)
    net.setInput(ref["x"])
    maps, pres = net.forward(["maps", "presence"])
    n = len(ref["x"])
    agree = maps[:, 0].reshape(n, -1).argmax(1) == ref["maps"][:, 0].reshape(
        n, -1
    ).argmax(1)
    print(
        f"OpenCV {cv2.__version__}: max |d| maps {np.abs(maps - ref['maps']).max():.2e}, "
        f"presence {np.abs(pres - ref['presence']).max():.2e}, "
        f"heatmap argmax agreement {agree.mean():.3f} over {n} canvases"
    )


if __name__ == "__main__":
    main()
