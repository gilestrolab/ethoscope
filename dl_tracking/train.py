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

import cv2
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, WeightedRandomSampler

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
    shape = b["shape"]

    def masked_l1(
        pred: torch.Tensor, target: torch.Tensor, mask: torch.Tensor
    ) -> torch.Tensor:
        err = (pred - target).abs().sum(dim=1) * mask
        return err.sum() / mask.sum().clamp(min=1)

    out = {
        "heat": focal_loss(maps[:, 0], b["heat"]),
        # Dense: every cell around the fly is trained to point at its centre.
        "offset": ((maps[:, 1:3] - b["off"]).abs().sum(dim=1) * b["offmask"]).sum()
        / b["offmask"].sum().clamp(min=1),
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
    has = len(e) > 0  # a set of human-verified empty tubes has no flies at all
    return {
        "err_median": float(np.median(e)) if has else float("nan"),
        "err_p95": float(np.percentile(e, 95)) if has else float("nan"),
        "detect_rate": float(np.mean(e <= 4)) if has else float("nan"),
        "presence_fly": float(pp.mean()) if len(pp) else float("nan"),
        "presence_empty": float(pn.mean()) if len(pn) else float("nan"),
        "false_presence": float(np.mean(pn > 0.5)) if len(pn) else float("nan"),
        "n_fly": int(len(e)),
        "n_empty": int(len(pn)),
    }


def split_rows(pack: Path, runs: Path, human: Path | None = None) -> pd.DataFrame:
    """
    Load the training rows with each run's split and ``no_ir`` flag.

    Human labels (:mod:`dl_tracking.review.ingest`), when given, replace any
    automatic label for the same snapshot and tube, and add human-verified empty
    tubes as negatives (``present`` False).

    Args:
        pack (Path): Pack directory.
        runs (Path): ``runs.parquet`` from :mod:`dl_tracking.select_runs`.
        human (Path | None): ``human_labels.parquet``, if any.

    Returns:
        pd.DataFrame: Rows of :func:`dataset.training_rows` (plus human rows) with
        ``split``, ``no_ir`` (False when the runs table has none) and ``present``.
    """
    std_path = pack / "canvas_std.parquet"
    canvas_std = pd.read_parquet(std_path) if std_path.exists() else None
    rows = D.training_rows(
        pd.read_parquet(pack / "labels.parquet"), canvas_std=canvas_std
    )
    rows["present"] = True
    if human is not None and human.exists():
        hl = pd.read_parquet(human)
        key = ["sid", "roi_idx"]
        rows = rows.merge(hl[key].assign(_h=1), on=key, how="left")
        rows = pd.concat(
            [rows[rows._h.isna()].drop(columns="_h"), hl], ignore_index=True
        )
        rows = rows.sort_values(key)
    table = pd.read_parquet(runs)
    table["run_id"] = table.machine_id + "_" + table.run_dt
    if "no_ir" not in table:
        table["no_ir"] = False
    rows = rows.merge(table[["run_id", "split", "no_ir"]], on="run_id")
    rows["present"] = rows.present.astype(bool)
    return rows


def _one_thread_per_worker(_worker_id: int) -> None:
    """
    Keep each data-loader worker to one thread.

    Reason: OpenCV and torch default to a thread per core in every worker; with a
    dozen workers per run the machine thrashed and an epoch took ten times longer.

    Args:
        _worker_id (int): Worker index (unused).
    """
    cv2.setNumThreads(1)
    torch.set_num_threads(1)


def loader(
    store: D.SnapshotStore,
    rows: pd.DataFrame,
    train: bool,
    args,
    max_snapshots: int | None = None,
) -> DataLoader:
    """
    Build a data loader over some rows.

    Args:
        store (D.SnapshotStore): Packed snapshots.
        rows (pd.DataFrame): Label rows.
        train (bool): Augment and shuffle (training) or not (evaluation, which still
            swaps windows so that presence is measured on fly-free canvases).
        args: Parsed command-line arguments.
        max_snapshots (int | None): Cap on snapshots, sampled reproducibly.

    Returns:
        DataLoader: The loader.
    """
    if max_snapshots is not None and rows.sid.nunique() > max_snapshots:
        keep = pd.Series(rows.sid.unique()).sample(max_snapshots, random_state=0)
        rows = rows[rows.sid.isin(keep)]
    ds = D.TubeDataset(store, rows, augment=train, p_swap=0.5)
    sampler = None
    weight = getattr(args, "human_weight", 1.0)
    if train and weight != 1.0:
        # Reason: human labels are <1% of training tubes but sit exactly where the
        # model fails (empty tubes, dead flies); draw their snapshots more often.
        human = set(rows.sid[rows.status.isin(["human_fly", "human_empty"])])
        w = np.where([sid in human for sid in ds.sids], weight, 1.0)
        sampler = WeightedRandomSampler(torch.as_tensor(w), len(ds), replacement=True)
    return DataLoader(
        ds,
        args.snapshots_per_batch,
        shuffle=train and sampler is None,
        sampler=sampler,
        drop_last=train,
        collate_fn=D.collate,
        num_workers=args.workers,
        persistent_workers=train and args.workers > 0,
        worker_init_fn=_one_thread_per_worker,
    )


def fit(
    net: torch.nn.Module, train_dl: DataLoader, val_dl: DataLoader, args, device: str
) -> None:
    """
    Train, validating after every epoch; keep ``last.pt`` and the best ``best.pt``.

    Args:
        net (torch.nn.Module): The network.
        train_dl (DataLoader): Training data.
        val_dl (DataLoader): Validation data (selects the checkpoint).
        args: Parsed command-line arguments.
        device (str): Torch device.
    """
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
    ap.add_argument(
        "--human",
        type=Path,
        default=Path("/mnt/cache/dl_tracking/review/human_labels.parquet"),
        help="human labels from review.ingest (used if the file exists)",
    )
    ap.add_argument(
        "--human-weight",
        type=float,
        default=5.0,
        help="how much more often snapshots with human labels are drawn",
    )
    ap.add_argument(
        "--include-flagged",
        action="store_true",
        help="also train on runs flagged no_ir (picamera2 tuning bug)",
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    args.out.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    rows = split_rows(args.pack, args.runs, args.human)
    store = D.SnapshotStore(args.pack)
    train = rows[(rows.split == "train") & (args.include_flagged | ~rows.no_ir)]
    # Reason: select checkpoints on unflagged validation runs in every variant, so
    # that runs trained with and without the flagged data are compared alike.
    val = rows[(rows.split == "val") & ~rows.no_ir]
    logging.info(
        "train %d snapshots / %d tubes (flagged %s), val %d snapshots",
        train.sid.nunique(),
        len(train),
        "included" if args.include_flagged else "excluded",
        val.sid.nunique(),
    )
    net = M.build(args.variant).to(device)
    fit(
        net,
        loader(store, train, True, args),
        loader(store, val, False, args, args.max_val_snapshots),
        args,
        device,
    )

    best = torch.load(args.out / "best.pt", map_location=device)
    net.load_state_dict(best["state_dict"])
    report = {"best_epoch": best["epoch"]}
    test = rows[rows.split == "test"]
    human = test.status.isin(["human_fly", "human_empty"])
    sets = {
        "test_unflagged": test[~test.no_ir & ~human],
        "test_flagged": test[test.no_ir & ~human],
        # Reason: the acceptance target for false detections is about real empty
        # tubes, which only the human review provides.
        "test_human": test[human],
    }
    for key, sub in sets.items():
        if len(sub):
            dl = loader(store, sub, False, args, args.max_val_snapshots)
            report[key] = evaluate(net, dl, device)
    (args.out / "final.json").write_text(json.dumps(report, indent=1))
    logging.info("final: %s", json.dumps(report))


if __name__ == "__main__":
    main()
