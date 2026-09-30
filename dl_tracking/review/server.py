"""A one-page web app for reviewing tube crops. Standard library only.

Answers are appended to ``answers.jsonl`` (one line per crop, the last line for a
crop wins), so nothing is lost if the server stops, and reviewing resumes where
it left off. Every request must carry the token printed at start-up.

Usage::

    python -m dl_tracking.review.server --queue /mnt/cache/dl_tracking/review \\
        --pack /mnt/cache/dl_tracking/data/pack --port 8765
"""

from __future__ import annotations

import argparse
import json
import secrets
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import cv2
import numpy as np
import pandas as pd

from ..dataset import SnapshotStore

MARGIN = 8  # full-res px of context around the ROI
SCALE = 2  # display upscaling
MIN_RANGE = 20.0  # narrowest contrast stretch, grey levels
STRIPS_PER_PAGE = 10
PAGE = Path(__file__).with_name("page.html")


def render(frame: np.ndarray, item: pd.Series) -> np.ndarray:
    """
    Cut an item's ROI (with a margin), stretch its contrast and upscale it.

    The stretch uses the crop's own percentiles, so a fly in a dim tube is as
    visible as one in a bright tube. The low end is the 0.2nd percentile because a
    fly covers well under 1% of a crop, and the range never narrows below
    ``MIN_RANGE`` grey levels, so a flat crop is not blown up into noise or black.

    Args:
        frame (np.ndarray): Full-resolution greyscale snapshot.
        item (pd.Series): Queue row.

    Returns:
        np.ndarray: The display image (uint8).
    """
    x0, y0 = int(item.roi_x) - MARGIN, int(item.roi_y) - MARGIN
    h, w = frame.shape
    crop = frame[
        max(0, y0) : min(h, y0 + int(item.roi_h) + 2 * MARGIN),
        max(0, x0) : min(w, x0 + int(item.roi_w) + 2 * MARGIN),
    ].astype(np.float32)
    lo, hi = np.percentile(crop, (0.2, 99.5))
    if hi - lo < MIN_RANGE:
        mid = (hi + lo) / 2
        lo, hi = mid - MIN_RANGE / 2, mid + MIN_RANGE / 2
    crop = np.clip((crop - lo) * 255 / (hi - lo), 0, 255).astype(np.uint8)
    return cv2.resize(crop, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_CUBIC)


def to_display(x: float, y: float) -> tuple[float, float]:
    """ROI-relative full-res position -> display pixels."""
    return (x + MARGIN) * SCALE, (y + MARGIN) * SCALE


def to_roi(ix: float, iy: float) -> tuple[float, float]:
    """Display pixels -> ROI-relative full-res position."""
    return ix / SCALE - MARGIN, iy / SCALE - MARGIN


