# Activity trigger + time restriction as a cross-cutting modifier

Date: 2026-07-14
Status: **Superseded** — see `todo.activity-trigger-duty-cycle.md` (2026-08-11).

> The "continuous bout, strict mirror" decision below did not survive contact with real
> flies: at the `min_active_time` values users naturally pick (120–300 s, mirroring
> `min_inactive_time`) it delivered ~0 stimuli. The "Deferred" item at the bottom of this
> file is now implemented, as a binned duty cycle rather than a grace period.

## Goal

Add a fifth closed-loop trigger that mirrors Inactivity but fires on *activity*:
deliver a stimulus after *n* seconds of sustained movement, with probability *P*.

## Design decisions

- **Continuous bout, strict mirror.** The bout clock counts up while the animal is moving
  and resets to zero on any non-moving frame. Chosen deliberately over a cumulative /
  sliding-window variant.
  - Consequence: `_has_moved()` reports `False` when the animal is not spotted in a frame,
    so a micro-pause, a grooming bout, or a tracking dropout restarts the count. The
    trigger is meaningful at **short thresholds (seconds)** — hence `min_active_time`
    defaults to **10 s**, not the 120 s that `min_inactive_time` uses.
- **Time restriction is now a modifier, not a trigger type.** Previously
  "Time-restricted inactivity" was its own dropdown entry, which only scaled because
  inactivity was the sole trigger it wrapped. Adding Activity would have forced a
  `time_restricted_activity` entry too, and every future trigger would double the list.
  It is now a checkbox that composes with *any* trigger — like `stimulus_probability`.

## Changes

- `stimulators/triggers.py`
  - New `MovementBoutTrigger` base holding `_has_moved()`, the probability draw, and the
    bout clock. Polarity picked by `_fires_when_moving`. `InactivityTrigger` and the new
    `ActivityTrigger` are now ~10 lines each and cannot drift apart.
  - New `ScheduledTrigger`: decorator that gates *any* trigger to a daily window.
  - `TimeRestrictedInactivityTrigger` is now a thin **deprecated** subclass of
    `ScheduledTrigger`. Kept (with its `"time_restricted"` registry key) so configs saved
    before this change keep running; removed from the UI dropdown.
  - `TRIGGER_REGISTRY` gains `"activity"`.
- `stimulators/composed_stimulator.py`
  - `trigger_type` gains **Activity**; new `min_active_time` and `time_restricted` args;
    daily-schedule fields now `depends_on` the checkbox rather than the dropdown.
  - Replaced the `if/elif trigger_type == ...` kwargs chain with signature introspection.
    That chain **failed open**: `TRIGGER_REGISTRY.get()` succeeds for a new key, so the
    `ValueError` guard never fires, and a forgotten `elif` would silently build the
    trigger with all defaults and discard the user's parameters. Triggers now wire
    themselves up from their own `__init__` signature.

## Not changed

Frontend is fully data-driven off the backend `_description` (`isArgumentVisible()` reads
`depends_on` generically; `getFilteredActionOptions()` only filters `action_type`;
`"type": "boolean"` already renders as a checkbox). No JS, HTML, API, or `tracking.py`
changes were required.

## Verification

- 815 unit tests pass. (`test_light_daemon.py::TestRampWalker::
  test_ramp_down_visits_intermediate_values` fails, but **pre-existing** — confirmed
  failing on pristine HEAD with the stimulator changes stashed.)
- Drove `ComposedStimulator(trigger_type="activity")` frame-by-frame against a mock
  tracker: fires at t=7 s on a 10 s walking bout with `min_active_time=5`; a single pause
  mid-bout defers it; a stationary animal never fires; `time_restricted=True` wraps it in
  a `ScheduledTrigger` and silences it outside the window.
- Confirmed through the real serving path (`ControlThread.user_options()`, which reads
  `__dict__["_description"]`) that Activity reaches the browser with its `depends_on`
  wiring intact and the payload stays JSON-serialisable.

## Discovered during work

- `tests/unit/test_composed_stimulator.py` and `tests/unittests/test_composed_stim.py` are
  **duplicate coverage of the same code** in two directories. Both had to be updated. Worth
  consolidating separately.
- `ComposedStimulator` is still absent from `multi_stimulator.py`'s `stimulator_classes`
  map, so it cannot be used inside a MultiStimulator sequence. Pre-existing.
- `MidlineCrossingTrigger` draws its probability with `<` while every other trigger uses
  `<=`. Pre-existing inconsistency; left alone.

## Deferred

Cumulative / pause-tolerant activity accumulation. If the strict mirror proves too twitchy
on real flies, `MovementBoutTrigger` is the place to add a `max_pause_s` grace period, and
it would then apply to both polarities for free.
