# Timed stop for tracking — unify with the video autostop

Date: 2026-08-18
Issue: [#226 "Automatic Stop Date for Tracking"](https://github.com/gilestrolab/ethoscope/issues/226)

> "It would be great to be able to set an automatic stop date/time instead of manually
> having to press stop. For me, I would have to drive to the lab on off days to ensure
> that the experiment stops on time."

## 1. What exists today

Video recording already has an autostop; tracking has none.

| | video recording | tracking |
|---|---|---|
| option group | `time_control` → `timedStop` (`src/ethoscope/ethoscope/control/record.py:552`, wired at `:631`) | absent |
| mechanism | `threading.Timer(countdown, self.stop)` (`src/ethoscope/ethoscope/control/record.py:805`) | — |
| input | one `str` field, `DD:HH:MM` **duration** | — |
| reported in `_info` | `autostop` (the raw `DD:HH:MM` string) | — |
| shown in UI | `src/node/static/pages/ethoscope.html:153` (only inside the `recording` block) | — |

### Defects in the existing implementation

These are the reasons to rebuild rather than copy-paste the recorder's timer into `ControlThread`:

1. **Duration only, no date.** The issue explicitly asks for a *stop date/time*. `DD:HH:MM`
   forces the user to do the arithmetic, and the arithmetic is wrong if the start is delayed.
2. **The timer is never cancelled.** `ControlThreadVideoRecording.stop()`
   (`src/ethoscope/ethoscope/control/record.py:821`) drops the `Timer` handle. A manual stop
   leaves a live non-daemon timer that later fires `stop()` on the dead controller and
   rewrites `recording.info` for a session that already finished, and blocks interpreter exit.
3. **Wall-clock drift.** The countdown is computed once at start. The node pushes clock
   corrections to devices (`/update/<id>/datetime`, see the auto-correct loop in
   `updateTimestampDisplay`), so a one-shot timer and the device clock disagree after a
   correction. A stop *date* must be re-evaluated against `time.time()`, not slept through.
4. **Nothing is exposed but a string.** `_info["autostop"]` is the user's input echoed back;
   there is no scheduled-stop timestamp, so the UI cannot show "stops at 09:00 on Friday" or
   a live countdown, and nothing else on the node can reason about it.
5. **No way to change your mind.** The countdown is fixed at start. Extending a run means
   stopping and restarting it, which is exactly what the user is trying to avoid.

### Two latent issues this feature will expose

6. `ControlThread.run()` has `# self.stop()` commented out
   (`src/ethoscope/ethoscope/control/tracking.py:1473`). If the monitor loop ever ends by
   itself, the thread dies with `status == "running"`. Our design avoids this (the stop is
   *driven* by `stop()`, which then stops the monitor) but the dead code should go.
7. The `datetime` argument type is declared in `DescribedObject`
   (`src/ethoscope/ethoscope/utils/description.py`) and rendered by both modals, but **no
   backend class uses it**, and the two start paths disagree about its wire format:
   `start_recording` unwraps `[Date, value]` arrays (`ethoscopeController.js:1352`) while
   `start_tracking` only unwraps `{formatted: ...}` objects (`ethoscopeController.js:993`).
   The first real consumer of `datetime` has to fix this.

## 2. Design

One harness, in the shared base class, driven by an **absolute stop timestamp**.

### 2.1 `TimedStop` — one described object for both control threads

New module `src/ethoscope/ethoscope/utils/scheduling.py` (device package only; no node
dependency). `record.py` already imports from `tracking.py`, so a third module is the only
placement that both can import without a cycle.

```python
class TimedStop(DescribedObject):
    """Resolves user input into an absolute unix timestamp at which to stop."""
    _description = {
        "overview": "Stop the experiment automatically, after a fixed duration or at a "
                    "given date and time. Leave on 'Never' to stop it by hand.",
        "arguments": [
            {"type": "dropdown", "name": "mode", "description": "Automatic stop",
             "options": [{"value": "never",    "text": "Never - I will stop it myself"},
                         {"value": "duration", "text": "After a fixed duration"},
                         {"value": "datetime", "text": "At a date and time"}],
             "default": "never"},
            {"type": "str", "name": "duration",
             "description": "Run for Days:Hours:Minutes", "default": "00:00:00",
             "depends_on": {"mode": ["duration"]}},
            {"type": "datetime", "name": "stop_at",
             "description": "Stop at", "default": "",
             "depends_on": {"mode": ["datetime"]}},
        ],
    }

    def resolve(self, start_time):
        """Return the unix timestamp to stop at, or None for 'never'."""
```

- `depends_on` conditional visibility is already supported
  (`src/node/static/js/controllers/ethoscopeFormService.js:437`), so only the relevant field shows.
- `stop_at` travels as a **unix timestamp**, never as a naive local-time string. The browser
  knows the user's timezone, the device does not; converting in the browser is the only place
  the answer is unambiguous.
- Validation happens in `__init__` (bad `DD:HH:MM`, a `stop_at` in the past) so the run is
  refused at start with a readable error rather than at some later point.
- Keep the name `timedStop` as a module-level alias so JSON payloads saved from the current
  UI (`{"time_control": {"name": "timedStop", ...}}`) still resolve through the `eval()` in
  `_parse_one_user_option` (`src/ethoscope/ethoscope/control/tracking.py:679`).

### 2.2 The harness lives in `ControlThread`

`ControlThreadVideoRecording` subclasses `ControlThread`, so put the machinery in the base
(`src/ethoscope/ethoscope/control/tracking.py`) and let the recorder inherit it:

- `time_control` → `[TimedStop]` added to `ControlThread._option_dict` (`:210`); the recorder's
  own `time_control` entry (`record.py:631`) then just points at the same class.
- `_arm_autostop(start_time)`: resolves the timestamp, stores `self._autostop_at`, starts a
  single **daemon** supervisor thread; no-op when mode is `never`.
- `_cancel_autostop()`: called from both `stop()` implementations; sets an `threading.Event`
  the supervisor waits on, so it exits promptly and never fires on a dead controller.
- The supervisor is a `while not event.wait(POLL)` loop comparing `time.time()` against
  `self._autostop_at`, **not** a one-shot sleep. This is what makes it correct across clock
  corrections and what allows the target to be changed while running (§2.4).
  `POLL` of 20 s is ample for a multi-day experiment and costs nothing.
- When it fires it calls `self.stop()` — the same entry point as the user's stop button, so
  tracking gets its clean path (`Monitor.stop()` → `_force_stop` → loop breaks → result writer
  closed by its context manager → cache finalised) and recording gets its `recording.info`
  marker. Nothing new needs to know how to shut anything down.
- Record the reason: pass through to `finalize_cache(..., stop_reason="autostop")`
  (`src/ethoscope/ethoscope/control/tracking.py:1737`) so the database says whether a run ended
  by hand, by timer, or by error.

### 2.3 What the device reports

Extend `_info` in both control threads:

- `autostop_at`: unix timestamp of the scheduled stop, or `None`.
- `autostop`: keep the existing human string for backwards compatibility with
  `ethoscope.html:153`.

One timestamp is all the UI needs to render both an absolute date and a live countdown.

### 2.4 Changing or cancelling a running experiment

New listener action `set_autostop` (`src/ethoscope/scripts/device_listener.py:145`) plus the
matching branch in `controls()` (`src/ethoscope/scripts/device_server.py:340`). It re-arms the
supervisor with a new target, or clears it. This is the part that actually solves the
reporter's problem for a run already under way.

**Correction (found in Stage 2):** this section originally claimed no node change was needed,
because the proxy route `/device/<id>/controls/<instruction>`
(`src/node/ethoscope_node/api/device_api.py:62`) is generic. It is, but
`Ethoscope.send_instruction` validates the instruction against an `ALLOWED_INSTRUCTIONS`
whitelist first (`src/node/ethoscope_node/scanner/ethoscope_scanner.py:52`) and raises
`ValueError: Unknown instruction` for anything not in it. The whitelist needs the new entry.

## 3. Frontend

### 3.1 The argument renderer is duplicated three times

`src/node/static/pages/ethoscope.html` renders option arguments in three near-identical
blocks — stimulator (`:1013`), tracking (`:1096`), recording (`:1299`) — and they have
drifted apart. Recording supports `filepath`, `number`, `str`, `date_range`, `datetime`;
tracking additionally supports `dropdown`, `boolean`, `select`, `str+options`. A `TimedStop`
with a `mode` dropdown would therefore render in the tracking modal and render *nothing* in
the recording modal.

Fix by extraction, not by a fourth copy: pull the argument inputs into
`src/node/static/pages/partials/option-argument.html` and `ng-include` it from all three
sites, aliasing the model root with `ng-init="argModel = selected_options.recording[name]['arguments']"`
(and the tracking / stimulator equivalents) so the partial only ever writes `argModel[arg.name]`.
Every type becomes available everywhere, and the next argument type is added once.

### 3.2 Unify the datetime wire format

`start_tracking` and `start_recording` (`ethoscopeController.js:987` and `:1347`) both begin
with a near-identical argument-normalisation loop that handles different cases. Extract one
`normaliseArguments(option)` into `ethoscopeFormService` handling `{formatted}` objects,
`[Date, value]` arrays and `datetime` → unix seconds, and call it from both. Fixes defect 7.

### 3.3 Display

- Move the autostop block out of the `recording`-only section of
  `src/node/static/pages/ethoscope.html:153` so it shows for `status == 'running'` too.
- Show the absolute date **and** a countdown, driven off `device.autostop_at`. Add a
  `ethoscope.remainingtime(t)` beside the existing `ethoscope.elapsedtime(t)`
  (`ethoscopeController.js:862`) rather than reformatting the `DD:HH:MM` string.
- An "extend / cancel" control next to it, posting to `set_autostop` (§2.4).

## 4. Out of scope (recorded, not done)

- **Node-side backstop.** Not needed: if the device server dies the `ControlThread` dies with
  it and the experiment stops anyway, so a device-local timer has no coverage gap to fill.
- **Timed *start*.** The same `TimedStop` shape would express it, but nobody has asked.
- **Post-stop actions** (trigger a backup / power off on autostop). `_auto_SQL_backup_at_stop`
  (`src/ethoscope/ethoscope/control/tracking.py:206`) is the existing hook if we ever want it.

## 5. Tasks

### Stage 1 — device backend  ✅ done 2026-08-18
- [x] `TimedStop` + `format_countdown` + `timedStop` alias in
      `src/ethoscope/ethoscope/utils/scheduler.py`. Put there rather than in a new
      `scheduling.py`: that module already owns `Scheduler` / `DailyScheduler`, and two
      files a letter apart would have been a trap.
- [x] `ControlThread`: `time_control` in `_option_dict`, `_init_autostop_state` /
      `_arm_autostop` / `_set_autostop` / `_cancel_autostop` / `_autostop_supervisor`,
      daemon supervisor, `autostop_at` in `_info`, `stop_reason="autostop"`.
- [x] `ControlThreadVideoRecording`: local `timedStop` and the uncancellable
      `threading.Timer` deleted; both now come from the shared harness. The recording
      marker gained a `stop_reason` field for parity with the tracking cache.
- [x] Removed the dead `# self.stop()` in `ControlThread.run()` (defect 6).
- [x] 36 unit tests: `tests/unit/test_timed_stop.py` (new) plus a `stop_reason` case in
      `tests/unit/test_recording_marker.py`.

**Decisions taken during implementation**

- **No `mode` dropdown.** The design called for one, but the recording modal renders only
  5 of the 9 argument types the tracking modal does, and `dropdown` is not among them — a
  mode dropdown would have rendered as nothing at all in the recording form until Stage 3
  landed. `TimedStop` therefore takes two plain `str` fields, `duration` and `stop_at`, with
  `stop_at` winning if both are set. Both modals render `str` today, so **Stage 1 ships
  without touching the frontend and without a regression**. Stage 3 can add the dropdown
  once the shared partial exists.
- **`stop_at` accepts a unix timestamp as well as a date string**, so Stage 3 can switch the
  field to the `datetime` picker without a backend change.
- **Class-level defaults for the four `_autostop_*` attributes.** `__del__` calls `stop()`,
  which cancels the autostop, and `__del__` runs on objects whose `__init__` raised part
  way through. The defaults make `stop()` safe on any instance.
- **`_set_autostop` takes a `reference` time.** `format_countdown` truncates, which is right
  for a "time left" readout but made a 24 h run report as `00:23:59` when measured from a
  moment after the start. Caught by a test.

### Stage 2 — device API  ✅ done 2026-08-18
- [x] `ControlThread.set_autostop(data)`, sharing `_arm_autostop` via a `kwargs` override.
      A `duration` is counted from **now** ("run for one more day"); `stop_at` is absolute;
      empty cancels.
- [x] `set_autostop` action in `device_listener.py`, guarded on an active run and
      converting `TimedStopError` into a readable `ERROR:` string rather than a traceback.
- [x] `set_autostop` branch in `device_server.py`, returning the device info with the new
      `autostop_at` (plus an `error` field when the request was refused).
- [x] `set_autostop` added to the node's `ALLOWED_INSTRUCTIONS` — see the correction in §2.4.
      Deliberately **not** added to `_STOP_INTERVENTION_INSTRUCTIONS`: it reschedules a stop,
      it does not perform one, and recording it as an intervention would make the scanner
      suppress the alert for a later run termination.
- [x] 19 more tests in `test_timed_stop.py` (the method and the listener dispatch) and 3 in
      the node's `test_ethoscope_scanner.py`.
- [x] Verified end to end over the real socket protocol against a live listener: schedule,
      reschedule, cancel, fire, and refusal once stopped.

**Key property, tested:** a malformed or already-past request leaves the existing schedule
running untouched. `TimedStop` construction and `resolve()` both raise before `_set_autostop`
is reached, so a typo while extending a run cannot silently drop the stop the user already
has — nor stop the run.

### Stage 3 — frontend  ✅ done 2026-08-18
- [x] `static/pages/partials/option-argument.html`, included by the tracking and
      recording modals with `ng-init="argModel = …; argSiblings = …; argForm = '…'"`.
      Recording gains `select`, `dropdown`, `boolean` and `str`-with-options, which it
      silently dropped before.
- [x] `normaliseArguments()` / `normaliseArgumentValue()` in `ethoscopeFormService`,
      called from `start_tracking`, `start_recording` **and** the stimulator sequence,
      which had a third copy of the same loop. Handles `{formatted}` objects, moments,
      `Date`s and `[label, value]` pairs. Fixes defect 7.
- [x] `ethoscope.remainingtime()`; the scheduled stop shown for `running` as well as
      `recording`, as an absolute date **and** a live countdown driven off
      `autostop_at`; `argIsMissing()` helper for the partial's required-field message.
- [x] `#autostopModal`: +6h / +1 day / +2 days / +1 week quick buttons, a field for a
      specific time, and "Cancel the automatic stop". Also offered when no stop is set,
      so a run already going can have one scheduled. Always sends an absolute
      timestamp, so what is on screen is what the device is asked for.
- [x] Dropped `$scope.device.countdown`, which nothing read.

**Only two callers, not three.** The plan said all three modals. The stimulator block
(`ethoscope.html:1039`) is a Bootstrap-styled card - `form-control` on every control,
`placeholder="{{arg.default}}"`, its own ids - while the tracking and recording blocks
are plain `<ul>` lists. Folding it in would have meant either restyling that card or
giving the partial style knobs. The two list-shaped callers were the ones that had
actually diverged in *behaviour*, and they are now one copy.

**Verified in a browser** (`localhost` harness loading the real partial through real
Angular, since `device_server.py` hardcodes `/ethoscope_data` and cannot run here
without root):
- all 11 argument types render exactly one control each;
- writes through `argModel` land on the caller's object - `argModel === ` the caller's
  arguments object, no shadowing from `ng-include`'s child scope;
- `arg`, `$index`, `argSiblings` and `argForm` all reach the partial correctly;
- the required-field message is hidden untouched, shown touched-and-empty, hidden once
  filled;
- clean console on load;
- `remainingtime()`, evaluated out of the served controller, gives `null` for no
  schedule, "any moment now" for a past target, and `2 days, 4h, 12min` style otherwise.

Plus a static cross-check that every `ethoscope.*` binding in the template resolves to
a controller function.

### Stage 4 — verification on real hardware  ✅ done 2026-08-18
Run against **ETHOSCOPE_900** (192.168.4.137, imx219 camera) with a node served from this
working tree. The device was moved onto the branch by fetching a git bundle over SSH into
its own `/opt/ethoscope` — nothing was pushed anywhere public, and the original branch
(`fix/222-decouple-exposure-from-maxfps` at `a2c27452`) is recorded for restoring it.

- [x] Device suite and node suite pass.
- [x] **Recording, 2-minute duration.** Armed a stop at 17:53:12, stopped itself at 17:53:16
      (poll interval, not drift). `recording.info` carried
      `"status": "completed", "stop_reason": "autostop"`, and a 30 MB `.h264` chunk was
      written. No timer thread left behind.
- [x] **Tracking, absolute stop.** `stop_at` sent as a unix timestamp, accepted verbatim,
      ran, and stopped itself at 17:57:18 against a 17:57:17 target - one second. The run's
      cache recorded `stopped_gracefully: True`, `stop_reason: autostop`.
- [x] **Extend from the UI on a running experiment.** "+6 hours" moved the stop from
      16:56:51 to 22:56:51 GMT through browser → node → device, without restarting the run.
      This is the reporter's scenario.
- [x] **Cancel from the UI.** Stop cleared, experiment kept running.
- [x] **Schedule from scratch on a running experiment**, via the modal's own field.
- [x] The node needed `set_autostop` in `ALLOWED_INSTRUCTIONS` - confirmed in the live path.

### Stage 5 — interface revision after bench feedback  ✅ done 2026-08-18
Giorgio, watching it run: seconds in the stop time are overkill, and the `DD:HH:MM`
duration format "always bothered me" (his own original design).

- [x] The duration is now **three number fields** - `days`, `hours`, `minutes` - instead of a
      packed `DD:HH:MM` string. Self-describing, validated by the widget, nothing to parse,
      and still able to express both a three-week experiment and a two-minute test recording.
      Out-of-range values are summed rather than refused (36 hours means 36 hours): three
      labelled boxes cannot be misread the way a packed string can.
- [x] `stop_at` drops seconds: `YYYY-MM-DD HH:MM`. Minutes stay, because "stop at 09:30 on
      Friday" is a real thing to want and costs nothing.
- [x] The `DD:HH:MM` string survives as a **deprecated `duration`/`timer` kwarg** with its
      original stricter parse, so configurations saved by earlier versions still start. It is
      no longer offered in the form.
- [x] Re-verified on the device: the recording modal renders three spinners with proper
      ranges, and a run started from the real form with `minutes: 2` armed and fired correctly.

**This is what Stage 3's partial extraction bought.** The revision needed `number` fields in
the recording modal, which is exactly the class of argument that modal used to drop silently.

### Stage 6 — graphical review  ✅ done 2026-08-18
Giorgio, on the screenshot of Stage 5: three number boxes stacked vertically, each with a
sentence of a label, read as three unrelated questions; and the stop time deserved the
calendar widget used elsewhere.

- [x] **A duration is one argument, not three.** New `duration` argument type, rendered by
      the shared partial as one label and three boxes on a row with small unit captions.
      `TimedStop` takes `run_for={"days":…, "hours":…, "minutes":…}`; the flat `days`/
      `hours`/`minutes` kwargs stay, because they read better when driving the API by hand
      (`{"days": 2}`), and `run_for` simply overrides them.
- [x] **`stop_at` is now type `datetime`** — the same calendar-and-clock picker used
      elsewhere. This is the first working use of that type in the codebase.
- [x] CSS for the duration row in `main.css`, with `!important` to match the surrounding
      modal rules: `.modal label { display: block }` is what stacked the units, and
      `.modal input[type=number] { max-width: 250px }` is what made the boxes enormous.

**The `datetime` type is fixed, not worked around.** Stage 3 diagnosed it and left it alone:
the picker's `$parsers` writes a **moment**, while both seeding paths wrote a
`[label, value]` **array**, which the `$formatters` then handed to `moment()` as a list of
date parts. Both seeders now call a new `momentOrNull()`, and `normaliseArgumentValue`
turns the moment back into a unix timestamp on submit. Two further bugs surfaced while
fixing it:
- `updateUserOptions` seeds arguments inside a `setTimeout`, where `this` is not the
  service. The pre-existing `this.ensureMomentLocale()` call there had never run. Captured
  as `self`.
- A picker the user *clears* writes `{startDate: null, endDate: null}` rather than null,
  which would have reached the device as a date. Normalised to an empty string.

### Remaining
- [ ] Restore ETHOSCOPE_900 to `fix/222-decouple-exposure-from-maxfps` (`a2c27452`) and drop
      the `test-timed-stop` branch, once the bench work is finished.
- [ ] Squash the `wip: interface feedback` commit into the stage commits before this goes out.
- [ ] Update `CLAUDE.md` / `README.md` if the option needs documenting.

## Discovered during work

- `_option_dict` is a **class** attribute mutated by `_parse_user_options`, so option state is
  shared across instances within a process. Pre-existing; do not rely on per-instance state.
- **`datetime` is still unused, and now diagnosed.** `TimedStop.stop_at` stayed a `str`
  rather than switching to the picker, because the widget disagrees with its own
  initialiser: with `singleDatePicker`, the directive's `$parsers` writes a **moment** to
  the model (`angular-daterangepicker.js:190`), while `updateUserOptions` seeds datetime
  args as a `[label, value]` **array** (`ethoscopeFormService.js:114`), which the
  `$formatters` then hands to `moment()` as if it were a date part list. Whoever switches
  a field to `datetime` must make the initialiser write a moment (or null for an empty
  default) first. `normaliseArgumentValue` already handles every one of these shapes, so
  the submit half is done. Also note `autoUpdateInput: true` in the inline picker options:
  for an *optional* field it would set a value merely because the user opened the picker.
- **`initDateRangePicker` does not exist.** `ethoscope.html:1092`, in the stimulator card,
  calls it from `ng-click`; nothing defines it, so the clock icon there is a no-op. Angular
  swallows the call silently. Pre-existing (68ceb318), untouched, and in the one block the
  partial extraction deliberately left alone.
- The node has **no JavaScript test infrastructure** — no karma, jest or spec files. The
  frontend work here was verified with a browser harness and a throwaway node script rather
  than committed tests. Standing up a JS runner would be its own task.