class Review:
    """The queue, the answers so far, and the pages still to serve."""

    def __init__(self, queue_dir: Path, pack: Path) -> None:
        """
        Load the queue and any earlier answers.

        Args:
            queue_dir (Path): Directory with ``queue.parquet``; answers go here too.
            pack (Path): Pack directory with the snapshots.
        """
        self.queue = pd.read_parquet(queue_dir / "queue.parquet").set_index(
            "item_id", drop=False
        )
        self.answers_path = queue_dir / "answers.jsonl"
        self.done: set[str] = set()
        if self.answers_path.exists():
            self.done = {
                json.loads(line)["item_id"] for line in self.answers_path.open()
            }
        self.store = SnapshotStore(pack)
        self.lock = threading.Lock()

    def next_page(self) -> dict:
        """
        Return the next groups with unanswered crops, about one page's worth.

        Returns:
            dict: ``done``, ``total`` and ``groups`` (each with its ``items``).
        """
        todo = self.queue[~self.queue.item_id.isin(self.done)]
        groups, n = [], 0
        for gid, g in todo.groupby("group", sort=False):
            if n and n + len(g) > STRIPS_PER_PAGE:
                break
            items = []
            for it in g.itertuples(index=False):
                has = not np.isnan(it.px)
                mx, my = to_display(it.px, it.py) if has else (None, None)
                items.append(
                    {"id": it.item_id, "mx": mx, "my": my, "t": f"{it.t / 3.6e6:.1f} h"}
                )
            groups.append({"group": gid, "kind": g.kind.iat[0], "items": items})
            n += len(g)
        return {"done": len(self.done), "total": len(self.queue), "groups": groups}

    def image(self, item_id: str) -> bytes:
        """
        Render one crop as PNG.

        Args:
            item_id (str): Queue item id.

        Returns:
            bytes: PNG data.
        """
        item = self.queue.loc[item_id]
        png = cv2.imencode(".png", render(self.store.frame(int(item.sid)), item))[1]
        return png.tobytes()

    def record(self, answers: list[dict]) -> int:
        """
        Append answers (display coordinates are converted back to the ROI's).

        Args:
            answers (list[dict]): ``{id, state, ix, iy}`` with ``state`` one of
                ``fly``, ``empty`` or ``unsure``.

        Returns:
            int: Number recorded.
        """
        now = time.time()
        with self.lock, self.answers_path.open("a") as fh:
            for a in answers:
                if a["id"] not in self.queue.index or a["state"] not in (
                    "fly",
                    "empty",
                    "unsure",
                ):
                    continue
                item = self.queue.loc[a["id"]]
                x, y = to_roi(a["ix"], a["iy"]) if a["state"] == "fly" else (None, None)
                moved = None
                if a["state"] == "fly" and not np.isnan(item.px):
                    moved = float(np.hypot(x - item.px, y - item.py))
                rec = {
                    "item_id": a["id"],
                    "kind": item.kind,
                    "state": a["state"],
                    "x": x,
                    "y": y,
                    "moved_px": moved,
                    "time": now,
                }
                fh.write(json.dumps(rec) + "\n")
                self.done.add(a["id"])
        return len(answers)


def make_handler(review: Review, token: str) -> type[BaseHTTPRequestHandler]:
    """
    Build the request handler bound to a review and its token.

    Args:
        review (Review): The review state.
        token (str): Required value of the ``k`` query parameter.

    Returns:
        type[BaseHTTPRequestHandler]: The handler class.
    """

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authorised(self) -> tuple[bool, str, dict]:
            url = urlparse(self.path)
            query = parse_qs(url.query)
            ok = secrets.compare_digest(query.get("k", [""])[0], token)
            if not ok:
                self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
            return ok, url.path, query

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            ok, path, _ = self._authorised()
            if not ok:
                return
            if path == "/":
                self._send(HTTPStatus.OK, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/next":
                self._send(
                    HTTPStatus.OK,
                    json.dumps(review.next_page()).encode(),
                    "application/json",
                )
            elif path.startswith("/img/"):
                item_id = unquote(path[5:])
                if item_id not in review.queue.index:
                    self._send(HTTPStatus.NOT_FOUND, b"no such crop", "text/plain")
                    return
                self._send(HTTPStatus.OK, review.image(item_id), "image/png")
            else:
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            ok, path, _ = self._authorised()
            if not ok:
                return
            if path != "/api/answers":
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            n = review.record(body)
            self._send(
                HTTPStatus.OK, json.dumps({"recorded": n}).encode(), "application/json"
            )

        def log_message(self, fmt: str, *args) -> None:  # quiet: no per-image lines
            return

    return Handler


def main() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--queue", type=Path, required=True)
    ap.add_argument("--pack", type=Path, required=True)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", default=None, help="reuse a token (default: a new one)")
    args = ap.parse_args()
    token = args.token or secrets.token_urlsafe(12)
    review = Review(args.queue, args.pack)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(review, token))
    print(
        f"serving {len(review.queue)} crops ({len(review.done)} done) on port {args.port}"
    )
    print(f"open: http://<this host>:{args.port}/?k={token}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
