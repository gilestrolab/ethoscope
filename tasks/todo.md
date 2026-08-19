# Node config-folder location — review & fix

Date: 2026-06-08

## Problem (confirmed)

1. **Wrong default.** Wizard offers `/etc/ethoscope`; it should be `{ETHOSCOPE_DATA}/config`.
2. **Choice ignored.** Wizard collects `configDir` (and marks it required) but `processBasicInfo`
   never sends it and `_setup_basic_info` never consumes it — the value is discarded.
3. **Root cause.** `config_dir` is a *bootstrap* parameter (must be known before the config file
   is read), resolved only at server start from `-c` / `ETHOSCOPE_CONFIG_DIR`, and **never
   persisted**. The location is also **duplicated/hardcoded** as `/etc/ethoscope` across many
   independent services (backup tools, cronie, updater `NODE_DB_PATH`, tunnel.env, SSH keys).

## Design decisions (approved by user)

- **Coherent single source of truth** across services.
- **Wizard choice persists to a bootstrap env file + migrates existing files + prompts restart.**

## Key architecture

- **Bootstrap anchor stays at a FIXED path:** `/etc/ethoscope/environment` (tiny pointer file with
  `ETHOSCOPE_DATA_DIR` / `ETHOSCOPE_CONFIG_DIR`). It is the only thing kept at the fixed path —
  this breaks the chicken-and-egg (can't store the config dir inside the config file).
- **All config content** (`ethoscope.conf`, `ethoscope-node.db`, `keys/`, `tunnel.env`) lives under
  the config dir, default `{ETHOSCOPE_DATA}/config` = `/ethoscope_data/config`.
- **Resolution order** (everywhere): explicit arg/flag → `ETHOSCOPE_CONFIG_DIR` env →
  `{ETHOSCOPE_DATA_DIR or /ethoscope_data}/config`.

## Tasks

### Stage 1 — central resolver (backbone) + tests
- [ ] New `src/node/ethoscope_node/utils/paths.py`: `resolve_data_dir`, `resolve_config_dir`,
      `write_bootstrap_env`, `migrate_config_dir`, constants `DEFAULT_DATA_DIR`, `BOOTSTRAP_ENV_FILE`.
- [ ] Unit tests for the resolver + env-file write + migration.

### Stage 2 — make the default `{ETHOSCOPE_DATA}/config`
- [ ] `scripts/server.py`: config default = `resolve_config_dir(data_dir=env_data_dir)`; always
      propagate to module globals in `__init__` (not only when explicitly provided).
- [ ] `utils/configuration.py:26`, `utils/etho_db.py:39`, `scanner/ethoscope_scanner.py:81,1456`:
      defaults via `resolve_config_dir()` instead of literal `/etc/ethoscope`.
- [ ] `api/setup_api.py:130` (`_get_system_info`): default via `resolve_config_dir()`.

### Stage 3 — make the wizard choice take effect
- [ ] Frontend `installationWizardController.js`: `processBasicInfo` sends `configDir` + `dataDir`;
      init default + step-2 placeholder → `/ethoscope_data/config`; surface restart-required notice.
- [ ] `api/setup_api.py` `_setup_basic_info`: validate/create new config dir, migrate old→new,
      `write_bootstrap_env`, return `restart_required: true` when the dir changed.
- [ ] Tests for the new backend handler (config-dir change, migration, env write).

### Stage 4 — propagate single source of truth to sharing services
- [ ] `scripts/backup_tool.py:274`, `scripts/rsync_backup_tool.py:349`: argparse default via resolver.
- [ ] Backup units (`ethoscope_backup_unified/sqlite/video/mysql.service`): add
      `EnvironmentFile=-/etc/ethoscope/environment`.
- [ ] `accessories/databases/retire_inactive_devices.py`, `accessories/migrate_user_pins.py`:
      argparse default via env (duplicated tiny fallback — accessory scripts).
- [ ] `src/updater/helpers.py:21` `NODE_DB_PATH`: derive from env with duplicated fallback
      (package independence — updater must not import ethoscope_node); ensure updater unit has the env file.
- [ ] Confirm cronie `check_databases.sh` already sources the env file (it does; results dir only).

### Verification
- [ ] `python run_tests.py --package node`
- [ ] Smoke: start server with no env (default `/ethoscope_data/config`) and with
      `ETHOSCOPE_CONFIG_DIR` set; check `/setup/system-info` reports the right dir.

## Review (done 2026-06-08)

Implemented all four stages. Single source of truth = `ethoscope_node.utils.paths`
(node package) + the duplicated 3-line fallback in standalone/independent consumers
(updater, virtual_sensor, accessory scripts) fed by the bootstrap env file.

Files changed:
- **New**: `utils/paths.py` (+ `tests/unit/utils/test_paths.py`, 13 tests).
- **Default → {DATA}/config**: `configuration.py`, `etho_db.py`, `ethoscope_scanner.py`
  (2 ctors), `scripts/server.py` (resolve once in `__init__`, help text), `setup_api.py`
  (`_get_system_info`).
- **Wizard persists choice**: `setup_api.py` `_setup_basic_info` (create+migrate+env+restart flag),
  `installationWizardController.js` (sends config/data dir, restart notice, default),
  `step-2-basic-setup.html` (placeholder/help). Tests added.
- **Sharing services**: backup tools help text + 4 backup units get `EnvironmentFile`;
  updater `helpers.py` `NODE_DB_PATH`, `ethoscope_update_node.service`; accessories
  `retire_inactive_devices.py`, `migrate_user_pins.py`; virtual sensor script + unit.
- **Fixed-path files** (pinned by a unit's `EnvironmentFile=`): bootstrap `environment` and
  `tunnel.env` are excluded from migration so they never move.

Verified: 1559 node unit tests + 9 device virtual-sensor tests pass; resolution smoke-tested
in all three modes (default / data-dir override / explicit); package independence intact.

## Notes / risks
- Backend writing `/etc/ethoscope/environment` and migrating into `{ETHOSCOPE_DATA}/config` needs
  write perms; on a fresh node the service has them. Log clearly on failure.
- A running server cannot relocate already-loaded config → restart required after a change.
- `migrate_config_dir` must be idempotent and never overwrite newer files at the destination.

---

# Smart incubators — node integration (Phase 1: monitor-only)

Date: 2026-06-12
Plan: `~/.claude/plans/noble-drifting-brook.md`

- [x] Firmware: incubator also serves the etho_sensor API (`GET /` JSON, `/id`, `POST /set`),
      advertises `_incubator._tcp` + `_sensor._tcp`, status page moved to `/status`. Compiles
      clean (d1_mini, RAM 42%/flash 39%). FW bumped to 3.1.0-wifi.
- [x] `IncubatorScanner`/`Incubator` (`_incubator._tcp`, polls `/telemetry`) + server.py wiring.
- [x] DB `hostname` binding column on incubators (migration 10) threaded through add/update.
- [x] `incubator_api`: GET `/incubators/live`, GET `/incubators/merged`, POST `/incubator/bind`
      (binds record ↔ unit and pushes incubator name into the unit's sensor `location`).
- [x] Incubators page: live status column, discovered-unbound banner, link-unit control (15s poll).
- [x] Tests: scanner / etho_db hostname / incubator_api — 33 new, all green; 528 node-unit regression green.

## Review
- The unit is discovered on two channels: `SensorScanner` (unchanged) handles CSV + temp alerts;
  the new `IncubatorScanner` handles incubator telemetry. No node sensor-code changes.
- Phase 2 (not done): push `set_temp`/light schedule DB→firmware (node already authoritative for
  the per-ethoscope daylight LEDs). Open: firmware is fixed 24h (no T-cycle); panel-vs-LED policy.

## Discovered during work
- arduino-cli needs the sketch folder name to match the `.ino`; `firmware/` ≠
  `client_firmware_esp8266.ino`, so `build.sh`'s `arduino-cli compile .` fails in place — build
  by copying into a correctly-named temp sketch dir (or rename). Worth fixing in build.sh later.

---

# Smart incubators — node integration (Phase 2: schedule push + fade + decoupled subpackage)

Date: 2026-06-13
Plan: `~/.claude/plans/i-think-we-should-nested-puppy.md`

## Goals

1. Push the node's variable-T light schedule (`lights_on/off/period/anchor`) to incubator firmware as source of truth.
2. Add fade-in/out (incubator-only — ethoscope GPIO17 is not HW-PWM capable).
3. Decouple incubator control: self-contained subpackage under `ethoscope_node.incubators`, `[full]` extras gates the heavy node stack.

## Tasks

### Stage 1 — subpackage scaffold (pure-Python, no network)
- [ ] `ethoscope_node/incubators/__init__.py` + `schedule.py` (port `should_light_be_on`, payload builder) + tests
- [ ] `ethoscope_node/incubators/firmware_client.py` (requests-based) + tests
- [ ] `ethoscope_node/incubators/storage.py` (ABC + `SQLiteIncubatorStorage`) + tests

### Stage 2 — discovery + reconciliation
- [ ] `ethoscope_node/incubators/scanner.py` (with duplicated BaseDevice/DeviceScanner) + tests
- [ ] `ethoscope_node/incubators/reconciler.py` (Timer-based drift re-push) + tests

### Stage 3 — routes + standalone server + SPA
- [ ] `ethoscope_node/incubators/routes.py` (framework-agnostic handlers) + tests
- [ ] `ethoscope_node/incubators/bottle_app.py`
- [ ] `ethoscope_node/incubators/standalone.py` (CLI entry)
- [ ] `ethoscope_node/incubators/web/{index.html,app.js,style.css}` minimal SPA

### Stage 4 — packaging
- [x] `src/node/pyproject.toml`: keep default install = full node (incubator-only is fringe), add console-script `ethoscope-incubator-server`, document manual minimal-install recipe in pyproject header
- [x] Makefile / systemd units / Docker / migrate_to_unified_structure.sh: unchanged from Phase 1 (default install pulls everything)

### Stage 5 — node integration
- [ ] `ExperimentalDBIncubatorStorage` adapter; refactor `api/incubator_api.py` to thin bridge
- [ ] `scanner/incubator_scanner.py` becomes re-export shim
- [ ] Wire `Reconciler` lifecycle into `scripts/server.py`

### Stage 6 — DB migration + auto-push
- [ ] `etho_db.py` migration 11 adds `fade_in_seconds` + `fade_out_seconds`; addIncubator/updateIncubator accept them
- [ ] `setup_api.py`: extend `_LOCKED_INCUBATOR_FIELDS`; auto-push after add/update/reset-anchor
- [ ] Tests

### Stage 7 — firmware
- [ ] `incubator.h` Config: drop `mode`; add `light_period_minutes`, `light_cycle_anchor`, `fade_in_ms`, `fade_out_ms`
- [ ] `Config.cpp/h`: parsers + bump persisted-config schema version (reset old configs to defaults)
- [ ] `LightControl.cpp/h`: drop modes; new `isLightOn` (wall-clock + T-cycle); per-direction fade step
- [ ] `Api.cpp/h`: `/config` accepts new fields; `/telemetry` reports them; drop mode/light_target hints
- [ ] `version.h`: bump to 3.2.0-wifi
- [ ] `README.md`: update API table + curl examples + note mode removal
- [ ] Compile-check

### Stage 8 — node frontend
- [ ] `incubators.html` + `incubatorsController.js`: fade inputs, push-now button, drift badge

### Verification
- [x] Default install `pip install -e src/node/` pulls the full node stack (cherrypy 18.10.0, etc.); IncubatorAPI bridge imports cleanly
- [x] Manual minimal recipe (fresh venv, `pip install --no-deps -e src/node` + `pip install bottle zeroconf requests`) → subpackage imports; CherryPy import fails; standalone `ethoscope-incubator-server` starts, SPA loads, REST round-trips fade fields
- [x] `pytest src/node/ethoscope_node/incubators/tests` → 127 green (schedule, firmware_client, storage, scanner, reconciler, routes, bottle_app)
- [x] Full node `pytest src/node/tests/` → 1734 green (the 60 in test_target_detection_analysis.py blocked by an unrelated numpy/MKL system-level link error, not by Phase 2 code)
- [x] Firmware compile via `build.sh`: clean, RAM 42% / flash 39% (d1_mini, esp8266 3.1.2), FW 3.2.0-wifi build #5
- [x] Smoke: standalone server adds an incubator with fade=30/45/80, GET /api/incubators returns the round-tripped record

## Review (2026-06-13)

Phase 2 implemented across nine stages.

**Net code shape:**
- New self-contained subpackage `ethoscope_node/incubators/` (1.6 kLOC + 600 LOC of tests):
  schedule.py (T-cycle algorithm + firmware payload builder), firmware_client.py,
  storage.py (ABC + SQLite impl), scanner.py (duplicated minimal Base{Device,Scanner}),
  reconciler.py (Timer-based drift re-push), routes.py (framework-agnostic handlers),
  bottle_app.py, standalone.py (CLI entry), web/ (vanilla-JS SPA). **Zero
  `ethoscope_node.*` imports** outside this package.
- `pyproject.toml`: default install unchanged (full node stack); added
  console-script `ethoscope-incubator-server` for the rare incubator-only
  deployment + documented the manual `--no-deps + bottle/zeroconf/requests`
  recipe in the pyproject header.
- Node-side bridge: `api/incubator_storage_adapter.py` wraps ExperimentalDB into the
  ABC; `api/incubator_api.py` is now a thin handler-registration shim; old
  `scanner/incubator_scanner.py` is a re-export shim.
- Reconciler lifecycle wired into `scripts/server.py`.
- DB migration 11 adds `fade_in_seconds`, `fade_out_seconds`, `max_light` to incubators.
- `setup_api.py` `_LOCKED_INCUBATOR_FIELDS` extended; add/update/reset-anchor each
  trigger best-effort auto-push via `IncubatorAPI.push_schedule_to_unit`.
- Firmware FW 3.1.0 → 3.2.0-wifi: dropped DD/LL/DL/MM modes; added
  `light_period_minutes`, `light_cycle_anchor`, `fade_in_ms`, `fade_out_ms` to Config;
  new `isLightOn()` port of `should_light_be_on` (wall-clock + T-cycle); per-direction
  fade step. `POST /command set_light` kept as transient debug override.
- Node UI: edit modal gains Fade-in/Fade-out/Max-brightness inputs and a "Push now"
  button next to "Link"; controller hydrates+saves the new fields and posts to
  `/incubator/push-schedule`.

**Decoupling proven (manual recipe):** stripped-down venv with
`pip install --no-deps ethoscope_node && pip install bottle zeroconf requests`
runs `ethoscope-incubator-server` end-to-end — no CherryPy, no MySQL connector,
no numpy, no GitPython. The default install stays full for the common case.

**Drift handling:** auto-push on every relevant write + 60 s background reconciliation
that re-pushes when telemetry-reported schedule diverges from storage. Failures are
warn-only.

## Out of scope (deferred)
- Ethoscope-side fade (GPIO17 is not a HW-PWM pin; pairs with WS2812 hardware-rev plan).
- Packaging the standalone as a Debian/Docker artefact (Phase 3).
- Migrating already-deployed firmware configs — bump persisted-config schema, accept
  reset-to-defaults on first boot of new FW.

# Fresh-install setup wizard + incubator report (2026-08-12)

Reported by a user on a freshly reinstalled node (Manjaro LiveCD, ethoscope-node
1.7-7): the wizard's final "Next" did nothing, and adding an incubator failed
with a generic, doubled error message.

## Fixed (all reproduced locally first)
- [x] **Wizard dead-end in reconfigure mode.** `init()` set `totalSteps = 8`
      while the completion screen is step 9, so `nextStep()` was a no-op on the
      last input step: the POST succeeded, the page never changed, and
      `/setup/complete` was never reached. Reconfigure mode never actually
      skipped a step, so the total is now 9 in both modes.
      (`static/js/controllers/installationWizardController.js`)
- [x] **`/setup/reset` was a silent no-op on fresh installs.** The no-config-file
      path shallow-copied `DEFAULT_SETTINGS`, so `_settings["setup"]` *was* the
      class attribute; `complete_setup()` flipped the class default to
      `completed: True`, and every later "restore the defaults" restored the
      polluted values. Now a deep copy. (`utils/configuration.py`)
- [x] **`add_key()` never persisted.** Mutated `_settings` without `save()`; its
      round-trip test only passed because of the pollution above.
- [x] **Dead Back button on the Remote Access step** — `ng-click="goToPreviousStep()"`
      names a function that does not exist. AngularJS evaluates an undefined
      handler as a silent no-op: no page change, no console error, no request.
- [x] **Unactionable incubator error.** `addIncubator()` returns -1 for both
      "name already taken" and "the INSERT failed"; the handler reported a bare
      "Failed to create incubator". It now re-queries on the failure path only
      and names which of the two happened. (`api/setup_api.py`)

## Discovered During Work
- `migrate_legacy_config_dir()` **moves** (`shutil.move`) everything in
  `/etc/ethoscope` into the resolved config dir. Starting a dev server with
  `--configuration <somewhere else>` silently relocates a real node's config.
  Worth a guard or at least a loud warning.
- Failure-path messages across `setup_api.py` are uniformly generic
  ("Failed to create user", ...); the incubator one is fixed, the rest are not.
# Real-time noise diagnostics on the device (2026-08-12)

Step 1 of the plan for #222: measure noise while tracking, surface it through the
node, and record enough context to debug an experiment after the fact. Step 2
(a calibration phase advising on illumination / FPS / gain) builds on the numbers
this step produces and is deliberately out of scope here.

Design decisions taken: show positional jitter *and* sensor noise side by side
(jitter is expected to be driven mainly by sensor noise and by focus blur, which
this step will test rather than assume); per-minute samples go to a new
DIAGNOSTICS table.

## 1a. Measurement primitives (device)
- [ ] Implement `BackgroundModel._bg_sd` as an EWMA of `|img - _bg_mean|` — the
      stub commented out at `adaptive_bg_tracker.py:217`. One array op per frame,
      alongside the mean update that already runs. This is the sensor-noise term.
- [ ] Add a focus/sharpness metric (variance of Laplacian) per ROI, sampled once
      per diagnostics interval rather than per frame. Second candidate cause of
      positional jitter.
- [ ] Positional jitter: 10th percentile of per-frame displacement over the
      existing 250 s rolling buffer, per ROI, then median across ROIs. Most
      animals are quiescent at any moment, so the low percentile is the noise
      floor without needing to know which ones are asleep.
- [ ] Surface the signals already computed and discarded: `prop_fg_pix`,
      `is_ambiguous` rate (`adaptive_bg_tracker.py:510,524`), `is_inferred` rate.
- [ ] Read real exposure/gain via `capture_metadata()`. The current
      "Auto-exposure status" log (`cameras.py:766`) reads `camera_controls`,
      which returns (min, max, default) limits, not actual values.

## 1b. Aggregation and storage
- [ ] Diagnostics aggregator in the monitor loop, once per interval (default 60 s),
      with bounded cost — percentiles over the existing buffer, no new retention.
- [ ] New DIAGNOSTICS table in both the SQLite and MySQL writers:
      `t, fps, exposure_us, gain, brightness, sensor_noise, sharpness, jitter,
      inferred_frac, ambiguous_frac`. ~1440 rows/day against ~21M tracking rows.
- [x] Static acquisition context into METADATA at start: `maxfps_setting`,
      `target_fps`, `gain_setting`, `exposure_decoupled`, `camera_tuning_expected`,
      `camera_tuning_loaded`, `camera_sensor`, `pi_version`, `picamera2_version`,
      `tracker_class`. One queryable field each - `hardware_info` already carried
      some of this, but only as a stringified blob that cannot be compared across
      runs. Collected defensively: a diagnostic must never stop an experiment.

## 1c. Surfacing through the node
- [ ] Include the latest diagnostics sample in the `/data/<id>` payload next to
      `monitor_info`, so the node needs no new endpoint.
- [ ] Indicator in the device status bar beside the hard-drive / response-time
      icons, with the detail on the device page.
- [ ] **No hard alert threshold yet.** Display value and trend, collect across the
      fleet, then set the threshold from the observed distribution. Shipping an
      invented cutoff is how the activity trigger ended up with a rule sitting
      above p99.4 of real behaviour (#224).

## 1d. Validation
- [ ] Unit tests per estimator: synthetic frames with known added noise, synthetic
      position traces with known jitter, deliberately defocused frames.
- [ ] Measure the added per-frame cost on a real device; must stay negligible
      against tracking, which is already the bottleneck.
- [ ] Archive audit (independent, cheap): median `dt` per experiment across
      existing databases, recoverable from the `t` column with no code change.
      Tells us which historical datasets are mutually comparable.

## Attribution experiment (once data exists)
Regress jitter on sensor noise and on sharpness across the fleet. GG's prediction
is that sensor noise dominates; measuring both causes alongside the effect is what
makes that testable rather than assumed.

## Origin of the noise regression: the picamera -> picamera2 migration

Comparing the legacy path (pre-`e2e74f64`) with the current one:

| | legacy picamera | picamera2 today |
|---|---|---|
| exposure | `exposure_mode='auto'` (default) | `ExposureTime: 0` (auto) |
| gain | **auto ISO** | **`AnalogueGain` pinned** |
| white balance | auto, `awb_auto_is_greyworld` in config.txt | `AwbEnable: False` + NoIR tuning file |
| frame rate | `capture.framerate` | `FrameRate` control |

The frame-rate/shutter coupling existed under picamera too - `framerate` limited
shutter speed there as well. What changed is that **pinning AnalogueGain removed
the AE loop's second degree of freedom**: in dim light the old stack raised gain
instead of lengthening exposure, so the FPS ceiling never bound in practice. With
gain fixed, shutter is the only lever and it is capped, so the sensor
under-exposes and the frames get noisy. That, not the FrameRate control by
itself, is the regression.

The fixed gain was deliberate ("Fixed gain to avoid tracking artifacts") - auto
gain destabilises the background model. So the real choice is: give AE more frame
duration (Alice's branch), or let AE use gain within bounds. The step-1
diagnostics are what tell us which regime a device is actually in.

- [x] Record in METADATA which regime applied: exposure policy and configured
      gain are now stamped at experiment start. The *observed* exposure/gain per
      frame still needs the per-minute DIAGNOSTICS table (1b).

## NoIR tuning: make it constant, and fix the sensor mismatch

Ethoscopes cannot exist without a NoIR camera, so the `use_noir_tuning` flag is a
setting that should never be False.

- [ ] Remove the flag: `pi.get_noir_setting` / `pi.set_noir_setting`
      (`pi.py:1381,1399`), its `/etc/ethoscope/use_noir_tuning` file, and the UI
      control. Always apply NoIR tuning.
- [ ] **Select the tuning file from the detected sensor.** It is currently
      hardcoded to `imx219_noir.json` (`cameras.py:694`) while `pi.py:680-689`
      already recognises `ov5647` (NoIR v1) and `imx219` (NoIR v2); Camera Module
      3 is `imx708`. On any non-imx219 device the load fails.
- [ ] **Never fall back silently.** The failure path currently drops to
      `Picamera2()` with default colour tuning, logged as a warning and recorded
      nowhere - two nominally identical ethoscopes can run different AE tuning
      with no trace in the data. Fail loudly, and record the tuning file actually
      loaded in METADATA.

## Bench session results (2026-08-12, ETHOSCOPE_900, Pi 3 + imx219, no flies)

Step 1 is implemented and verified on hardware: 1a (estimators), 1b (DIAGNOSTICS
table + acquisition context in METADATA) and 1c (device page readout) are done.
Alert thresholds remain deliberately unset pending fleet data.

**Reference numbers, empty arena, maxfps=5:** image noise ~0.57 grey levels,
sharpness ~21, jitter ~0.0022 ROI widths, achieved ~4.8 fps.

**Findings**

- [x] Jitter barely moves with illumination: 0.00222 -> 0.00242 (~9 %) across
      room light -> IR-only dark -> LED 100 % -> LED 50 %, while image noise
      changed ~35 %. Early evidence *against* sensor noise dominating jitter -
      but weak, since with no flies only 4-18 ROIs report and they track dust
      and reflections rather than animals. Needs repeating with flies.
- [x] Sharpness groups by illumination *condition*, not by noise: 20.9 room ->
      38.4 IR-only -> 25.6 LED-on, with corr(noise, sharpness) = +0.10 over 52
      samples and overlapping noise ranges between conditions. The first reading
      (noise contamination) was wrong; the camera simply images best under IR,
      where a NoIR sensor sees crisp silhouettes against the backlight and added
      visible light washes edges out. It still cannot separate focus from
      contrast on its own - that needs a defocus test at fixed illumination.
- NOT APPLICABLE: the Pi thermally throttled (87 C, throttled=0x70006, fps
      4.99 -> 3.64) under the black cloth used for this bench test. Ethoscopes run
      in cooled incubators and are never covered, so this was an artefact of
      testing on a desk, not a field confound.
- [x] Achieved fps also depends on **scene content**: switching the LED on took
      fps from 4.99 to 4.1, more foreground to segment on a CPU-bound Pi.
- [x] At maxfps=5 the exposure decoupling is a **no-op**: `_MAX_EXPOSURE_US`
      (200 ms) equals the 5 fps frame period, so decoupled and pinned-FrameRate
      allow the same maximum exposure. The fix only has room to act above 5 fps.
- [x] The white daylight LED barely changes image statistics; the **IR backlight**
      forms the image on a NoIR sensor. Calibration (step 2) should target IR
      brightness and gain, not the daylight LED.

**Implication for #222:** the FPS -> sleep pathway has more than one contributor -
the exposure ceiling and CPU load, which varies with scene content. A fix
addressing only exposure will not make sleep scores comparable across units.

## Still open
- [ ] Decimation study (one recording, scored at several sampling rates).
- [ ] Repeat the illumination sweep with flies, so jitter reflects animals.
- [ ] Defocus test at fixed illumination, to see whether sharpness separates
      focus from contrast before it is used for attribution.
- [x] `manual_polygons` ROI templates repaired (`template.py`): int32 points,
      and unit-square coordinates scaled to the frame and clipped to the last
      valid pixel. `default_full_image` builds and tracks on the device.
- [x] ROI-building failures now report their real cause. Builder construction
      moved inside the try as well, since a missing template failed one line
      above it and escaped as a raw traceback.
- [x] DIAGNOSTICS created unconditionally, so resumed runs record samples.
- [x] Camera model cache path unified (writer and reader had disagreed, so it
      was never read).

Remaining known defects, not fixed here:
- [ ] `_has_moved()` divides by dt before the term cancels (#224 territory).
- [ ] `ethoscopeFormService.js` seeds arguments with `argDef.default || ''`,
      mangling boolean False and numeric 0 (#224 territory).
- [ ] The device unit suite cannot be collected by pytest at all: importing
      `ethoscope/__init__.py` fails through `control` -> `ethoscope.core.monitor`.
      Pre-existing; tests had to be run from a copy outside the package tree.
- [ ] Devices cannot self-update on this network: `origin` is
      `git://node.local/ethoscope.git`, which does not resolve from a device and
      whose git daemon port is closed.

---

# Self-hosted SD image publishing

Date: 2026-08-19

## Problem

Releasing an image meant: zip, md5, upload to box.com, create a share link, hand-edit
`Docker/resource_server/contents/links.json`, get that file onto the server, restart the
container. The box URLs are opaque and unscriptable, and `pa_server.py` read `links.json`
only at import time — so the deployed copy on `ctb.gilest.ro` had already drifted from git.

## Tasks

- [x] `accessories/publish-image.sh` — zip, md5, resumable rsync to `ctb.gilest.ro`,
      remote checksum verification, sidecar manifest published last, `--prune`, `--dry-run`.
- [x] `pa_server.py` — build the image list from sidecar manifests (newest first) merged
      with the remaining `links.json` entries; mtime-cached reads so `links.json` and
      `news.txt` no longer need a restart; `/latest_sd_image/<pi>` selects by model instead
      of a hardcoded list index, and 404s honestly when there is no match.
- [x] `--zerofree` in `accessories/ethoscope-image.sh` (in `--all`), with a fill-and-delete
      fallback when `zerofree` is not installed.
- [x] `Docker/resource_server/docker-compose.yml` synced with what is actually deployed
      (`intranet` network, healthcheck, no vestigial `VIRTUAL_HOST`) + images mount.
- [x] `Docker/image_server/docker-compose.yml` — versioned copy of the `repo.ethoscope`
      container that serves the files.
- [x] Archive size surfaced on the resources page (node UI + resource server index).
- [x] Release process documented in `CLAUDE.md`.

## Discovered during work

- The front proxy on `ctb.gilest.ro` is Nginx Proxy Manager, not docker-gen nginx-proxy:
  the `VIRTUAL_HOST` / `LETSENCRYPT_HOST` env vars in the repo's compose files do nothing.
- The deployed clone at `/home/gg/mydocker_images/lab/ethoscope` carries uncommitted edits
  to `links.json` and `docker-compose.yml`; they need resolving before the next `git pull`.

## Remaining

- [x] Download host deployed on `ctb.gilest.ro`: `/srv/http/ethoscope/images` created and
      bind-mounted read-only into `repo.ethoscope` (old compose kept as
      `docker-compose.yml.bak`). Verified end to end with a miniature test image: HTTPS 200,
      correct md5, range requests honoured, directory listing works; test file then removed.
- [x] `pa_server.py` deployed: `dev` pushed, the drifted clone reset and pulled, resource
      server rebuilt (healthy). Verified live — a published manifest appears first in
      `/resources` with its size, `/latest_sd_image/pi3|pi4` follows it, and deleting the
      manifest instantly reverts to the previous entry with no restart. The remaining
      box.com entries still resolve, their models parsed from the `_PI3`/`_PI4` filenames.
- [ ] `--zerofree` could not be executed here (loop devices need sudo); the rest of the
      pipeline was verified end to end against a miniature test image.

## Updater table reported "Up to Date" for devices months behind (2026-08-19)

**Root cause: a frozen remote-tracking ref.** `get_local_and_origin_commits()` called a
bare `self._remote.fetch()` and then read `origin_commit` off
`refs/remotes/origin/<branch>`. A bare fetch relies on `remote.origin.fetch` being
configured; where that entry is missing or narrowed, `git fetch` still exits 0 but writes
nothing under `refs/remotes/`. The tracking ref then stays frozen -- in every affected
case at the device's own HEAD -- so the device compared itself against a stale mirror of
itself and reported up_to_date forever.

Confirmed against prod `/devices`: ETHOSCOPE_224, _310, _311, _358 and _363 all had
`origin_commit` byte-identical to `local_commit`, on commits from 2026-04-28 to
2026-07-01, while devices whose fetch worked correctly reported `origin_commit` =
`7820b89`. `DeviceUpdater` never called `_ensure_fetch_refspec()` -- only
`BareRepoUpdater` (the node) did, which is why the node itself was never affected.

Where the refspec was absent entirely, GitPython's `fetch()` raises
`AssertionError: Remote 'origin' has no refspec set`, so `check_update` returned an error
and `up_to_date` was simply missing. Those devices (312, 361, 380, 390) then failed the
`up_to_date == false` row filter and vanished from the table altogether -- they could not
be selected for an update at all.

- [x] `updater.py`: `ensure_fetch_refspec()` lifted out of `BareRepoUpdater` to module
      level and now called from `DeviceUpdater.__init__` too (non-fatally -- a device
      with an unwritable config should still answer). Returns whether it had to repair.
- [x] `updater.py`: `get_local_and_origin_commits()` fetches an explicit
      `+refs/heads/<branch>:refs/remotes/<remote>/<branch>` refspec and takes the commit
      from the returned `FetchInfo`. This refreshes the tracking ref, gives an
      authoritative answer even if it did not, and sidesteps the `_assert_refspec`
      crash (GitPython only asserts when `refspec` is None).
- [x] `tests/test_updater_stale_tracking_ref.py`: six tests over real temporary git
      repos. Verified they fail on the unfixed code with exactly the prod signature
      (`assert '128392e...' != '128392e...'`) and pass after.

### Secondary: the version column and the badge measured different things

- `device.version` <- `/data/<id>` (port 9000) -> the listener's `GIT_VERSION`, which
  `device_listener.py:338` snapshots **once at process start** and reuses for every
  `ControlThread` it spawns.
- `device.up_to_date` <- `/device/check_update/<id>` (port 8888) -> the checkout on disk.

A device pulled but never restarted shows an old version with a current disk. Only
ETHOSCOPE_391 was actually in this state (running 13b7f78, disk 7820b89), so this was
*not* the cause of the reported symptom -- but it is real and was invisible.

- [x] `script.js`: single `device_state()` classifier -- `unknown` / `outdated` /
      `stale` / `current` -- with `state_label()`, `state_color()`, `needs_action()`, so
      the three places that render the badge cannot drift apart.
- [x] `index.html`: badge routed through those helpers; the version cell shows the
      on-disk commit under the running one when they differ; row filter uses
      `needs_action()` so `[Unknown]` devices are no longer hidden.
- [x] `main.css`: `.color-grey` added, pulse extended to `.color-yellow`.
- [x] `helpers.py`: `update_dev_map_wrapped()` takes a `timeout`; `check_update` gets 45s
      instead of 10s, since the device runs a live `git fetch` to answer it.
- [x] Verified by rendering the real page in headless Chrome against a stub reproducing
      the prod table: all four states render with the right colour, and the default view
      lists exactly the stopped devices needing attention.

### Discovered during work

- `GIT_VERSION` is also stamped into every experiment's metadata, so a device pulled
  without a restart records the wrong version into its result databases too.
- `update_active_branch()` uses `self._remote.pull()`, which with a broken refspec merges
  FETCH_HEAD and advances HEAD without updating the tracking ref -- ETHOSCOPE_391's exact
  state (disk 7820b89, tracking ref still 13b7f78). Repairing the refspec in
  `__init__` fixes this path too.
- GitPython's `config_reader().get_value(section, option, default=None)` still raises:
  it treats a `None` default as "no default given".
- [ ] After deploying, confirm the five devices flip to Outdated and that 312/361/380/390
      answer `check_update` instead of erroring.

## The fix could not reach the devices that needed it (2026-08-19)

Devices whose fetch refspec was broken kept reporting themselves up to date, so they
were never selected for an update -- and the update was the only thing that would have
repaired the refspec. The fault suppressed its own fix, and 358, 361, 363 and 380 sat
green on April/May commits through three rounds of updating everything else.

The device's reported HEAD is reliable; only its conclusion is not. The node's bare repo
at /srv/git/ethoscope.git is literally what devices pull from
(`git remote set-url origin git://node.local/ethoscope.git`, install_ethoscope_debian.sh:431),
so the node has everything it needs to answer the question itself.

- [x] `BareRepoUpdater.branch_tip()` and `.is_current(sha, branch, monitored_paths)` --
      decide from the node's mirror, applying the same monitored-paths rule the device
      used to apply. Returns None when undecidable (unknown branch, or a commit the node
      has never seen), so the device's own answer survives where the node cannot improve
      on it.
- [x] `judge_devices_locally()` runs over the map at the end of `/devices`, overwriting
      `up_to_date` and `origin_commit`. Falls back to the running `version` when
      check_update could not answer at all -- a lower bound, but enough to know the code
      being executed is stale.
- [x] `monitored_paths(for_node=)` so the node can ask about a device rather than about
      itself; the dict lifts to a module constant.
- [x] Module-level defaults for `is_node` / `bare_repo_updater` / `device_id` /
      `ethoscope_updater`, so update_server can be imported and tested without starting
      a server.
- [x] `tests/test_node_side_verdict.py`: 12 tests over a real bare repo, including the
      ETHOSCOPE_358 shape end to end.

### Also fixed this round

- [x] Discovery dropped any device that missed a 2s probe (`if id is None: continue`) --
      no row, no log. Now seeded from the node's own id/name knowledge, probed with 5s,
      retried once after 4s (a device mid-update is restarting the very server being
      probed), and listed as Unreachable if still silent. `_probe_devices()` +
      `_enrich_device_map()` replace four copies of the same fan-out loop.
- [x] Frontend `is_listed()` replaces the `status == 'stopped'` row filter, so
      unreachable and software-broken devices are visible rather than implicitly fine.

### Outcome (confirmed in prod, 2026-08-19)

The node-side verdict resolved it. A refresh produced the full list of genuinely
outdated ethoscopes, they updated, and 363 -- the last holdout -- appeared and updated
on the following refresh. The devices that had been lying green since April are current.

- [x] `[Restart Required]` lagging one update behind: display lag, not a lost restart.
      `reload_device_daemon()` restarts `ethoscope_listener`, which re-reads HEAD only at
      process start; a scan landing before the listener finishes coming back up sees the
      previous commit. Same cause for the transient "Software broken" -- the device web
      server has not rebound its port yet. Both clear on their own within a minute or two.
      Only worth investigating if it persists past that.

### Open

- [ ] `/bare/update` and `/devices` are fired in parallel by the frontend. The verdict
      reads the bare repo at the end of `/devices`, by which point the fetch has
      finished in practice, but nothing enforces it.
- [ ] Optional: suppress the post-update transient. `record_device_intervention()`
      already records that the user deliberately disturbed a device; the update table
      could read it and show "settling" for a minute instead of Restart Required /
      Software broken. Cosmetic -- only worth doing if the churn is actually annoying.
