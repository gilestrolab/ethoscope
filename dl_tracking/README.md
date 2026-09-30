# dl_tracking: a learned per-tube fly locator

Training and evaluation code for a small CNN that finds the one fly in each tube of
an ethoscope, meant to replace or complement AdaptiveBGModel. It is not part of the
device or node packages and is not installed on devices. The plan, decisions and
findings are in `tasks/todo.dl-tracking.md`.

Derived data, the virtual environment and checkpoints live under
`/mnt/cache/dl_tracking/` on turing, never in the repository.

## Environment

```bash
uv venv --python 3.13 /mnt/cache/dl_tracking/venv
VIRTUAL_ENV=/mnt/cache/dl_tracking/venv uv pip install torch==2.14.1 onnx==1.23.1 \
    onnxruntime==1.30.0 opencv-python-headless==4.14.0.94 numpy==2.5.3 \
    pandas==3.0.6 pyarrow==25.0.1 pytest==9.1.1
```

Python 3.13 and OpenCV 4.14 match the devices, so the `cv2.dnn` parity check in
`export.py` runs the same inference code as a Pi. Run everything from the repository
root, as `python -m dl_tracking.<module>`.

## Pipeline

| Step | Module | Output |
|---|---|---|
| Census of every DB (read-only) | `census` | `census.parquet` |
| Choose runs, split by machine | `select_runs` | `runs.parquet` |
| Copy each DB to NVMe, label its snapshots | `extract` | `data/snaps/`, `data/labels/` |
| Pack snapshots into one store | `dataset.pack` | `data/pack/` |
| Human review of what needs a human | `review.queue`, `review.server` | `review/answers.jsonl` |
| Train | `train` | `runs/<name>/best.pt` |
| Export to ONNX, check against `cv2.dnn` | `export` | `.onnx` |
| Run on a video | `run_video` | per-frame parquet |
| Compare with AdaptiveBGModel and pixel truth | `evaluate` | JSON report |

`qa` renders contact sheets of labelled crops for checking by eye.

## Labels in one paragraph

A snapshot's tube gets a **confident** label when AdaptiveBGModel detected the fly
in that very frame, at a plausible size, with no hop to a second blob within 10 s;
and a **gapfill** label when the fly was lost and found again within 3 px, so it was
there all along (these are the still flies background subtraction misses). A gap
fill must also sit on a dark spot, relative to the same fly's confident labels. A
tube the tracker never saw is not a negative: an empty tube and a fly dead from the
start look the same to it, so those go to human review. Negatives for the presence
head come from pasting, into a tube, a window of another snapshot of the same run
where the fly was elsewhere; positives get the same pasted windows elsewhere, so a
seam carries no information.

## Geometry

Every tube is seen at half resolution on a fixed 32 x 288 canvas centred on its ROI
(`preprocess.py`), so a fly has the same pixel size everywhere. The whole frame is
downsampled once and the canvases are cut from it, in training and on the device
alike. The network outputs a heatmap at stride 4 with sub-cell offsets, blob size,
orientation, and a presence logit; the position is the heatmap's argmax.

## Reviewing

```bash
python -m dl_tracking.review.queue --pack /mnt/cache/dl_tracking/data/pack \
    --runs /mnt/cache/dl_tracking/runs.parquet --out /mnt/cache/dl_tracking/review
python -m dl_tracking.review.server --queue /mnt/cache/dl_tracking/review \
    --pack /mnt/cache/dl_tracking/data/pack --port 8765
```

The server prints a URL with a token. Every strip should end up showing the truth: a
ring where the fly is, no ring where there is none. Click to place the ring, click the
ring to remove it, `?` if unsure, Enter for the next page. Answers are appended as you
go, so the page can be closed and reopened at any time.

## Tests

```bash
/mnt/cache/dl_tracking/venv/bin/python -m pytest dl_tracking/tests -q
```
