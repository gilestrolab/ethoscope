# Activity trigger: binned duty cycle (fixes "zero stimuli delivered")

Date: 2026-08-11
Status: **Done**
Follows: `todo.activity-trigger.md` — this is the "Deferred" item at the bottom of that
file, which turned out not to be optional.

## The report

A student ran the Activity trigger on ETHOSCOPE_265 and got, in her words, no stimuli.

## What the data actually showed

Three activity runs on ETHOSCOPE_265, all on current firmware (`13b7f787`):

| run | `min_active_time` | stimuli delivered |
|---|---|---|
| 2026-07-16 | 300 s | **1** (21.4M rows, 20 flies) |
| 2026-07-29 | 120 s | **11** |
| 2026-07-31 | 120 s | **23** |
| 2026-07-27 (inactivity, 120 s) | — | 4619 |
| 2026-08-03 (inactivity, 120 s) | — | 3039 |

Nothing crashed and nothing fell back. The trigger ran correctly and never fired.

**Root cause.** She set `min_active_time` to 120/300 s, mirroring the `min_inactive_time`
she uses for sleep deprivation. That is the natural thing to do and it is unreachable.
The two triggers looked symmetric but were not: a sleeping fly genuinely produces no
moving frame for minutes, whereas a walking fly dips below the velocity threshold
constantly. Replaying her own data, *genuine* continuous 120 s bouts occur **zero** times
in 77 h. Measured yield of real bouts, per fly per day: 5 s → 86562, 10 s → 28064,
30 s → 1658, 60 s → 84, **120 s → 0**. The UI accepted up to 3600 s with no warning.

**And the few that did fire were artifacts.** 16 of the 23 (70%) landed on an *inferred*
position. `_infer_position()` returns the previous DataPoint verbatim and `_has_moved()`'s
"not spotted" guard never fires for inferred points, so a fly lost while its last real
frame read "moving" keeps reading "moving" for the full 30 s inference cap. Those ghost
bouts were the only thing getting near 120 s.

## Design

Replace the all-or-nothing bout with a **binned duty cycle**: cut the window into short
bins, score a bin active if the animal moved *at all* within it, and fire once
`activity_threshold` of the bins are active.

Two candidates were measured against all three runs before choosing.

**Rejected — fraction of moving *frames*.** Works, but is frame-rate dependent. At 120 s /
85%: 57, 71, but only **5** per fly/day on the 4 fps run despite near-identical activity
(moving-frame fraction 0.285 vs 0.282). A frame-count average concentrates towards the
mean as sampling rises, so the ≥85% tail thins out — meaning the low-fps runs were partly
firing on sampling noise, and a camera change would silently rescale the protocol.

**Chosen — fraction of active *bins*.** "Moved at all in 10 s" saturates, so it does not
drift with fps. Same three runs at 120 s / 85%: **187 / 228 / 234** per fly/day. Spread
collapses from 14x to 1.25x. Mis-fire proxy (mean inferred fraction of the firing window)
also falls, from 22–33% to 4–17%. It reuses the criterion `InactivityTrigger` already
applies, one bin wide.

`is_inferred` was deliberately **not** touched: inference is mostly caused by the tracker
losing a fly during prolonged inactivity, so filtering on it would bias the activity
measure itself, and an occasional false positive is acceptable.

## Parameters

- `min_active_time` default **10 s → 120 s**, min 1 → 10. Now genuinely mirrors
  `min_inactive_time`; the short default only existed to work around the old rule.
- `activity_threshold`, new, default **0.85**, exposed in the UI. Sits on the p90 knee of
  the observed 120 s duty-cycle distribution (p50 = 0.10, p90 = 0.86, p99 = 0.99); the old
  implicit 100% sat above p99.4, which is why it starved.
- Bins target 12 per window but never go below 5 s, so windows under ~60 s get coarse
  threshold steps. Documented in the class docstring.

## Changes

- `stimulators/triggers.py` — `MovementBoutTrigger` keeps only what the two polarities
  genuinely share (`_has_moved()`, the probability draw as `_draw()`). `InactivityTrigger`
  owns its continuous-stillness clock; `ActivityTrigger` owns the binned window.
  `_fires_when_moving` is gone: the polarities no longer share a bout clock to flip.
- `stimulators/composed_stimulator.py` — new `activity_threshold` arg and UI field;
  `min_active_time` default and label updated.

### Also fixed (found while diagnosing, verified independently)

- `control/tracking.py:726` — a stimulator that failed to construct **silently fell back
  to `DefaultStimulator` for every ROI**, producing an experiment that tracked perfectly,
  looked healthy in the UI and delivered nothing, undetectable until the data came back.
  Fuzzing found five realistic form payloads that hit it (a blanked numeric field, a
  cleared field, a blank daily start time, an unknown `trigger_type` on a device that had
  not been updated). Now raises `EthoscopeException`, which the existing handler surfaces
  as a device error.
- `utils/scheduler.py` — `DailyScheduler` anchored its daily window with
  `int(t // 86400)`, i.e. the **UTC** epoch day, so `daily_start_time="09:00:00"` ran
  10:00–18:00 under BST and jumped an hour mid-experiment at DST transitions. Extracted
  `_daily_start_timestamp()`, anchored to the local wall clock (not midnight + seconds, so
  the 23 h and 25 h DST days stay correct), and routed all three call sites through it.
  `test_scheduler_timing.py` had encoded the same UTC assumption and agreed with the bug;
  updated to a local-midnight helper.

## Verification

- **825 tests pass** (`src/ethoscope`), up from 815; black and ruff clean.
- **Behaviour-preservation on inactivity**, the thing most at risk from the refactor:
  replayed old vs new `InactivityTrigger` over real ROI data from two devices —
  **identical on every ROI**, and matching the counts the devices actually recorded
  (494 / 633 / 692 / 832 …). Two ROIs differ from the device by 1 and 9; confirmed
  pre-existing, since old and new agree with each other (replay cannot see frames where
  tracking returned nothing, which the db does not record).
- **The new rule replayed over all three of her real runs** reproduces the offline
  analysis: 187 / 228 / 234 per fly/day at the new defaults.
- New tests cover the regression directly: one quiet bin in 12 (92%) fires where the old
  rule threw the bout away; three quiet bins (75%) correctly does not; the same trace
  flips on threshold alone; and a frame-rate sweep (2/5/10/25 fps) asserts the fire time
  drifts less than 1 s.

## Discovered during work

- `_has_moved()` divides by `dt_s` before the term cancels out, so two frames sharing a
  timestamp raise `ZeroDivisionError` out of `apply()` and kill the monitor. Latent and
  pre-existing; `velocity_corrected` is algebraically just `dist / coef`. Left alone —
  worth a separate one-line fix.
- `ethoscopeFormService.js` seeds arguments with `argDef.default || ''`, so the boolean
  default `False` is posted as `''` (visible in every recorded run's metadata as
  `'time_restricted': ''`). Harmless today because `''` is falsy. Pre-existing.
- ETHOSCOPE_354 is still on `bd2c5f35` (2026-06-29) and has never run any version
  containing the Activity trigger — worth checking why it is not picking up updates.
