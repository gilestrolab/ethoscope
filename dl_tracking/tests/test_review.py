"""Tests for the review queue and the review server's state."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dl_tracking.review import queue as Q
from dl_tracking.review import server as S


@pytest.fixture
def review_dir(packed: Path, tmp_path: Path) -> Path:
    """A queue with one never-detected tube and audits of every other label."""
    labels = pd.read_parquet(packed / "labels.parquet").assign(contrast=50.0)
    labels.loc[labels.roi_idx == 2, "status"] = "never_detected"
    q = Q.build(labels, None, max_tubes=10, n_confident=10, n_gapfill=10)
    out = tmp_path / "review"
    out.mkdir()
    q.to_parquet(out / "queue.parquet")
    return out


def test_queue_contents(review_dir: Path) -> None:
    """The never-detected tube is one group of its snapshots, with no proposal."""
    q = pd.read_parquet(review_dir / "queue.parquet")
    nd = q[q.kind == "never_detected"]
    assert nd.group.nunique() == 1 and len(nd) == 3 and nd.px.isna().all()
    audit = q[q.kind == "audit_confident"]
    assert len(audit) == 3 and (audit.px == 100).all()
    assert q.item_id.is_unique


def test_display_coordinates_round_trip() -> None:
    """ROI -> display -> ROI is the identity."""
    assert S.to_roi(*S.to_display(123.5, 31.0)) == pytest.approx((123.5, 31.0))


def test_render_keeps_a_small_dim_fly_visible() -> None:
    """A fly covering 0.2% of a dim, flat crop still stands out after the stretch."""
    frame = np.full((960, 1280), 20, np.uint8)
    frame[130:140, 200:210] = 5  # 100 px of a 76 x 576 crop
    item = pd.Series({"roi_x": 40, "roi_y": 100, "roi_w": 560, "roi_h": 60})
    img = S.render(frame, item)
    assert img.shape == ((60 + 2 * S.MARGIN) * S.SCALE, (560 + 2 * S.MARGIN) * S.SCALE)
    fly = img[(38 + S.MARGIN) * S.SCALE, (165 + S.MARGIN) * S.SCALE]
    background = np.median(img)
    assert background - fly > 150


def test_pages_answers_and_resume(review_dir: Path, packed: Path) -> None:
    """Answered crops leave the queue, are stored in ROI coordinates, and survive a restart."""
    review = S.Review(review_dir, packed)
    page = review.next_page()
    assert page["done"] == 0 and page["groups"][0]["kind"] == "never_detected"
    ids = [it["id"] for g in page["groups"] for it in g["items"]]
    answers = [
        {"id": ids[0], "state": "fly", "ix": 300.0, "iy": 70.0},
        {"id": ids[1], "state": "empty", "ix": None, "iy": None},
        {"id": ids[2], "state": "bogus", "ix": 0, "iy": 0},
        {"id": "no-such-crop", "state": "fly", "ix": 0, "iy": 0},
    ]
    review.record(answers)
    lines = [json.loads(line) for line in (review_dir / "answers.jsonl").open()]
    assert [a["state"] for a in lines] == ["fly", "empty"]
    assert (lines[0]["x"], lines[0]["y"]) == S.to_roi(300.0, 70.0)
    again = S.Review(review_dir, packed)
    assert again.next_page()["done"] == 2
    assert ids[0] not in [
        it["id"] for g in again.next_page()["groups"] for it in g["items"]
    ]


def test_audit_answer_records_the_correction(review_dir: Path, packed: Path) -> None:
    """Moving an audit ring stores how far the label was off."""
    review = S.Review(review_dir, packed)
    item = review.queue[review.queue.kind == "audit_confident"].iloc[0]
    ix, iy = S.to_display(item.px + 30, item.py + 40)
    review.record([{"id": item.item_id, "state": "fly", "ix": ix, "iy": iy}])
    rec = json.loads((review_dir / "answers.jsonl").read_text().splitlines()[-1])
    assert rec["moved_px"] == pytest.approx(50.0)


def test_model_items_ask_only_about_uncertain_crops() -> None:
    """Uncertain crops are queued in full; confident calls only as small audits."""
    rng = np.random.default_rng(0)
    n = 300
    scored = pd.DataFrame(
        {
            "run_id": [f"r{i % 7}" for i in range(n)],
            "roi_idx": np.arange(n) % 20 + 1,
            "sid": np.arange(n),
            "t": 0,
            "roi_x": 40,
            "roi_y": 100,
            "roi_w": 560,
            "roi_h": 60,
            "px": 100.0,
            "py": 30.0,
            "presence": rng.uniform(0, 1, n),
        }
    )
    q = Q.model_items(scored, n_unsure=10, n_conf=5, n_none=5)
    assert q.kind.value_counts().to_dict() == {
        "model_unsure": 10,
        "model_conf": 5,
        "model_none": 5,
    }
    assert q[q.kind == "model_none"].px.isna().all()  # no ring on confident-empty
    assert q[q.kind == "model_conf"].px.notna().all()
    assert q.item_id.is_unique and q.group.nunique() == 4  # blocks of 5


def test_ingest_answers_to_labels_and_audit(review_dir: Path, packed: Path) -> None:
    """Fly clicks become positives, 'no fly' negatives, unsure is dropped; audits scored."""
    from dl_tracking.review import ingest as I

    review = S.Review(review_dir, packed)
    nd = review.queue[review.queue.kind == "never_detected"].item_id.tolist()
    audit = review.queue[review.queue.kind == "audit_confident"].iloc[0]
    ix, iy = S.to_display(audit.px + 10, audit.py)  # moved 10 px: the label was wrong
    review.record(
        [
            {"id": nd[0], "state": "fly", "ix": 300.0, "iy": 70.0},
            {"id": nd[1], "state": "empty", "ix": None, "iy": None},
            {"id": nd[2], "state": "unsure", "ix": None, "iy": None},
            {"id": audit.item_id, "state": "fly", "ix": ix, "iy": iy},
        ]
    )
    answers = I.latest_answers(review_dir / "answers.jsonl")
    labels = I.human_labels(review.queue, answers)
    assert sorted(labels.status) == ["human_empty", "human_fly", "human_fly"]
    assert labels[labels.status == "human_empty"].x.isna().all()
    rep = I.audit_report(review.queue, answers)
    assert rep["audit_confident"]["wrong_rate"] == 1.0
    assert rep["never_detected"] == {
        "answered": 3,
        "unsure": 1,
        "fly": 1,
        "empty": 1,
        "wrong_rate": 0.5,
    }


def test_human_labels_override_and_add_negatives(
    review_dir: Path, packed: Path, tmp_path: Path
) -> None:
    """In training rows, a human answer replaces the automatic label for that crop."""
    from dl_tracking import train as T
    from dl_tracking.review import ingest as I

    review = S.Review(review_dir, packed)
    audit = review.queue[review.queue.kind == "audit_confident"].iloc[0]
    review.record([{"id": audit.item_id, "state": "empty", "ix": None, "iy": None}])
    labels = I.human_labels(
        review.queue, I.latest_answers(review_dir / "answers.jsonl")
    )
    labels.to_parquet(tmp_path / "human.parquet")
    runs = pd.DataFrame(
        {"machine_id": ["abc"], "run_dt": ["2020-01-01_00-00-00"], "split": ["train"]}
    )
    runs.to_parquet(tmp_path / "runs.parquet")
    # Reason: the synthetic snapshots are flat, so drop the canvas filter here.
    (packed / "canvas_std.parquet").unlink(missing_ok=True)
    rows = T.split_rows(packed, tmp_path / "runs.parquet", tmp_path / "human.parquet")
    same = rows[(rows.sid == audit.sid) & (rows.roi_idx == audit.roi_idx)]
    assert len(same) == 1 and not same.present.item()
    assert rows.present.sum() == len(rows) - 1


def test_propagate_dead_flies_and_empty_tubes() -> None:
    """Empty-at-every-time tubes stay empty; a still fly is interpolated between clicks."""
    from dl_tracking.review import ingest as I

    box = {"roi_x": 40, "roi_y": 100, "roi_w": 560, "roi_h": 60}
    pack = pd.DataFrame(
        [
            {
                "run_id": "r",
                "roi_idx": roi,
                "sid": s,
                "t": 1000 * s,
                "status": "never_detected",
                **box,
            }
            for roi in (1, 2)
            for s in range(10)
        ]
    )
    shown = [0, 3, 6, 9]
    queue = pd.DataFrame(
        [
            {
                "item_id": f"{roi}:{s}",
                "kind": "never_detected",
                "run_id": "r",
                "roi_idx": roi,
                "sid": s,
            }
            for roi in (1, 2)
            for s in shown
        ]
    )
    labels = pd.DataFrame(
        [
            {
                "run_id": "r",
                "roi_idx": 1,
                "sid": s,
                "t": 1000 * s,
                "present": False,
                "x": np.nan,
                "y": np.nan,
                **box,
            }
            for s in shown
        ]
        + [
            {
                "run_id": "r",
                "roi_idx": 2,
                "sid": s,
                "t": 1000 * s,
                "present": p,
                "x": x,
                "y": 30.0,
                **box,
            }
            for s, p, x in (
                (0, True, 100.0),
                (3, True, 106.0),
                (6, True, 300.0),
                (9, False, np.nan),
            )
        ]
    )
    new = I.propagate(labels, queue, pack)
    empty = new[new.roi_idx == 1]
    assert sorted(empty.sid) == [1, 2, 4, 5, 7, 8] and not empty.present.any()
    fly = new[new.roi_idx == 2]  # only between the two clicks 6 px apart
    assert sorted(fly.sid) == [1, 2] and fly.present.all()
    assert fly.sort_values("sid").x.tolist() == pytest.approx([102.0, 104.0])


def test_tube_model_items_show_whole_tubes_with_rings() -> None:
    """Round 3: whole tubes, four strips each, rings where the locator leans to a fly."""
    rows = []
    for tube in range(30):
        seen = tube < 20
        for s in range(10):
            p = 0.95 if (seen and s == 5) else (0.4 if seen else 0.05)
            rows.append(
                {
                    "run_id": f"r{tube % 6}",
                    "roi_idx": tube,
                    "sid": 100 * tube + s,
                    "t": 1000 * s,
                    "roi_x": 40,
                    "roi_y": 100,
                    "roi_w": 560,
                    "roi_h": 60,
                    "px": 200.0,
                    "py": 30.0,
                    "presence": p,
                }
            )
    q = Q.tube_model_items(pd.DataFrame(rows), n_seen=5, n_none=3)
    assert q.groupby("kind").group.nunique().to_dict() == {
        "tube_model_none": 3,
        "tube_model_seen": 5,
    }
    assert (q.groupby("group").size() == Q.N_TIMES).all()
    assert q[q.kind == "tube_model_none"].px.isna().all()
    assert q[q.kind == "tube_model_seen"].px.notna().all()  # 0.4 >= lower bound
