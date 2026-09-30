# Learned per-tube fly locator (`dl-tracking`)

Date: 2026-09-30
Status: **Approved 2026-09-30.** Phase 0 done; Phase 1 running.
Origin: brief from the ethoscopy session on jenner (ethoscopy-36), agreed with Giorgio.
Background numbers: `turing:/mnt/cache/claude_motion_calibration/README.md`.

## Goal

A small CNN that finds the one fly in each tube crop, runs in real time on a Pi 3, and
holds up across lighting setups. It replaces or complements AdaptiveBGModel, which:

- never detects a fly that is motionless from the first frame, because the background is
  seeded with the fly in it (5 dead flies in `alice_012`: <2% of frames detected);
- slowly loses flies that sit still, and those lost frames get scored as immobile;
- hops between the fly and a second blob in some tubes (5–31 px jumps);
- makes still flies cross the movement threshold in 8–35% of 10-s windows, because
  `xy_dist` carries +1 px (`adaptive_bg_tracker.py:586`, `(1 + Δpx) / w_roi`), so the
  threshold of 1.0 corresponds to only ~0.52 px of true motion.

The new tracker is opt-in. AdaptiveBGModel stays the default and is not modified.

## What the data looks like (sampled 2026-09-30)

- **Sources.** `/mnt/data/results` holds 21,372 DBs (9.1 TB). The archive
  (`/mnt/archive/Archive/ethoscope_results/results`, 21,840 DBs) contains every one of
  them (same machine_id + date + file name) plus 468 more, mostly from 2022. So
  `/mnt/data/results` is the working source and the archive adds only those 468.
- **Snapshots.** 238 of 291 sampled DBs have them (median 1,155 per DB). All are
  1280×960 and **raw**: no overlays (the monitor passes the frame to `flush()` before
  the drawer runs, and old 3-channel snapshots have identical channels). Written at
  **JPEG quality 50** (`io/helpers.py:227`). That is much lossier than a live frame, so
  the domain gap matters.
- **Layouts.** Tubes are horizontal in every sampled DB. In the 20-tube layouts
  (~95% of sampled DBs) the ROI box is 540–570 × 50–70 px. In the 10-tube layouts it is
  ~1110 × 50–80 px. ROI sizes therefore vary by ±10% between devices.
- **Appearance.** Brightness, contrast and vignetting vary a lot by era; some 2025
  night frames are very dark and flat. Food plugs and residue make dark smudges at the
  tube ends that look like flies. These are the main hard negatives.
- **Existing labels.** 52 flyscorer CSVs (2021) are present; 202 machine folders in
  `/mnt/data/videos`.

## Design

This follows the brief, with the changes marked **(change)**.

**Model.** A tiny fully-convolutional CenterNet-style network, one forward pass per
tube, all tubes batched together.
- Input: the ROI crop at a **fixed 0.5× scale, padded to a fixed canvas** (32×288 for
  20-tube layouts, 32×576 for 10-tube ones), rather than resized to fit.
  **(change)** Resizing to fit would give the fly a different pixel size in every tube
  and every layout. Padding costs ~12% more compute than the 32×256 benchmark
  (≈50 ms per 20 tubes on the Pi 3).
- Contrast: a per-crop robust normalisation (median / percentile range), done as one
  vectorised step over the stacked batch. The whole frame is downscaled once per frame,
  not per tube.
- Heads at stride 2 (a 16×144 map): centre heatmap, sub-pixel offset, size (w, h),
  orientation (sin 2φ, cos 2φ), and a presence logit from global pooling. The output is
  the heatmap argmax, with no NMS, since there is exactly one fly per tube.
- Two variants to compare: tiny (8-16-32-32, ~2 M MACs per tube) and small
  (16-32-64-64, ~6 M). Prefer tiny if its accuracy holds.
- Single-frame input on purpose. The training data are isolated snapshots five minutes
  apart, and a single-frame model can learn from all ~20k DBs, whereas temporal input
  would restrict training to the 202 video folders. Temporal logic (such as preferring
  the peak near the last position) belongs on the device side (see Phase 6).

**Output.** The device schema is unchanged (x, y, w, h, phi, xy_dist_log10x1000,
is_inferred), so ethoscopy and rethomics work as before. Motion is judged separately
from position, by pixel change in a small crop around the detected fly (the validated
`pixel_motion.py` rule: 0.0% false changes on dead flies, 1.1 ms per frame for 20
tubes on a Pi 3). It is stored as an extra variable.

