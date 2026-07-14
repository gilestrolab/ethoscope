# OpenCV 5 migration (deferred)

Date raised: 2026-07-14
Status: **Deferred** — dependency capped at `<5.0` as a stopgap in `8885ff46`

## Why this exists

`opencv-python 5.0.0.93` was published to PyPI in July 2026. Both packages
declared `opencv-python>=4.8.0` with no upper bound, so CI — and any fresh
ethoscope install — silently jumped to OpenCV 5 and broke.

This was not a CI-only problem. A device flashed on the day OpenCV 5 landed
would have installed it and been unable to track.

Both `pyproject.toml` files are now capped at `>=4.8.0,<5.0`, which restores the
last known-good major (4.13). The migration itself is still to do.

## What actually breaks under OpenCV 5

CI run on `b49aa72c` with `opencv-python 5.0.0.93` (vs 4.13.0.92 on the previous
run) produced exactly three device failures:

- `AttributeError: 'BaseDrawer' object has no attribute '_draw_frames'`
- `AttributeError: 'NullDrawer' object has no attribute '_video_writer'`
- `AssertionError: 5 not found in [2, 3, 4]`
  (`test_img_roi_builder.py::TestImgMaskROIBuilder::test_cv_version_exception_handling`)

## Root cause

The codebase branches on the OpenCV **major version** in at least six modules,
and none of them has a branch for 5 — they fall through to an unintended path:

```python
CV_VERSION = int(cv2.__version__.split(".")[0])
```

- `ethoscope/core/roi.py:7`
- `ethoscope/roi_builders/target_roi_builder.py:9`
- `ethoscope/roi_builders/img_roi_builder.py:4`
- `ethoscope/roi_builders/arena_mask_roi_builder.py:6`
- `ethoscope/trackers/single_roi_tracker.py:8`
- `ethoscope/trackers/multi_fly_tracker.py:9`

## Work to do

1. Audit every `CV_VERSION` branch and decide whether the 2/3 legacy paths can
   simply be dropped — OpenCV 2 and 3 are long dead, and removing them would
   delete the whole class of bug rather than adding a fifth branch.
2. Fix the drawers (`_draw_frames`, `_video_writer`): confirm whether these are
   genuine OpenCV 5 API changes (e.g. `VideoWriter` fourcc/back-end handling) or
   test-only breakage.
3. Update `test_cv_version_exception_handling`, which hardcodes `[2, 3, 4]`.
4. Re-test on real hardware — the Pi camera path is not covered by unit tests.
5. Only then lift the `<5.0` cap in both `pyproject.toml` files.

## Lesson

Unbounded upper pins on a C-extension dependency that gates on its own major
version are a time bomb. Consider whether `numpy` (already capped `<2.1.0`) and
the other runtime deps need the same treatment.
