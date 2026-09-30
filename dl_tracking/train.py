"""Train a fly locator on packed snapshots.

Usage::

    python -m dl_tracking.train --pack /mnt/cache/dl_tracking/data/pack \\
        --runs /mnt/cache/dl_tracking/runs.parquet --variant tiny --out runs/tiny_v0
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

from . import dataset as D
from . import model as M
from . import preprocess as P

LOSS_WEIGHTS = {"heat": 1.0, "offset": 1.0, "size": 0.1, "angle": 0.1, "presence": 0.5}


def focal_loss(logits: torch.Tensor, heat: torch.Tensor) -> torch.Tensor:
    """
    CenterNet's penalty-reduced focal loss, normalised by the number of flies.

    Args:
        logits (torch.Tensor): ``(n, h, w)`` heatmap logits.
        heat (torch.Tensor): ``(n, h, w)`` Gaussian targets (1 at each fly's cell).

    Returns:
        torch.Tensor: Scalar loss.
    """
    p = torch.sigmoid(logits).clamp(1e-4, 1 - 1e-4)
    pos = heat.eq(1).float()
    pos_loss = -(torch.log(p) * (1 - p) ** 2 * pos).sum()
    neg_loss = -(torch.log(1 - p) * p**2 * (1 - heat) ** 4 * (1 - pos)).sum()
    return (pos_loss + neg_loss) / pos.sum().clamp(min=1)


def losses(
    maps: torch.Tensor, presence: torch.Tensor, b: dict
) -> dict[str, torch.Tensor]:
    """
    Compute every loss term for one batch.

    Args:
        maps (torch.Tensor): ``(n, 7, h, w)`` network maps.
        presence (torch.Tensor): ``(n, 1)`` presence logits.
        b (dict): Batch from :func:`dataset.collate`.

    Returns:
        dict[str, torch.Tensor]: Loss terms, plus their weighted ``total``.
    """
    n = maps.shape[0]
    at = maps[torch.arange(n), :, b["cell"][:, 0], b["cell"][:, 1]]  # (n, 7)
    pos, shape = b["pos"], b["shape"]

    def masked_l1(
        pred: torch.Tensor, target: torch.Tensor, mask: torch.Tensor
    ) -> torch.Tensor:
        err = (pred - target).abs().sum(dim=1) * mask
        return err.sum() / mask.sum().clamp(min=1)

    out = {
        "heat": focal_loss(maps[:, 0], b["heat"]),
        "offset": masked_l1(at[:, 1:3], b["reg"][:, 0:2], pos),
        "size": masked_l1(at[:, 3:5], b["reg"][:, 2:4], shape),
        "angle": masked_l1(at[:, 5:7], b["reg"][:, 4:6], shape),
        "presence": F.binary_cross_entropy_with_logits(presence[:, 0], b["present"]),
    }
    out["total"] = sum(LOSS_WEIGHTS[k] * v for k, v in out.items())
    return out


def evaluate(net: torch.nn.Module, loader: DataLoader, device: str) -> dict[str, float]:
    """
    Measure position error and presence on a validation loader.

    Args:
        net (torch.nn.Module): The network.
        loader (DataLoader): Validation data (with swaps, so negatives exist).
        device (str): Torch device.

    Returns:
        dict[str, float]: Median and p95 position error (full-res px) on flies,
        detection rate (error <= 4 px), mean presence probability on flies and on
        fly-free canvases, and the rate of presence > 0.5 on fly-free canvases.
    """
    net.eval()
    errs, pres_pos, pres_neg = [], [], []
    with torch.no_grad():
        for b in loader:
            maps, presence = net(b["x"].to(device))
            dec = P.decode(maps.float().cpu().numpy(), presence.float().cpu().numpy())
            present = b["present"].numpy() > 0
            cell = b["cell"].numpy()
            reg = b["reg"].numpy()
            u_true = P.STRIDE * (cell[:, 1] + reg[:, 0]) - 0.5
            v_true = P.STRIDE * (cell[:, 0] + reg[:, 1]) - 0.5
            # Reason: canvas pixels are half-resolution, so errors double at full res.
            err = 2 * np.hypot(dec[:, 0] - u_true, dec[:, 1] - v_true)
            errs.append(err[present])
            pres_pos.append(dec[present, 6])
            pres_neg.append(dec[~present, 6])
    net.train()
    e, pp, pn = (np.concatenate(x) for x in (errs, pres_pos, pres_neg))
    return {
        "err_median": float(np.median(e)),
        "err_p95": float(np.percentile(e, 95)),
        "detect_rate": float(np.mean(e <= 4)),
        "presence_fly": float(pp.mean()) if len(pp) else float("nan"),
        "presence_empty": float(pn.mean()) if len(pn) else float("nan"),
        "false_presence": float(np.mean(pn > 0.5)) if len(pn) else float("nan"),
        "n_fly": int(len(e)),
        "n_empty": int(len(pn)),
    }


def split_rows(
    pack: Path, runs: Path, exclude_flag: str | None = "no_ir"
) -> dict[str, pd.DataFrame]:
    """
    Load the training rows and split them by the runs table.

    Args:
        pack (Path): Pack directory.
        runs (Path): ``runs.parquet`` from :mod:`dl_tracking.select_runs`.
        exclude_flag (str | None): Boolean column of ``runs`` whose True runs are
            left out (for example the runs recorded without IR), if present.

    Returns:
        dict[str, pd.DataFrame]: Rows per split.
    """
    rows = D.training_rows(pd.read_parquet(pack / "labels.parquet"))
    table = pd.read_parquet(runs)
    table["run_id"] = table.machine_id + "_" + table.run_dt
    if exclude_flag and exclude_flag in table:
        table = table[~table[exclude_flag].astype(bool)]
    rows = rows.merge(table[["run_id", "split"]], on="run_id")
    return dict(tuple(rows.groupby("split")))


def main() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pack", type=Path, required=True)
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--variant", default="tiny", choices=list(M.VARIANTS))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--snapshots-per-batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--max-val-snapshots", type=int, default=3000)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    args.out.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    splits = split_rows(args.pack, args.runs)
    store = D.SnapshotStore(args.pack)
    train_ds = D.TubeDataset(store, splits["train"], augment=True)
    val_rows = splits["val"]
    keep = pd.Series(val_rows.sid.unique()).sample(
        min(args.max_val_snapshots, val_rows.sid.nunique()), random_state=0
    )
    val_ds = D.TubeDataset(
        store, val_rows[val_rows.sid.isin(keep)], augment=False, p_swap=0.5
    )
    logging.info(
        "train %d snapshots / %d tubes, val %d snapshots",
        len(train_ds),
        len(splits["train"]),
        len(val_ds),
    )
    kw = {
        "collate_fn": D.collate,
        "num_workers": args.workers,
        "persistent_workers": True,
    }
    train_dl = DataLoader(
        train_ds, args.snapshots_per_batch, shuffle=True, drop_last=True, **kw
    )
    val_dl = DataLoader(val_ds, args.snapshots_per_batch, shuffle=False, **kw)

    net = M.build(args.variant).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, args.lr, total_steps=args.epochs * len(train_dl), pct_start=0.1
    )
    best = float("inf")
    for epoch in range(args.epochs):
        t0, sums, n = time.time(), {}, 0
        for b in train_dl:
            b = {k: v.to(device, non_blocking=True) for k, v in b.items()}
            maps, presence = net(b["x"])
            terms = losses(maps, presence, b)
            opt.zero_grad(set_to_none=True)
            terms["total"].backward()
            opt.step()
            sched.step()
            for k, v in terms.items():
                sums[k] = sums.get(k, 0.0) + float(v)
            n += 1
        metrics = evaluate(net, val_dl, device)
        rec = {
            "epoch": epoch,
            "sec": round(time.time() - t0),
            **{f"loss_{k}": v / n for k, v in sums.items()},
            **metrics,
        }
        logging.info(json.dumps(rec))
        with (args.out / "log.jsonl").open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        # Reason: rank by detection first (the failure we are fixing), then precision.
        score = (1 - metrics["detect_rate"]) * 100 + metrics["err_median"]
        ckpt = {
            "variant": args.variant,
            "state_dict": net.state_dict(),
            "epoch": epoch,
            "metrics": metrics,
        }
        torch.save(ckpt, args.out / "last.pt")
        if score < best:
            best = score
            torch.save(ckpt, args.out / "best.pt")


if __name__ == "__main__":
    main()