**Runtime.** ONNX (opset 13) through `cv2.dnn`, which is already on the devices (Debian
13, Python 3.13, OpenCV 4.14, aarch64). Only ops that `cv2.dnn` handles well: Conv
with BN folded in, ReLU, MaxPool and global pooling. TFLite, ncnn or int8 only if the
float model misses the budget.

## Labels

Every label source says exactly what it asserts. **A tube with no detection is never
used as a negative.**

1. **Confident positives.** A snapshot at t paired with that tube's ROI row at the
   same t, with `is_inferred = 0`, w and h within the DB's own fly-size distribution
   (median ± 3 MAD), and a continuous trajectory in the ±30 s around it (no jump that
   the preceding motion cannot explain). That last test excludes the second-blob hops.
2. **Gap-filled still positives.** The fly's last real detection before the snapshot
   and first real detection after it lie within 3 px of each other, and the gap spans
   the snapshot. The fly was there throughout, so the label is their mean. A sanity
   filter checks that the location is darker than the tube's median. These are the
   hard positives that background subtraction misses.
3. **Hard negatives come for free.** Every non-fly pixel of a positive crop (food,
   cotton, debris, the divider) is a negative for the heatmap. Explicit fly-free crops
   are needed only for the presence head.
4. **Never-detected tubes go to human review, not into negatives.** **(change)** To
   the tracker, a tube with almost no detections for the whole run is either empty or
   holds a fly that was dead from the start. The two look identical. Auto-labelling
   them "empty" would teach the network to ignore dead flies, which is the exact
   failure we are fixing.
5. **Human-verified gold set (~3,000 crops):** ~1,000 random auto-labels (measures
   label noise), never-detected tubes (empty or dead fly?), and, after the first
   training round, the crops where the network and the tracker disagree. The
   interface is a verification grid (accept, reject, click to correct), which is much
   faster than clicking every fly. I will first check whether flyscorer's
   click-the-fly mode can serve.
6. **Unlabelled** (tube not detected and not gap-filled): left out of training.

**Sampling.** Stratified by machine, year and light phase, capped at ~30 snapshots per
DB and ~1–2 M tube crops in total. Crops are stored at full resolution (so the scale
choice stays open) as uint8 shards under `/mnt/cache/dl_tracking/data` (~40 GB per
million crops).

**I/O.** The ROI tables are the 9 TB, and they have no index on t. But rows are
inserted in time order, so the rows around a snapshot can be found by bisecting on
`rowid`, which reads a few pages instead of scanning the table. To be verified per era.

