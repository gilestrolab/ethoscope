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
