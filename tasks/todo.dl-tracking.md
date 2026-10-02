# Learned per-tube fly locator (`dl-tracking`)

Date: 2026-09-30
Status: **Approved 2026-09-30.** Phases 0–2 done; review round 1 open; v1 training running.
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
- [x] **Flag the no-IR runs.** Giorgio: the camera problem started with the move to
      picamera2. The history bounds it: `370c9491` (2024-02-02) moved to picamera2,
      which runs libcamera's default *colour* tuning on NoIR sensors; NoIR tuning was
      an option defaulting to off (`faf84b46`), then unconditional (`217084d9`), and
      actually applied only from `766de9ab` (2026-08-26). A run is affected when its
      commit is in [370c9491, 766de9ab) **and** the device ran picamera2, which the
      kernel in `hardware_info` tells: Arch Linux ARM (`*-rpi-ARCH`) kept legacy
      picamera, Raspberry Pi OS (`+rpt`, `-v8`) has only picamera2.
      Result, `/mnt/cache/dl_tracking/flagged_no_ir_runs.csv`: **691 runs on 57
      machines (2024-11-08 → 2026-08-26)**, plus 204 "stack unknown" (window code, no
      kernel recorded). Brightness does not find them: auto-exposure mostly
      compensated (median night luminance 78 against 89 for legacy-picamera runs of
      the same period; fixed runs are brighter, ~122). An earlier luminance-only flag
      (dark nights) was dropped: its largest cluster was one user's AGO rig
      (`lblackhurst`, ETHOSCOPE_030–034, 2023–24), not this bug.
- [ ] **Train with and without the flagged runs.** 214 selected runs are flagged,
      including 34 of the 86 train runs from 2025 and 101 of the 132 from 2026, which is
      nearly all the recent data and all of the picamera2 camera stack. The plan said
      to keep them out of round 1; with this many, v1 is trained both ways and
      scored on the flagged test runs and the rest separately.

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

- [x] Round 2 queued after round 1 (2026-10-01): tiny_v2 scored the 104,165 crops
      AdaptiveBGModel missed in the train split (62,300 confident fly, 9,161
      confident empty, 32,704 in between). Queued: 100 uncertain (presence
      0.15–0.85, mostly tube ends and empty-looking tubes), 40 confident-fly and
      20 confident-empty audits. Queue total 1,110 crops.
- [x] **Giorgio's review (2026-10-01): all 1,110 crops answered.** Error rates:
      AdaptiveBGModel confident labels 3.3% (5 of 150 wrong), tiny_v2 confident
      "fly" on tracker misses 10% (4/40), tiny_v2 confident "empty" 0% (0/20); its
      uncertain band was 98% empty tubes. Never-detected tubes: 184 of 200 empty
      throughout, 10 with a dead fly in all four strips (within 10 px; up to 207 h),
      the rest moved once or faded. Giorgio: the unrecognised flies were probably
      dead, and dead flies dehydrate and change shape with time. Propagation over
      each tube's other snapshots gives 5,226 human labels (469 fly, 4,757 empty);
      the test split holds 774 verified empty crops and 53 dead-fly crops.
- **Human labels fix empty tubes.** On 774 verified-empty test crops (32 tubes),
  false presence at 0.5 was 56.5% (tiny_v2) and 55.3% (tiny_s2_v2), and 13.3% for
  tiny_s2_v3; on validation (300 crops, 12 tubes) 3.7%. A 0.9 threshold gave 0.8% on
  test but cost dead flies on validation (84% found), so no threshold is chosen yet.
  The remaining false detections sit in a few tubes: dark end caps at the ROI ends,
  ROIs not on a tube (a cable, a blank area), reflections in dark frames.
- **tiny_s2_v3 on the videos** (blended decode, tracks only where a fly is reported).
  alice_012: detect 99.8%, dead flies 100%, dead-fly jitter p95 0.30 px, still
  windows called moving 6.0% / 0.6% / 0.0% at 0.52 / 1 / 2 px. e044: detect 92.9%,
  still → moving 17.1% / 1.7% / 0.3% (AdaptiveBGModel 44.5% / 44.5% / 1.4%). It
  matches or beats tiny_v2 and mid_v2 everywhere and is the fastest on the Pi 3:
  **the current candidate**. e044 tubes 14 and 11 (58%, 63%) remain the tube-end gap.
- [ ] **Round 3 queued** (2026-10-01): 100 of the 1,058 unreviewed never-detected
      tubes where v3 sees a fly somewhere, plus 20 it calls empty; four strips each.