**Splits** are by machine, never by frame: ~75/10/15% of machines for
train/val/test, plus a second, era-held-out test (train ≤ 2023, test 2024–2026). The
machines behind the video test sets (ETHOSCOPE_012, ETHOSCOPE_044, tonight's device)
are kept out of training entirely.

**Augmentation:** gain, gamma and offset; Gaussian and Poisson noise; blur; JPEG
quality 30–95; vignetting gradients; shifts along the tube; horizontal and vertical
flips; ±3° rotation; ±10% scale.

## Acceptance targets (proposed, for Giorgio to adjust)

Measured offline on raw video frames from held-out machines, against AdaptiveBGModel
on the same frames:

- Detection ≥ 99% where AdaptiveBGModel detects confidently, and ≥ 95% on still and
  dead-from-start flies (AdaptiveBGModel: <2% on the dead ones).
- Position error against human clicks: median ≤ 1.5 px, p95 ≤ 4 px (full resolution).
- Still-fly jitter: p95 frame-to-frame displacement < 0.5 px, so still flies stay
  under the threshold even when velocity comes from positions.
- False detections in verified-empty tubes: ≤ 1% of frames.
- Downstream: fewer movement false positives on pixel-still windows than
  AdaptiveBGModel, and sleep closer to the pixel truth (`eval_long.py`,
  `replay_trigger*.py`).
- Pi 3: ≥ 5 fps end-to-end with 20 tubes (AdaptiveBGModel runs at 4–5), without
  running hotter than the current tracker.

## Tasks

### Phase 0: setup
- [x] Branch `dl-tracking` from `dev` at e7e0f8ca, in this clone (turing).
- [x] `dl_tracking/` at the repo top level, not installed as a package: code, a
      `README.md`, `requirements.txt`, and `tests/` (pytest, mirrors the modules,
      files < 500 lines). Derived data, the venv and checkpoints live under
      `/mnt/cache/dl_tracking/`, never in the repo.
- [x] A uv venv (Python 3.13, to match the devices) with torch+CUDA, onnx,
      onnxruntime and opencv 4.14. It is separate from the repo `.venv` and adds
      nothing to the ethoscope package's dependencies.
- [x] Long jobs run in detached tmux sessions. The A4000 is shared (~6.7 GB already in
      use), which is plenty for these models.

### Phase 1: data census (read-only)
- [ ] `census.py`: per DB, record machine, name, date, layout (n_roi, ROI sizes),
      snapshot count, frame shape, row counts, schema quirks and median snapshot
      luminance by light phase. Output: `/mnt/cache/dl_tracking/census.parquet`.
- [ ] Archive overlap by key and size. The 468 archive-only runs are included.
- [~] Verify the pairing on a sample from every era (2020–2022 done): snapshot `t` equals ROI-row `t`,
      and x, y are ROI-relative. Overlay the positions on the snapshots and look at
      them.
- [ ] Verify that `rowid` is monotonic in `t` in each era, so bisection is safe.
- [ ] Summarise the machines, eras and lighting clusters to drive the stratification
      and the splits.
- [x] **Flag the no-IR runs.** A camera-settings bug once left IR mode off, giving very
      dark snapshots (Giorgio, 2026-09-30). Done by image signature, since neither the
      code history nor the dates pin the bug: 941 runs (143 machines) whose darkest
      census sample is below 40% of their brightest (with working IR the backlight
      keeps nights nearly as bright as days). The list, with commit, commit date and
      user, is `/mnt/cache/dl_tracking/flagged_no_ir_runs.csv`; 168 of the selected
      runs carry `no_ir = True` in `runs.parquet` and are kept out of training.
      Clusters: (A) 246 runs Sept 2023 – March 2024, 245 of them one user's
      (`lblackhurst`, ETHOSCOPE_030–034, AGO experiments), possibly that rig's
      lighting rather than the bug; (B) 82 runs on 17 machines with Oct–Dec 2022
      commits; the other 613 are scattered from 2016 to 2026. The NoIR-tuning code
      window (Sept 2025 – Aug 2026) is **not** enriched (4.4% dark nights against 4.6%
      before it). **Ask Giorgio roughly when the bug was**, so the flag can be
      narrowed to it.

### Phase 2: dataset builder
- [x] `labels.py`: pure functions for the confident-positive filter, the trajectory
      continuity test, gap filling and the darkness check. Unit tests cover expected
      use, edge cases (gaps at run start and end, hops, inferred rows) and failures.
- [x] `extract.py` (written, tested; full run waits for the census): DB → snapshots, labels and metadata, run in parallel in tmux,
      resumable per DB.
- [ ] Contact sheets of random labelled crops per era and label source. I inspect
      them myself before any human time is spent, and fix the filters until they look
      clean.
- [ ] List the never-detected tubes for review.

### Phase 3: human-verified set
- [x] Verification UI (`dl_tracking/review/`, stdlib server + one page, token in URL; tested in headless Chrome): accept, reject, click, and
      "empty or dead".
- [ ] Round 1: random auto-labels and never-detected tubes. Round 2, after model v0:
      disagreements between the network and the tracker.
- [ ] Report the auto-label error rate per source and era.

### Phase 4: train and export
- [x] `model.py`: tiny (2.9 M MACs), mid (3.9 M), small (6.1 M); dilated context blocks give a 65 px (half-res) receptive field. `train.py`: focal loss on the heatmap, L1 on
      offset, size and angle at the true centre, BCE on presence.
- [x] `export.py` (parity verified with random weights at 20- and 10-tube widths): fold BN, export ONNX opset 13, and check parity: `cv2.dnn` against
      PyTorch on 1,000 crops (identical argmax, heatmap max |Δ| < 1e-4).
- [ ] Held-out evaluation on snapshots (machine and era splits) and on the gold set.

### Phase 5: offline evaluation on video
- [ ] Run the network over `alice_012`, `e044` and tonight's video at native fps,
      against the AdaptiveBGModel DBs already in the work folder.
- [ ] Metrics from the acceptance targets, broken down by lighting condition, with
      bootstrap CIs across machines.
- [ ] Downstream: movement false positives and sleep against pixel truth, reusing
      `eval_long.py` and `replay_trigger*.py`.
- [ ] Pi 3 timing with real preprocessing (one resize per frame, one vectorised
      normalisation, one batched forward), relayed to ethoscopy-36 via Giorgio.
- [ ] Lossless test frames. The device API serves only `last_drawn_img` (a JPEG with
      the tracking overlay), and the camera belongs to the tracking process while a
      device runs. A clean burst needs either a new device route or a one-off capture
      on an idle device with flies. Ask Giorgio which; the project lesson reserves SSH
      for rsync.

### Phase 6: device integration (design only, then a separate approval)
Sketch, not to be implemented under this plan:
- `trackers/cnn_tracker.py`, a BaseTracker subclass. The Monitor calls `track()` once
  per ROI, so a shared per-frame inference object runs one batched forward pass on the
  first call for a new `t` and serves the other ROIs from its cache. No Monitor
  change is needed.
- A temporal prior (prefer the peak near the last position) to prevent hopping.
- The pixel-motion variable. The ONNX weights (~12–35 KB) ship as package data under
  `ethoscope/trackers/models/`. The tracker is selectable in the tracking options.
- AdaptiveBGModel and the stimulators stay untouched, since ethoscope-63 is working
  there.

## Risks

- **Imitating the tracker.** A network trained on tracker positions can learn the
  tracker's biases. Hence the strict filters, the gap-filled still positives, and
  evaluation against human clicks rather than agreement with the tracker.
- **Domain gap.** Training data are q50 JPEGs and h264 video frames, while live frames
  are raw. Hence the JPEG and noise augmentation, and ideally a small lossless test
  set from a real device (question 5).
- **Pi 3 heat and throughput.** Pi 3s already run at 73 °C, and the GPIO listener
  busy-loops a core. The runtime budget stays ≤ ~6 M MACs per tube, preferably ~2 M.
- **Old DBs** (2015–2016) may differ in schema or conventions. Phase 1 finds out, and
  anything odd is left out rather than special-cased.

## Decisions (Giorgio, 2026-09-30)

1. Plan and acceptance targets approved.
2. Branch `dl-tracking` created from `dev` at e7e0f8ca; local commits are fine, no pushes.
3. Giorgio labels, himself. He is shown **only** the items that need a human, in the
   simplest web page that will do.
4. `xy_dist`: decided by testing in Phase 5; the +1 px correction is probably not
   needed with the new tracker.
5. ETHOSCOPE000 has no flies. Lossless test frames come instead from the ethoscopes
   on `node`, which turing reaches through a tunnel via node. Only read-only frame
   grabs; anything that changes a device's state needs a separate OK.

## Open questions for Giorgio (answered above)

1. Is the plan, including the acceptance targets, approved?
2. Can I create the `dl-tracking` branch from `dev` and commit locally on it? (No
   pushes without asking.)
3. Human labelling: who, and is ~2 h for round 1 acceptable?
4. `xy_dist` convention for the new tracker: keep the +1 px so existing thresholds
   hold, or use the true distance and rely on the new motion variable? To be settled
   with the ethoscopy session.
5. Can the ethoscopy session capture a lossless burst of frames (a few hundred PNGs,
   day and night) from ETHOSCOPE000 for the domain-gap test?

## Discovered During Work

- **Code so far** (`dl_tracking/`, 56 tests): `db_io` (read-only access, rowid
  bisection), `census`, `select_runs` (machine-grouped splits), `labels`, `extract`,
  `preprocess` (the canvas geometry and normalisation; one path for training and
  device, to move into the device package with the tracker), `model`, `dataset`
  (pack, targets, augmentation, seam-free swapped negatives), `train`, `export`,
  `run_video`, `qa` (contact sheets), `review/` (the labelling page).
- **Smoke test (2026-09-30).** A tiny model trained on 25 snapshots from one machine
  reached 1.5 px median error, 90% detection within 4 px and presence 0.98 against
  0.06 on a held-out run. On `alice_012` it placed all 20 flies in the frame checked,
  including the five dead ones, with 0.18–0.36 px position SD over 20 s. That is not an
  evaluation, but it supports the design.
- **Smoke model on `alice_012`** (25 training snapshots; `dl_tracking.evaluate`, 13,713
  frames shared with the 4 fps AdaptiveBGModel DB). Detection: 98.4% of tube-frames
  against 72.1%, and 100% against 0.06% on the five dead flies. But positions jitter:
  on the dead flies the frame-to-frame displacement is 0.31 px median and 2.8 px at the
  99th percentile, and rounded to whole pixels (the DB schema) it flips by 1 px in 43%
  of frames. On pixel-still windows, 40% (float) and 97% (rounded) are called moving
  at a 1 px cut, against 31% for AdaptiveBGModel. So movement must not come from
  rounded positions of this network: either the pixel-motion variable, or positions
  stabilised on the device (hysteresis, or a local intensity-weighted centroid around
  the network's estimate). This is a Phase 6 design question; the trained model's
  jitter will be measured first.
- **Positions in the DBs are integers** (SMALLINT). Still-fly jitter measured against
  DB labels is quantised to 1 px, and a device writing the new tracker's output
  through the same schema rounds too. Relevant to the `xy_dist` question in Phase 5.
- **Swapped negatives need gain matching.** Two snapshots with the same overall
  brightness still differ locally, so a raw paste left a visible band. The window is
  now fitted (gain and offset) to the columns just outside it.

- **Census I/O.** `/mnt/data` is two HDDs in linear LVM (~300 random reads/s in
  total). The first census draft cost ~600 reads per DB (~12 h in total); the slimmed
  one costs ~150 (~4 h). Extraction therefore must not bisect on the HDDs: each chosen
  DB is copied sequentially to NVMe (a 436 MB DB in seconds), labelled there, and the
  copy deleted.
- **Store snapshots, not crops.** The original q50 JPEG blobs (~40 KB each) are the
  source data. ~100k snapshots are ~4 GB, whereas decoded crops would be ~80 GB.
  Crops are cut at training time.
- **Pairing verified (2020–2022).** A snapshot's `t` matches ROI rows exactly, and x, y
  are ROI-relative (every overlay circle sits on its fly). Frame intervals are
  400–700 ms (1.4–2.4 fps) in these runs, so trajectories are coarse.
- **Not every run is a tube layout.** ETHOSCOPE_240 (2022, `TargetGridROIBuilder`)
  has 24 circular wells. Scope is tube layouts (ROI aspect ratio > 5); the census
  counts the rest.
- **Machine ids are not unique.** Cloned SD images share an id (for example
  `0001eeee…` appears as ETHOSCOPE_033 and others). Split groups are therefore the
  connected components of (machine_id, machine_name) pairs.
- 0-byte DB files exist; the census records them as `empty file` (569 of 21,840).
- **Two `selected_options` formats.** Some 2025–2026 versions write it as an
  OrderedDict of pairs, `(('tracker', {...`, not a dict. The first parser missed them,
  which silently dropped 763 recent runs; both forms are now parsed. The 342 runs
  from 2015 predate `selected_options` and stay excluded.
- **Census totals.** 21,840 DBs, 14,402 usable tube-layout runs (66%), 290 device
  groups (1,172 machine ids for 291 names: cards get re-flashed). Selection at 3 runs
  per group and year: 2,768 runs (1.57 TB), 2,081 train / 260 val / 427 test.
- **Some DBs hold their run twice.** 2.8% of the 2020–2023 DBs have ROI tables where
  `t` runs to the end and then restarts. They cluster in Feb–Mar 2022, which looks
  like a backup that appended its dump a second time. Excluded (`monotonic == 0`),
  since bisection would return rows from the wrong copy.
- **Label QA, first pass (3 runs, 2020–2022).** All 24 sampled `confident` labels sit
  on a fly. 4 of 6 `gapfill` labels do; the 2 wrong ones (a fly that moved and came
  back during a 68-min gap, and a label on the food) have negative contrast, so gap
  fills need a contrast threshold relative to the same fly's confident labels.
  `rejected_*` crops nearly all show a fly, so the rules are conservative; their
  tracker positions are kept for later recovery. `missed` crops mostly show a fly
  the tracker lost in dim tubes at night, which is the target of the model.
- **Hop rule loosened.** At 1–2 fps a 4 px jump threshold flagged ~22% of windows,
  nearly all of them walking or 4 px centroid jitter. Now 8 px, excursions of at most
  20 rows, and only hops within ±10 s of the snapshot reject its label.

- The brief counted ~18,500 DBs in `/mnt/data/results`. A glob finds 21,372 (the
  difference is probably DBs without snapshots). The census will settle it.
