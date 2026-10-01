"""The per-tube fly locator: a tiny fully-convolutional CenterNet-style network.

A stem convolution and two strided depthwise-separable blocks bring the canvas to
output stride 4 (8 x 72 cells for a 32 x 288 canvas); dilated depthwise blocks
then widen the receptive field to ~65 half-resolution pixels (~130 at full
resolution) so that the network sees the fly with the food, the tube ends and the
walls around it. The stride-4 map is cheap, so the context costs little.

Outputs, per cell: heatmap logit, sub-cell offset (x, y), log size (w, h, full
resolution) and (sin 2phi, cos 2phi); plus one presence logit per canvas from
global pooling. Only Conv, BatchNorm (folded at export), ReLU and global pooling
are used, all of which ``cv2.dnn`` runs.
"""

from __future__ import annotations

import torch
from torch import nn

# MACs per 32 x 288 canvas. The Pi 3 ran 2.1 M in 44.5 ms and 6.2 M in 96 ms for
# 20 tubes (untrained stand-ins, cv2.dnn, 4 threads); the budget is <= ~6 M.
VARIANTS = {
    "tiny": {"chans": (8, 16, 24, 24), "dilations": (1, 2, 4)},  # 2.9 M
    "mid": {"chans": (8, 16, 32, 32), "dilations": (1, 2, 4)},  # 3.9 M
    "small": {"chans": (12, 24, 40, 40), "dilations": (1, 2, 4)},  # 6.1 M
    # Cheaper context for the Pi 3, where dilated depthwise convolutions are slow:
    "tiny_k5": {"chans": (8, 16, 24, 24), "dilations": (1, 1, 1), "ctx_kernel": 5},
    "tiny_s2": {"chans": (8, 16, 24, 24), "dilations": (1, 2, 4), "stem_stride": 2},
    "tiny_d24": {"chans": (8, 16, 24, 24), "dilations": (2, 4)},  # one block fewer
    "tiny_s2k5": {
        "chans": (8, 16, 24, 24),
        "dilations": (1, 1, 1),
        "ctx_kernel": 5,
        "stem_stride": 2,
    },
}
N_MAPS = 7


def conv_bn(
    cin: int, cout: int, k: int, stride: int = 1, dilation: int = 1, groups: int = 1
) -> nn.Sequential:
    """
    Convolution, batch norm and ReLU.

    Args:
        cin (int): Input channels.
        cout (int): Output channels.
        k (int): Kernel size.
        stride (int): Stride.
        dilation (int): Dilation.
        groups (int): Groups (``cin`` for depthwise).

    Returns:
        nn.Sequential: The three layers.
    """
    pad = dilation * (k // 2)
    return nn.Sequential(
        nn.Conv2d(cin, cout, k, stride, pad, dilation, groups, bias=False),
        nn.BatchNorm2d(cout),
        nn.ReLU(inplace=True),
    )


def separable(
    cin: int, cout: int, stride: int = 1, dilation: int = 1, k: int = 3
) -> nn.Sequential:
    """
    Depthwise k x k followed by pointwise 1x1, each with batch norm and ReLU.

    Args:
        cin (int): Input channels.
        cout (int): Output channels.
        stride (int): Depthwise stride.
        dilation (int): Depthwise dilation.
        k (int): Depthwise kernel size.

    Returns:
        nn.Sequential: The block.
    """
    return nn.Sequential(
        conv_bn(cin, cin, k, stride, dilation, cin), conv_bn(cin, cout, 1)
    )


class FlyLocator(nn.Module):
    """Heatmap, offset, size, angle and presence for one fly per canvas."""

    def __init__(
        self,
        chans: tuple[int, int, int, int] = (8, 16, 32, 32),
        dilations: tuple[int, ...] = (1, 2, 4),
        ctx_kernel: int = 3,
        stem_stride: int = 1,
    ) -> None:
        """
        Build the network.

        Args:
            chans (tuple[int, int, int, int]): Channels of the stem, the two
                downsampling blocks, and the context blocks.
            dilations (tuple[int, ...]): One context block per dilation.
            ctx_kernel (int): Depthwise kernel of the context blocks; 5 with no
                dilation buys context without dilated convolutions, which cv2.dnn
                runs slowly on a Pi 3 (~20-27% of the forward pass).
            stem_stride (int): 2 moves the first downsampling into the stem, the
                most expensive layer at full canvas resolution; the output stride
                stays 4 because the second block then keeps stride 1.
        """
        super().__init__()
        c0, c1, c2, c3 = chans
        second = 1 if stem_stride == 2 else 2
        layers = [
            conv_bn(1, c0, 3, stem_stride),
            separable(c0, c1, 2),
            separable(c1, c2, second),
        ]
        cin = c2
        for d in dilations:
            layers.append(separable(cin, c3, 1, d, ctx_kernel))
            cin = c3
        self.body = nn.Sequential(*layers)
        self.maps = nn.Conv2d(c3, N_MAPS, 1)
        self.presence = nn.Conv2d(2 * c3, 1, 1)
        # Reason: CenterNet's prior; a heatmap that starts near 0 everywhere keeps the
        # focal loss from being swamped by easy negatives in the first steps.
        nn.init.constant_(self.maps.bias, 0.0)
        with torch.no_grad():
            self.maps.bias[0] = -4.6

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Run the network.

        Args:
            x (torch.Tensor): ``(n, 1, h, w)`` normalised canvases.

        Returns:
            tuple[torch.Tensor, torch.Tensor]: maps ``(n, 7, h/4, w/4)`` and
            presence logits ``(n, 1)``.
        """
        f = self.body(x)
        pooled = torch.cat(
            [
                torch.amax(f, dim=(2, 3), keepdim=True),
                torch.mean(f, dim=(2, 3), keepdim=True),
            ],
            dim=1,
        )
        return self.maps(f), self.presence(pooled).flatten(1)


def build(variant: str) -> FlyLocator:
    """
    Build a named variant.

    Args:
        variant (str): A key of :data:`VARIANTS`.

    Returns:
        FlyLocator: The untrained network.
    """
    return FlyLocator(**VARIANTS[variant])


def count_macs(model: nn.Module, h: int, w: int) -> int:
    """
    Count the multiply-accumulates of one canvas through every convolution.

    Args:
        model (nn.Module): The network.
        h (int): Canvas height.
        w (int): Canvas width.

    Returns:
        int: MACs per canvas.
    """
    total = 0

    def hook(mod: nn.Conv2d, _inp, out: torch.Tensor) -> None:
        nonlocal total
        k = mod.kernel_size[0] * mod.kernel_size[1]
        total += out.numel() * (mod.in_channels // mod.groups) * k

    handles = [
        m.register_forward_hook(hook)
        for m in model.modules()
        if isinstance(m, nn.Conv2d)
    ]
    was_training = model.training
    model.eval()
    with torch.no_grad():
        model(torch.zeros(1, 1, h, w))
    model.train(was_training)
    for handle in handles:
        handle.remove()
    return total


def receptive_field(model: FlyLocator) -> int:
    """
    Compute the receptive field of the output cells, in canvas pixels.

    Args:
        model (FlyLocator): The network.

    Returns:
        int: Receptive field width.
    """
    rf, jump = 1, 1
    for m in model.body.modules():
        if isinstance(m, nn.Conv2d):
            k = m.dilation[0] * (m.kernel_size[0] - 1) + 1
            rf += (k - 1) * jump
            jump *= m.stride[0]
    return rf