- [ ] **Soak test** of tiny_s2_v3 on ETHOSCOPE000 (240 min static + 60 min camera,
      from 12:31). The bench PSU sags under 4-thread load (0x50005, ARM at 600 MHz
      while scaling_cur_freq said 1200), so analyse by throttle bits; a production
      ethoscope with its normal supply is the deciding test.
- [x] **Round 3 (2026-10-01).** Of the 100 tubes where v3 saw something: 49 empty
      throughout (its false detections), 29 dead flies (same place at every time),
      13 flies that moved, 9 seen only in some strips (Giorgio: the controversial
      cases are again dead bodies). Where a fly was present v3's ring was within
      4 px of the click in 185 of 186 strips; its "empty everywhere" tubes were all
      empty. Human labels now 7,876 (1,376 fly, 6,500 empty); v4 trains on them.
- [x] **Round 4 (2026-10-01).** 67 more never-detected tubes where v3 saw a fly: 19
      immobile at every time (dead flies, or pupae: Giorgio, "all those cases are
      immobile targets, scored as dead", so calling them a fly costs nothing), 22
      with a live fly that moved between times (a whole tube of data AdaptiveBGModel
      lost, <1,000 detections in the run), 8 seen in some strips, 18 empty. Rings
      within 4 px of the click in 178 of 179 strips. Human labels: 8,977 (2,010 fly,
      6,967 empty).
- **Production fleet (2026-10-01, stopped devices via ssh through node, cleared by
  Giorgio).** All stopped devices are Pi 3 (B or B+), on dev d960edb9, but with
  **OpenCV 4.7.0, 4.9.0, 4.11.0 and 4.13.0**. On 4.7.0 the presence output was
  NaN (ReduceMax/ReduceMean); fixed by global pooling, then parity within 1e-5 on
  every version. Full path, tiny_s2_v3, 20 tubes, 4 threads: ETHOSCOPE_380 44.9 ms
  (22.3 fps), ETHOSCOPE_025 (3B+, 4.7) 52.1 ms (19.2 fps), ETHOSCOPE_301 73.3 ms
  (13.6 fps) at 600 MHz because its supply is under-voltage even at idle (0x50005
  on 301, 310 and 359; Giorgio: PSU problems are common and must be lived with).
  4 threads beats 3 everywhere. Soak tests (120 min static + 30 min camera) on 380
  and 301 from 13:48.
- [ ] **v3** (tiny_s2, chosen on the Pi timings): `python -m dl_tracking.review.ingest`, then train v3
      (`train.py` picks up `review/human_labels.parquet`): human answers override
      automatic labels and verified empty tubes become negatives; `final.json`
      reports `test_human`, the false-detection measure for real empty tubes.

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
Constraints measured so far (2026-10-01):
- **Cap the tracker's frame rate** (≈ 8–10 fps). At full speed a Pi 3 in its
  enclosure (ETHOSCOPE_380, healthy supply) went 58 → 82.7 °C in ~80 min, hit the
  soft limit and was frequency-capped (0x70002; 44.9 → 49.1 ms per frame).
  At ~50 ms per frame, 10 fps is half load, still twice AdaptiveBGModel's 4–5 fps.
- **cv2.setNumThreads(4)** on d960edb9 and later (cores − 1 on older code, where
  the GPIO listener busy-loops a core).
- **The model must stay within ops every fleet OpenCV runs** (4.7 to 4.14): Conv,
  Relu, GlobalMaxPool, GlobalAveragePool, Concat, Flatten. Check new exports with
  `pi_parity.py` on a 4.7 device.
- **Weak supplies can brown out under camera + CPU load.** In the production soak
  (tiny_s2_v3, 4 threads, full speed; 120 min static then 30 min live camera),
  ETHOSCOPE_380 (healthy supply) held 49.1 ms per frame static and 66.9 ms with
  capture (~15 fps), thermally capped at up to 83.8 °C, with no stalls.
  ETHOSCOPE_301 (under-voltage even at idle, 600 MHz) held 72.9 ms static at 47 °C,
  then **rebooted ~10 min into the camera phase** (boot 15:58:11; no persistent
  journal, so the cause is inferred). Its overnight recording the night before also
  failed ("Could not get frame from camera"). The frame-rate cap is therefore also
  a current cap; consider 3 threads on devices that report under-voltage.
- **Do not assume a fixed frame interval**: under-voltage throttling (common in the
  lab) moves a frame between ~45 and ~75 ms.
- `xy_dist` from float positions before the SMALLINT rounding.

**Approved 2026-10-02** (plan: `~/.claude/plans/cuddly-hopping-russell.md`). The
tracker is called `DeepTubeTracker`. It is a radio button in the start dialog's tracker
group, AdaptiveBGModel stays the default, and a live test on one stopped device is
allowed.
- [x] `trackers/deep_tube/`: preprocess copy, engine (batched forward, shake
      correction, setup check), tracker, v5 ONNX + model card
- [x] Monitor hook `make_shared_state` (one engine per Monitor)
- [x] control: selectable on production Pis, early setup check, `tracker_model`
      metadata
- [x] package data; unit, control, integration and drift tests; parity reference
      (device suite 1,214 passed + 3 integration; dl_tracking 96 passed)
- [x] docs (CLAUDE.md, READMEs, rst)
- [ ] live check on a stopped device (git bundle, no push), then restore it
- [ ] later, own commit: tracker arguments from the UI are dropped in
      `_start_tracking` (kwargs built, never passed to Monitor)
- **Found while integrating (2026-10-02).**
  - The bandit pre-commit hook (rev 1.7.6) cannot run on Python 3.14: it reports
    "Unknown test found in profile" and cannot parse any file, so every commit
    touching `src/` fails it. bandit 1.9.4 (via `uvx`) finds no medium/high issue in
    the new code; the integration commits skip only that hook (`SKIP=bandit`).
    Bumping the hook's rev is a one-line fix for Giorgio to decide on.
  - The ROI template JSONs are not package data either, so a wheel would ship
    without them (devices install editable, so nothing breaks today).
  - `is_inferred` is stored as the text '0' / '1' (BOOLEAN column through the
    writer), for every tracker.

Sketch, superseded by the plan above:
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

- **Extraction and pack (2026-09-30).** 2,768 runs extracted (1 malformed DB),
  69,125 snapshots (3.7 GB), 896,596 training positives (891,746 confident, 4,850 gap
  fills after the contrast filter), 1,258 never-detected tubes in 346 runs, and
  144,723 `missed` crops for round 2. Review round 1 (200 tubes × 4 strips + 250
  audits) is served from turing on port 8765 (token in
  `/mnt/cache/dl_tracking/review/token`). v1 (tiny, 30 epochs) trains with and
  without the flagged runs, in tmux `dl_train_excl` / `dl_train_incl`; epoch 0
  already gave 0.98 px median error and 94% detection on validation machines.
- **v1 → v2 (2026-10-01).** Test machines (errors against tracker labels; false
  presence on swapped fly-free canvases):

  | | p95 err, unflagged | detect, unflagged | p95 err, flagged | detect, flagged |
  |---|---|---|---|---|
  | v1 tiny, without flagged | 2.93 px | 96.2% | 4.07 px | 94.9% |
  | v1 tiny, with flagged | 2.95 px | 96.1% | 3.73 px | 95.3% |
  | v2 tiny (no gap fills, no flat canvases) | 2.65 px | 96.4% | 1.80 px | 98.0% |
  | v2 mid | 2.49 px | 96.6% | 1.68 px | 98.1% |

  Training with the flagged picamera2 runs helps on them and costs nothing elsewhere,
  so they stay in. Most remaining test "misses" are label problems (gap fills on
  tube-end objects, two fly-like objects in a tube, flat canvases), not model errors.
- **Gap fills were 75% wrong.** The rule "lost and found again in the same place"
  is equally true of a static dark object at a tube end (end cap, ROI edge), which
  AdaptiveBGModel picks up about once a day. Gap fills are off by default; to
  reinstate them, require the fly to be seen walking into or out of the spot.
- **Cell-boundary flips.** v2 made a dead fly jump ~0.9 px in a quarter of frames:
  its centre sat on the boundary of two heatmap cells (logit margin 0.09), and each
  cell's estimate was steady but they disagreed. `decode()` now blends the peak
  with its strongest neighbour (weight 0.5 at a tie, 0 one logit below), which is
  continuous across a flip. On `alice_012`, blended decode:

  | | detect all / dead | dead-fly jitter p95 | still windows called moving @1 px | moving windows detected @1 px |
  |---|---|---|---|---|
  | AdaptiveBGModel | 72.1% / 0.1% | — | 30.6% | 95.7% |
  | v1 tiny | 99.8% / 100% | 0.30 px | 0.6% | 74.3% |
  | v2 tiny | 99.9% / 100% | 0.39 px | 1.3% | 75.1% |
  | v2 mid | 99.9% / 100% | 0.35 px | 0.7% | 74.5% |

  The jitter target (p95 < 0.5 px) is met. Movement windows missed at 1 px are mostly
  twitches with no centroid displacement, which the pixel-motion variable is for.
  `xy_dist` should be computed on the device from float positions (before the
  SMALLINT rounding); no +1 px correction is needed.
- **e044, 47 h, dim IR, test machine (2026-10-01).** 1.04 M frames, pixel truth at
  the noise-scaled level (`evaluate --level auto`, = eval_long.py). Locator tracks
  use only frames where it reports a fly (scoring every frame had inflated false
  movement).

  | | detect | still → moving @0.52 / 1 / 2 px | moving detected @1 / 2 px |
  |---|---|---|---|
  | v2 tiny | 93.4% | 20.6% / 2.0% / 0.3% | 66.4% / 58.3% |
  | v2 mid | 92.9% | 20.4% / 2.2% / 0.4% | 66.5% / 58.2% |
  | AdaptiveBGModel | 78.2% | 44.5% / 44.5% / 1.4% | 86.6% / 61.6% |

  The detection gap is concentrated in tubes 14 (55%) and 11 (69%): for hours the
  fly sits at the very end of the tube, half outside the ROI box. The model's peak
  is on it but presence stays near 0.05; AdaptiveBGModel loses it too (48%). To do:
  train with flies partly cut off by the canvas edge (still present), and check
  whether a slightly wider canvas can reach the tube ends without seeing the
  neighbouring tube across the divider. tiny and mid perform alike, so tiny (2.9 M
  MACs) is the candidate unless the Pi has room to spare.
- [ ] **Partly visible flies at tube ends** (above): augmentation, then re-check
      e044 tubes 11 and 14.
- **ETHOSCOPE_109, 22.8 h legacy video (2019-11-22, 25 fps), 10 single-fly tubes
  (2026-10-01).** From `/mnt/archive/_rescued/legacy_ethoscope_video`; work in
  `/mnt/cache/dl_tracking/eval/legacy/` (scripts in `analysis/`). The locator runs on
  every frame; AdaptiveBGModel on every 4th (6.25 fps, as e044).

  **The rig's camera shakes.** In bursts, the whole image moves ~1–1.5 px vertically
  on alternate frames, beating slowly, as a ~12.5 Hz vibration (half the frame rate)
  would; sampled peaks reach 6 px. 1.3% of frames move ≥ 0.3 px, spread evenly over
  the 23 h; 99.6% of those steps are vertical. Found because 4,767 windows the pixel
  truth called moving had no locator step ≥ 1 px: at their peak frames the image moved
  1.34 px (median), against 0.03 px at walking peaks and 0.013 px on still frames.
  alice_012 and e044 show nothing like it (0.05 and 0.10 px at their busiest frames).
  - The shake reached everything. 18% of pixel-truth hits fell on shaken frames, and as
    each hit breaks a 5-min bout, sustained truth sleep goes from **18.3% to 85.3%**
    once they are dropped. Every tracker reports the shake as movement unless its
    sampling interval is an even number of frames, where the alternation cancels: the
    raw locator called 3% sleep at 25 fps and 82% at 12.5 fps.
  - Measuring it: phase correlation pixel-locks on these smooth frames (a 0.5 px
    synthetic shift read as 0.24–0.81 px), and against a fixed reference frame its
    response decays to noise within a minute (H.264 noise is shared only by
    consecutive frames). `analysis/lkshift.py` fits one translation per frame pair by
    Lucas–Kanade instead: within 0.09 px on synthetic shifts of 0.25–1.5 px.
  - **The locator sees the shake exactly.** Its per-frame median displacement over the
    20 tubes follows the measured image shift with correlation 0.95, slope 0.96 and
    0.08 px residual (p95, 41k frames). Tubes move 0.85–1.13 × the image, with no
    trend in height (no rolling-shutter wobble to model).
  - So a device can remove it without image work: subtract each frame's median step
    over all tubes (common mode), and ignore steps on frames whose common mode is
    ≥ 0.3 px (0.8–1.7% of steps). The gate is needed because the largest shakes leave
    ~1 px after subtraction.

  Clean truth (shaken frames dropped), 1 px cut, v5:

  | | sleep (truth 85.3%) | per-tube sleep error | moving windows found | still → moving |
  |---|---|---|---|---|
  | locator 25 fps, common mode + gate | 78.8% | 6.4% | 89.9% | 0.6% |
  | locator 12.5 fps, common mode + gate | 82.0% | 3.3% | 93.1% | 0.8% |
  | locator 8.3 fps, common mode + gate | 78.4% | 6.8% | 94.2% | 1.1% |
  | locator 6.25 fps, common mode + gate | 79.2% | 6.0% | 94.5% | 1.4% |
  | locator 6.25 fps, raw | 70.5% | 14.8% | 94.8% | 2.0% |
  | AdaptiveBGModel 6.25 fps @0.52 px (default) | 17.0% | 68.3% | 99.9% | 50.3% |
  | AdaptiveBGModel 6.25 fps @2 px | 51.0% | 34.3% | 90.0% | 3.6% |

  Per tube (6.25 fps, common mode), the locator is 2–15 points under the truth in all
  ten tubes (no dead flies here); AdaptiveBGModel at 2 px is 13–52 points under. v3 is
  a little worse than v5 (per-tube error 8.0% against 6.3% at 6.25 fps). Common mode
  does nothing for AdaptiveBGModel, whose integer positions jitter by more than the
  shake.
- **v6 (all four review rounds) does not beat v5 (2026-10-01).** Snapshot test sets
  alike (median error 0.62 against 0.60 px, p95 2.67 against 2.66). Per-tube sleep
  error against pixel truth, 1 px cut:

  | | alice_012 | e044 | ETHOSCOPE_109 clean, 6.25 / 12.5 fps (common mode + gate) |
  |---|---|---|---|
  | v3 | 3.9% | 6.3% | 7.6% / 4.8% |
  | v5 | 3.8% | 6.4% | 6.0% / 3.3% |
  | v6 | 6.1% | 6.6% | 6.4% / 4.1% |

  e044 is a tie. v6 detects least there (91.0%, against 92.0% for v5 and 92.9% for
  v3) and jitters more on alice_012's dead flies (p99 0.57 against 0.49 px). The
  round-4 tubes (dead flies, pupae) were already found by v3/v5 and matter little to
  centroids, so **v5 stays the candidate**.
- [ ] **Common-mode correction on the device** (Phase 6 design): median step over
      tubes, gate at 0.3 px, needs ≥ 5 tubes with a fly. Check on the fleet whether
      other rigs shake (cross-tube synchrony of pixel motion at lag 0 against lag 1 is
      the cheap test).
- **Pi 3 timing (ETHOSCOPE000, by the ethoscopy session, 2026-10-01).** Full device
  path, 20 tubes, median ms per frame (forward | total → fps), untrained variants:

  | variant | MACs | 3 threads | 4 threads |
  |---|---|---|---|
  | tiny (v1/v2 architecture) | 2.89 M | 67.7 \| 75.2 → 13.3 | 91.6 \| 100.4 → 10.0 |
  | **tiny_s2** (stride-2 stem) | 2.05 M | **51.0 \| 58.9 → 17.0** | 69.0 \| 79.4 → 12.6 |
  | tiny_d24 (two dilated blocks) | 2.44 M | 62.8 \| 70.3 → 14.2 | 82.2 \| 90.5 → 11.1 |
  | tiny_s2k5 | 2.71 M | 74.1 \| 81.6 → 12.2 | 92.5 \| 100.0 → 10.0 |
  | tiny_k5 (5×5 depthwise) | 3.56 M | 91.0 \| 98.6 → 10.1 | 114.2 \| 122.2 → 8.2 |

  Dilated depthwise convolutions cost 20–27% of the forward pass in cv2.dnn there,
  and 5×5 kernels are slower still. 3 threads beat 4 for every variant, and are far
  steadier, because the GPIO listener busy-loops a core: the device default should
  be `cores - 1` until that is fixed. 60 → 75 °C over 15 min (no throttling during
  the run, past under-voltage in `vcgencmd get_throttled` = 0x50000), so a long
  soak test is needed before multi-day use. Normalise dropped 6 → 3–4 ms with
  cv2.meanStdDev; the blended decode cost 2.5–3.6 ms there and was then halved.
  tiny_s2 and tiny_d24 are training on the v2 data.
- **Two training crashes fixed.** `np.polyfit` failed to converge on flat pixel rings
  in the swap gain match (now a closed-form mean-and-spread match), and unpinned
  OpenCV/torch threads in 24 loader workers made epochs ten times slower.
- **Code so far** (`dl_tracking/`, 69 tests): `db_io` (read-only access, rowid
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
