"""Export a trained locator to ONNX (opset 13) and check it against ``cv2.dnn``.

Usage::

    python -m dl_tracking.export --ckpt run/best.pt --out fly_locator.onnx
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import nn

from . import model as M
from .preprocess import CANVAS_H, CANVAS_W

OPSET = 13


def fold_batchnorm(net: nn.Module) -> nn.Module:
    """
    Return a copy of the network with every Conv+BatchNorm pair folded into a Conv.

    Args:
        net (nn.Module): A network built from :func:`dl_tracking.model.conv_bn`.

    Returns:
        nn.Module: The folded copy, in eval mode.
    """
    net = copy.deepcopy(net).eval()
    for mod in net.modules():
        if not isinstance(mod, nn.Sequential):
            continue
        for i in range(len(mod) - 1):
            conv, bn = mod[i], mod[i + 1]
            if not (isinstance(conv, nn.Conv2d) and isinstance(bn, nn.BatchNorm2d)):
                continue
            scale = bn.weight / torch.sqrt(bn.running_var + bn.eps)
            fused = nn.Conv2d(
                conv.in_channels,
                conv.out_channels,
                conv.kernel_size,
                conv.stride,
                conv.padding,
                conv.dilation,
                conv.groups,
                bias=True,
            )
            with torch.no_grad():
                fused.weight.copy_(conv.weight * scale[:, None, None, None])
                bias = conv.bias if conv.bias is not None else torch.zeros_like(bn.bias)
                fused.bias.copy_((bias - bn.running_mean) * scale + bn.bias)
            mod[i], mod[i + 1] = fused, nn.Identity()
    return net


def export(net: nn.Module, path: Path) -> Path:
    """
    Write the folded network to ONNX with a dynamic batch size and canvas width.

    Args:
        net (nn.Module): Trained network.
        path (Path): Output ``.onnx`` file.

    Returns:
        Path: ``path``.
    """
    folded = fold_batchnorm(net)
    dummy = torch.zeros(2, 1, CANVAS_H, CANVAS_W)
    torch.onnx.export(
        folded,
        dummy,
        str(path),
        opset_version=OPSET,
        dynamo=False,
        input_names=["input"],
        output_names=["maps", "presence"],
        dynamic_axes={
            "input": {0: "n", 3: "w"},
            "maps": {0: "n", 3: "wo"},
            "presence": {0: "n"},
        },
    )
    return path


def parity(net: nn.Module, path: Path, canvases: np.ndarray) -> dict:
    """
    Compare the PyTorch network with the exported file run through ``cv2.dnn``.

    Args:
        net (nn.Module): The network that was exported.
        path (Path): The ``.onnx`` file.
        canvases (np.ndarray): ``(n, 1, h, w)`` float32 normalised inputs.

    Returns:
        dict: ``max_abs_maps``, ``max_abs_presence``, ``argmax_agree`` (fraction of
        decisive canvases whose heatmap peak falls in the same cell) and
        ``n_decisive``. A canvas is decisive when its top two heatmap logits differ
        by more than ten times the largest numerical difference; below that the
        argmax is a coin toss that says nothing about the export.
    """
    with torch.no_grad():
        ref_maps, ref_pres = (t.numpy() for t in net.eval()(torch.from_numpy(canvases)))
    dnn = cv2.dnn.readNetFromONNX(str(path))
    dnn.setInput(canvases)
    maps, pres = dnn.forward(["maps", "presence"])
    n = len(canvases)
    err = float(np.abs(maps - ref_maps).max())
    ref_heat = ref_maps[:, 0].reshape(n, -1)
    top2 = np.sort(ref_heat, axis=1)[:, -2:]
    decisive = (top2[:, 1] - top2[:, 0]) > 10 * err
    agree = maps[:, 0].reshape(n, -1).argmax(1) == ref_heat.argmax(1)
    return {
        "max_abs_maps": err,
        "max_abs_presence": float(np.abs(pres - ref_pres).max()),
        "argmax_agree": (
            float(agree[decisive].mean()) if decisive.any() else float("nan")
        ),
        "n_decisive": int(decisive.sum()),
    }


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ckpt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    ckpt = torch.load(args.ckpt, map_location="cpu")
    net = M.build(ckpt["variant"])
    net.load_state_dict(ckpt["state_dict"])
    export(net, args.out)
    rng = np.random.default_rng(0)
    probe = rng.normal(size=(64, 1, CANVAS_H, CANVAS_W)).astype(np.float32)
    print(parity(net, args.out, probe))


if __name__ == "__main__":
    main()
