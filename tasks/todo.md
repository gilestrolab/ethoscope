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

---

# Incubators: a virtual box must say where it is

Date: 2026-08-20

## Problem

A virtual ("shoe box") incubator is not a box that stands on its own -- it normally sits
*inside* a proper incubator, and until now nothing in the record said which one. The
`location` free-text field describes a room, so a shoe box carrying a light regime of its
own gave no way to tell where the animals in it actually were, nor which sensor was
measuring their conditions.

## Change

Every virtual incubator now declares a **parent**: the name of a physical (normal/smart)
incubator, or the sentinel `Room` when it stands out in the open. Parents must be
physical, so the hierarchy is one level deep and cycles are impossible by construction.

- [x] `incubators/hierarchy.py` -- the single home of the rule (`ROOM`, `validate_parent`,
      `children_of`, `effective_location`). No imports, so the subpackage stays standalone.
- [x] `parent` column in both backends: `etho_db` migration 14 (existing virtual rows
      default to `Room`) and `SQLiteIncubatorStorage` schema v3 with the idempotent ALTER.
- [x] Both write paths validate through the same helper: `setup_api` (node) and
      `IncubatorRoutes` (standalone). Unknown parent, self-parent and box-inside-box are
      refused with a message rather than silently coerced.
- [x] Category changes carry the parenting: promoting a box to normal drops its parent,
      demoting a host to virtual sends its boxes back to the Room, binding hardware
      clears the parent (the record is physical from then on).
- [x] Rename cascades to the children; delete re-parents them to the Room instead of
      leaving a dangling name (the delete message names the boxes that moved).
- [x] `/incubators/merged` gains a derived `effective_location` resolved through the parent.
- [x] UI: a "Sits inside" selector on the incubator modal (virtual only, listing physical
      incubators + Room); the Location field becomes read-only and inherited when the box
      has a parent; the table's search resolves through the parent, so looking for an
      incubator also turns up the shoe boxes kept inside it. (The Location column itself
      was dropped later -- see the next entry.)
- [x] A device in a shoe box now falls back to the **parent's sensor** for temperature and
      humidity (`get_ip_of_sensor` in `ethoscopeController.js`) -- the box has no sensor of
      its own, and the conditions it sees are the enclosing incubator's.

## Verification

- 1713 node tests pass, including new suites for the rules (`test_hierarchy.py`), the
  standalone routes/storage, `etho_db`, and `setup_api`.
- Driven end to end against a live dev node on :8099 -- add/move/rename/delete, the two
  rejection paths, and the UI round trip (edit modal -> save -> table) all behave.
- pre-commit clean on every touched file.

## Discovered During Work

- [ ] The wizard's add/edit incubator modals still have no category field, so they can only
      create normal incubators. Fine for first-time setup; worth revisiting if users start
      creating shoe boxes during installation.
- [ ] A shoe box inside an incubator with a light regime of its own is a light *override*,
      not an inheritance -- currently nothing warns when the two schedules conflict.

---

# Incubators: see which ethoscopes sit in which incubator

Date: 2026-08-20

## Problem

Nothing in the UI answered "what is in Incubator_4A?". The information exists but is
scattered: a tracking device reports its incubator in `experimental_info.current.location`,
an idle one still remembers `previous.location`, and a device that is switched off reports
nothing at all -- on the production fleet that is 23 of 54 devices, i.e. most of the room
would have been invisible.

## Change

- [x] `utils/device_locations.py` -- pure resolver, no scanner or DB needed to test it.
      Precedence: current run -> device's previous run -> node `runs` table. Each
      attribution carries its `source` so the UI can distinguish "is here" from
      "was here in June". Unplaceable devices are still listed, never silently dropped.
- [x] `ExperimentalDB.getLastKnownLocations()` -- newest located run per ethoscope in one
      GROUP BY, timestamps normalised through the existing `_parse_session_time`.
- [x] `GET /devices/locations` -- wires scanner + DB into the resolver.
- [x] Expandable rows on the incubators table: each row carries a caret and a count,
      and opens a detail row listing the ethoscopes inside — shoe boxes nested under the
      incubator that holds them, counts rolled up, greyed-out rows for last-known
      placements. Groups are rebuilt on load (not from the template) so the 15 s poll
      cannot churn the digest.
      Started as a second "Occupancy" tab; folded into the table on review, so all the
      information stays on one page.
- [x] Page-wide "show offline ethoscopes" toggle, off by default, mirroring the main
      device list. An offline device is placed by memory, not observation, so it is not
      counted until asked for; an expanded row says how many it is hiding.
- [x] Dropped the Location and Sensor columns on review: the room name is not what
      anyone needs from this table, and a sensor's *name* says nothing — the Live column
      now shows that sensor's readings instead, and a shoe box's "in <incubator>" moved
      into the Name cell.
- [x] Devices whose recorded incubator no longer exists are silently left out. Deleting
      an incubator is a normal act and its old runs are history, not a fault to report.
      (Only devices that never recorded any incubator are still listed, once.)
- [x] Fixed `loadDevices()` in `incubatorsController`: it fetched `/node/ethoscopes`,
      which has never existed in `NodeAPI`, so `$scope.devices` was always empty and the
      "light schedule locked while devices are running" banner never appeared. Now `/devices`.

## Verification

- 1733 node tests pass (20 new: resolver, DB query, endpoint).
- Rendered against real data -- production `/devices` snapshot + a local copy of the node
  DB -- first via a throwaway stub, then via the real server with only its three scanners
  stubbed out (`scratchpad/devnode.py`), so nothing on the lab network was discovered,
  SSH-keyed or pushed a schedule. 49 of 54 devices placed (2 current, 29 previous, 18
  rescued by the runs table), 5 unplaced.
- Opening that production DB copy also exercised migration 14 on 120 MB of real data: both
  existing virtual incubators were back-filled to `Room` as intended.
- `getLastKnownLocations()` takes 7.7 ms over 2258 runs -- fine for the 15 s poll.

## Discovered During Work

- [ ] Production has duplicate device registrations (two ids, same `ETHOSCOPE_073` name),
      which now show as two rows in one incubator. Worth a cleanup pass on the ethoscopes
      table, unrelated to this view.
- [ ] Bound smart incubators show "offline" in Live when their unit is unreachable, even
      when a sensor of the same name is still reporting readings. Falling back to the
      sensor there too would be consistent with what non-smart incubators now do.

# Platform-wide CLI updater

Date: 2026-08-28

## Goal

Update the whole platform from a terminal: refresh the bare repo, update every
upgradable ethoscope and the node, restart their services, then confirm and summarise.
Equivalent to `src/updater/update_server.py`'s web UI, without a browser.

## Tasks

- [x] Drive the existing update server API rather than reimplementing git/systemd logic,
      so the CLI and the web page cannot disagree about what "out of date" means.
- [x] Copy the web UI's two safety rules verbatim: the updatable-status allowlist
      (`stopped`, `NA`, `Software broken`) and the busy states that are never touched.
- [x] Update the node *after* the devices — restarting it kills the update server the
      script is talking to.
- [x] Confirm by re-surveying, not by trusting the group response (successful device
      replies come back without a device id, so they cannot be attributed).
- [x] Wait out the node restart window and re-query it before reporting.
- [x] Tests: state classification, eligibility (busy is immune to `--force`), glob
      filters, plan building, response parsing, transport failures. 23 tests.
- [x] Verified `--dry-run` against the production node (30 devices, ETHOSCOPE_073
      correctly excluded as running) and the full mutation path against a stub server.

## Review

- Split into `accessories/update_platform.py` (CLI, phases, output) and
  `accessories/update_platform_api.py` (client + rules) to stay under the 500-line rule
  and to make the rules unit-testable without a server.
- Errors are de-duplicated: `process_device_update` returns the same error dict twice
  when the update call raises, so a failing device would otherwise be reported twice.

## Discovered During Work

- [ ] `process_device_update` in `src/updater/update_server.py` returns each device's
      reply verbatim, and a *successful* reply carries no `device_id`. The web UI's
      result panel has the same blind spot. Stamping the id onto every response would
      let both attribute successes, not just failures.

# Stop button does nothing for recording and streaming (2026-08-28)

- [x] Reproduce: ETHOSCOPE_025 stuck in `streaming`; `POST /device/<id>/controls/stop`
      returns 200 but the status never changes.
- [x] Root cause: `commandingThread._busy_with()` trusted `ControlThread.is_alive()`
      alone (introduced in 1fdced7d). `ControlThreadVideoRecording.run()` hands the
      camera to its own `cameraCaptureThread` and returns, so the control thread is
      dead seconds after a recording or stream starts. The listener therefore read a
      busy device as idle and answered "There is no activity to stop."
- [x] Fix: liveness is now `is_alive()` **or** a reported status in
      `_ACTIVE_STATUSES`; the join is skipped when the thread already returned.
- [x] Tests: `TestVideoActivitiesAreStoppable` in `test_listener_busy_guard.py`
      (busy detection, stop, no join, start still refused). 105 tests pass.
- [x] Unstuck 025 in production via `POST node:8888/group/restart`.

## Discovered During Work

- [x] `updates_api_wrapper()` ran `urlparse(ip).hostname`, so a bare IP silently
      resolved to the host "None" and failed as "Name or service not known". Split
      out `helpers.hostname_of()`, which accepts a bare address, a host:port pair or
      a full URL and refuses an empty one by name. Tests in
      `src/updater/tests/test_updates_api_address.py`.

# Update an SD image's checkout from the command line (2026-08-28)

- [x] `accessories/ethoscope-image-update.sh`: loop-mount an image, bind-mount
      `/dev`, `/proc`, `/sys` and `/run` into it, and move `/opt/ethoscope` to the
      tip of a branch (default `dev`).
- [x] Fetch from `https://github.com/gilestrolab/ethoscope.git` by way of whichever
      named remote in the image already points there (`github`), so the image's
      remote-tracking refs move too. The device's own `origin` is its node's bare
      repo and is not reachable from a workstation.
- [x] Where the host can execute the image's binaries (matching arch, or qemu-user
      with a registered binfmt handler), re-run the editable installs the way
      `updater.create_python_egg()` does. Otherwise say so, and warn when the set of
      Python packages changed — a stale editable finder mapping means new
      sub-packages will not import on the device.
- [x] Verified: `--help`, `--list-branches`, `--dry-run`, an unknown branch (exit 2),
      a `dev` bump and a `dev` -> `main` switch, all against a rootfs built from a
      clone of the image's repo.

## Discovered During Work

- [ ] `ethoscope-image.sh --update` does the same git update with the branch
      hardcoded. It could delegate to the new script (`--root "$MNT_ROOT"`) instead
      of keeping its own copy of the logic.

---

# Incubator edit modal: toggles + smart-only WiFi section (2026-09-03)

Frontend only (`src/node/static/pages/incubators.html`, `js/controllers/incubatorsController.js`,
`css/toggle_switch.css`). No backend change: empty `lights_on`/`lights_off` already means
"no light control" for both the node and the firmware payload (`00:00`–`00:00`).

- [x] Light regime On/Off toggle (`selectedIncubator.light_regime`, UI-only). OFF = DD: the
      schedule body is hidden and the save sends empty on/off times. Switching ON with no
      times seeds 09:00–21:00 so the switch has a visible effect.
- [x] Crepuscular checkbox -> On/Off toggle; fade-in/out fields hidden while OFF.
- [x] Max brightness moved into the light-regime row in place of the Preview column.
- [x] Physical unit (WiFi) section shown only for smart incubators (`isSmart()`), not just
      non-virtual ones.
- [x] `.toggle-check-onoff` CSS variant (On/Off labels, compact, no float).

Verified in the browser on a local node (:8080): smart record (incubator-50), normal record
without regime (Incubator_6A), and the update payload captured with regime OFF
(`lights_on: ""`, `lights_off: ""`).

Note: with the WiFi section hidden for normal records, the only way to make a record smart
is "Add & bind" on a discovered unit — the Category select still offers normal/virtual only.

# Manual lights on/off for smart incubators (2026-09-03)

Finding: `POST /command {"set_light": N}` is dead in practice. `LightControl::update()` runs
every 200 ms and `evaluateSchedule()` rewrites `light_target` from the schedule first, so a
manual level survives one tick. A real control needs the firmware to hold it.

Decision (user): the override holds **until the schedule next flips on/off**, then the
schedule takes back control; an explicit "resume schedule" clears it earlier. Not persisted:
a reboot returns to the schedule.

- [x] Firmware 3.3.0-wifi: `state.light_manual` (-1 = schedule) + scheduled state at the
      time of the override; `evaluateSchedule()` honours it and releases on transition;
      `set_light` < 0 or `{"light_auto": true}` clears; `/telemetry` reports `light_manual`.
- [x] Node: `set_light_override(ip, None)` clears; routes/bottle/CLI accept "auto";
      `POST /incubator/light-override {name, pct|null}` on the main node API; merged view
      carries `light_manual`.
- [x] UI: bulb button in the list row for online smart units (toggles on/off at
      `max_light`), a "resume schedule" button + "manual" marker while an override is active.
      Live snapshot refreshed from the proxied `/incubator/<name>/telemetry` after a command
      because the scanner only polls every 60 s.
- [x] Tests: firmware client (None → light_auto), routes (clear), bottle (null pct),
      incubator_api (route + delegation).

Verified: 248 incubator/API tests green; firmware compiles for `d1_mini` (arduino-cli,
staged copy, build number untouched); list row exercised in the browser with the live
endpoints stubbed at `$http` level (bulb posts `pct=max_light`, resume posts `pct=null`,
"manual" marker follows `light_manual`). Not tested on real hardware: the units need
flashing with 3.3.0 before the button does anything lasting.

---

# Custom ROI grid submitted as a single ROI (Alice's bug report)

Date: 2026-09-10

## Symptom

A 2 cols x 8 rows TargetGridROIBuilder, with parameters that "usually work well",
produced one ROI covering the whole arena on updated ethoscopes.

## Diagnosis

The ROI builder is correct. Measured against the targets in the screenshot, the single
ROI is 0.9 x 0.9 of the reference frame, centred — exactly `TargetGridROIBuilder(n_rows=1,
n_cols=1, horizontal_fill=0.9, vertical_fill=0.9)`, i.e. the constructor defaults. The
device was started with an empty-of-user-values argument map.

The shared `option-argument.html` partial takes its arguments map through
`ng-init="argModel = selected_options.tracking[name]['arguments']"`, evaluated once when
the fields are rendered. `updateUserOptions()` re-seeded the group by *assigning a new*
object, so the widgets kept writing to the previous (FileBasedROIBuilder-seeded) object
while `start_tracking` POSTed the new one holding only the grid builder's defaults.
Regression from d8d4b274, which factored the per-input full-path bindings into the partial.

## Tasks

- [x] Re-seed the argument map in place in `updateUserOptions()` (clear keys, refill).
- [x] Regression test driving the real service file through node:
      `src/node/tests/unit/test_form_service_arguments.py` (skips if node is absent).
- [x] Confirm the test reproduces the bug on the pre-fix file — it fails with
      `(n_cols, n_rows) == (1, 1)`, Alice's exact symptom — and passes after.
- [x] Lesson recorded in `tasks/lessons.md`.

Scope note: affects every option group where the user picks a non-default class in the
Start Tracking and Record Video modals (result writer, tracker, camera, time control), not
just the ROI builder. The Machine Information modal was never affected — it still binds
the full path. The stimulator sequence binds `stimulator.arguments[...]`, also a path, so
it was safe too.

Not verified on hardware: needs a device to confirm a 16-ROI grid now builds; the fix is
in served static JS, so a browser refresh on the node is enough to pick it up.

# Options menu: drop SQL dump + manual Backup, add "Free up space"

Date: 2026-09-17. Plan: `~/.claude/plans/replicated-nibbling-crab.md`.

## Tasks

- [x] A. Remove SQL dump: html `<li>` + modal, controller `SQLdump`, node route `dumpSQLdb`,
      scanner `dump_sql_db`/`"dumpdb"`, device `pi.SQL_dump` + `_auto_SQL_backup_at_stop`, tests.
- [x] B. Remove manual Backup: html `<li>` + modal, controller `backup`/`startBackup` + state,
      node `POST /device/<id>/backup` (`_force_device_backup`), tests. Keep the GET.
- [x] C. Device: `ethoscope/utils/storage.py` (`list_runs`, `validate_run_dir`, `remove_runs`),
      routes `GET /data/runs/<id>` + `POST /data/runs/<id>/remove`, unit tests.
- [x] D. Node: scanner `list_runs`/`remove_runs`, `utils/device_storage.py` (`classify_run`,
      `summarise`), `api/storage_api.py` (`GET /device/<id>/storage`, `POST .../storage/purge`),
      registration, unit tests.
- [x] E. Frontend: "Free up space" item + `#freeSpaceModal`, `ethoscopeStorageService.js`,
      relabel `file_exists === false` → "Not on device".
- [x] F. Docs: CLAUDE.md section, device_server route table; run both test suites.

## Discovered During Work

- `pi.cleanup_old_data`/`manage_disk_space` (`pi.py:1306-1455`) run at every tracking start,
  age-only and backup-blind, and target a non-existent `tracking/` dir — disable or make
  backup-aware.
- `_checkpoint_sqlite_databases` (`backup/helpers.py:1404-1408`) glob `results/*/*.db` is two
  levels too shallow and runs `sqlite3` as `ethoscope` on root-owned 0644 files, so it has never
  checkpointed anything; ETHOSCOPE_025 carries a 4.6 MB un-checkpointed WAL as a result.
- `used_space` is set once in `ControlThread.__init__` and never refreshed;
  `ControlThreadVideoRecording` never sets it (UI 89 % vs `df` 93 % on 025).
- scanner `_check_storage_warnings` keys on `machine_info["disk_usage"]`, which the device never
  produces.
- `VideoBackupClass.get_video_list_json` calls `/list_video_files`, which no device serves.

## Review (2026-09-17)

Done and verified. The feature is node-orchestrated but device-executed, over the
regular device HTTP API (an earlier SSH-based design was rejected; see
`tasks/lessons.md`).

**Removed**: SQL dump end to end (UI item, modal, controller, node route, scanner
methods, `pi.SQL_dump`, `_auto_SQL_backup_at_stop`) and the manual Backup modal with
`POST /device/<id>/backup`. The GET stays, since the status bars use it. Route count
assertion 25 -> 23.

**Added**: device `ethoscope/utils/storage.py` + `GET /data/runs/<id>` and
`POST /data/runs/<id>/remove`; node `utils/device_storage.py` (`classify_run`),
`api/storage_api.py`, scanner `list_runs`/`remove_runs`; UI "Free up space" item,
`#freeSpaceModal`, `ethoscopeStorageService.js`, modal width/nowrap CSS.

**Verified**:
- node suite 1787 passed; device unit suite 419 passed; ruff and black clean.
- end-to-end logic against a synthetic tree
  (scratchpad `smoke_storage.py`): backed-up run deletable, dirty-WAL run held back,
  unsynced run held back, video run with a merged mp4 deletable, stray file counted as
  "other", and three refusals (live database, `/etc`, wrong depth).
- browser: every modal step rendered and inspected; real endpoint drives it; no console
  errors. An unreachable device now answers with a sentence rather than a traceback
  (other device endpoints still return tracebacks; not changed here).

**Not verified**: nothing has run against a real ethoscope, because the two device
routes only exist once devices are updated. On a device that is still on old firmware
the modal says so.

---

# SD image shipped 98% full — `/.zerofill` left inside `20260826`

Date: 2026-09-17

## Diagnosis (confirmed, reproduced from the published zip)

A user reported a freshly burnt card showing 27 G used of 29 G, after expanding the
filesystem. The card is fine; **the published image is not**.

`20260826_ethoscope000_pi3_pi4.img` contains `/.zerofill`, 23,293,067,264 bytes
(21.7 GiB), dated 26 Aug 19:09 — the fill file of an interrupted
`ethoscope-image.sh --zerofree` fill-and-delete pass (the fallback used when the
`zerofree` binary is absent). The `rm` never ran.

| image | rootfs total | free | leftover |
|---|---|---|---|
| `20260819` | 28.71 GiB | 23.0 GiB | — |
| `20260826` | 28.71 GiB | **0.02 GiB** | `/.zerofill` 21.7 GiB |

Undetectable downstream: a file of zeros compresses to nothing, so the `.zip` came out
at 2.0 GB (*smaller* than the previous week's 2.8 GB) and its md5 verified. Expanding
the filesystem is also a no-op — the image ships a 29400 M filesystem by design.

The device's own cleanup (`pi.py:1360`) cannot help: it only prunes `/ethoscope_data`,
so on such a card it fires forever and will delete real experiments once any are older
than 60 days.

## Tasks

- [x] Reproduce from the published artefact, not from a card (stream the zip, read the
      ext4 superblock)
- [x] Confirm `20260819` is clean, so it is a safe rollback target
- [x] Make the fill pass crash-safe (`accessories/ethoscope-image.sh:242`)
- [x] Refuse to publish a near-full image (`accessories/publish-image.sh:122`)
- [x] Report rootfs free space in `--info`
- [x] Repair the local source image and verify it
- [x] Document in `CLAUDE.md`
- [ ] Upload the repaired image (blocked for the agent by the sandbox classifier — the
      `.zip` and manifest are built and waiting in `/home/gg/ethoscope_images/`)

## Review (2026-09-17)

**Fix 1 — crash-safe zeroing.** The fill file is now unlinked *before* it is written,
so the kernel reclaims its blocks whenever the writer dies; the `sync` happens while
the fd is still open, so the zeros still reach the disk. A stale `/.zerofill` from a
pre-fix run is removed on the way in.

**Fix 2 — publish guard.** `check_rootfs_space()` reads the superblock through
`debugfs "image?offset=N"` (no root, no mount) before compressing and aborts below 40%
free (`ETHOSCOPE_PUBLISH_MIN_FREE_PCT`, 0 disables), naming any file over 1 GiB in `/`.
The partition-offset logic was factored out of `read_from_image` into `rootfs_offset`.

**Verified**:
- guard refuses a deliberately-full test image (`5% free`, exit 1) and passes a healthy
  one; its leftover detector names `/.zerofill (21.7 GiB)` on the real broken image
- unlink-before-write holds 800 MiB while writing, leaves no directory entry, and
  releases every byte when the writer is killed
- repaired source image: `e2fsck` clean with no corrections, 21.7 GiB free,
  `/etc/sdimagename` and the `/opt/ethoscope` checkout intact
- guard on the repaired image: `22230 MiB free of 29400 MiB (75% free)`
- both scripts pass `bash -n`

**Field fix**, for cards already burnt from this image: `sudo rm /.zerofill`. No
re-burn, no data loss.

---

# Warn before starting a run on a device that is low on space

Date: 2026-09-17

## Problem

Nothing stood between a user and starting a run on a device with 1 GB left: the
Start button in `#startModal` POSTed straight to `/controls/start`, and the only
disk signal on the page was a hard-drive icon most people never look at. A card
that fills mid-run loses the experiment, and the device's own auto-cleanup reacts
by deleting old data. The remedy already existed — Options -> Free up space
(529e38b8) — it just was not offered at the moment it was needed.

## Decisions

- **Warn, never block.** "Free up space…" / "Start anyway" / "Cancel".
- Trigger on **percent used OR free bytes**, whichever fires first, with a higher
  free-bytes bar for video than tracking.
- The percentage rule is **qualified by an absolute ceiling** so a large disk at
  91% (90 GB free) stays quiet; the absolute rule has no such qualifier.
- 90% rather than the existing `alerts.storage_warning_threshold` (80): that key
  governs notifications, where a message is cheap. A dialog in front of every
  start at 80% would be dismissed unread within a week, and 80% of a 32 GB card
  still leaves ~6 GB — ample for tracking.

## Tasks

- [x] `assess_free_space()` + `thresholds_for()` + df parsing in `device_storage.py`
- [x] Four new `alerts.*` config keys, auto-merged into existing installations
- [x] `?action=` on the existing `GET /device/<id>/storage` (no new route)
- [x] `preflight()` in `ethoscopeStorageService.js`; guard in both start paths
- [x] `#lowSpaceModal`, with a variant for "nothing safe to delete yet"
- [x] Unit tests (39 new) and end-to-end verification against a stand-in device

## Review (2026-09-17)

**Where the judgement lives.** All of it on the node: thresholds come from the
config file, the arithmetic is one pure function, and the JS only asks and
renders. There is no JS test runner in this repo, so every branch put in
JavaScript is a branch nobody can test — that asymmetry, not elegance, decided it.

**Why not the `used_space` already in the poll.** It is set once in
`ControlThread.__init__` (`tracking.py:419`), never refreshed, and absent from
`ControlThreadVideoRecording._info` (`record.py:647`) — so it can be days stale or
missing, and it carries no byte figures. The warning reads the disk live instead,
and corrects the icon's percentage from what it finds.

**Fail open, deliberately.** An unreachable device, firmware too old to serve
`/data/runs`, a timeout (10 s) or an unparseable `df` field all mean "no warning".
A disk check must never be why an experiment fails to start.

**Fixed in passing** (same function, would have been worse to refactor around):
`start_tracking` called `startTrackingWithData()`, which is defined nowhere in the
repo — so choosing a **custom ROI template** uploaded it and then threw a
ReferenceError instead of starting. The two identical POST blocks are now one
local `postStart()`, which is also what line 1188 now calls.

**Verified** — unit: 1826 node tests pass (39 new, covering both gates, the
large-disk ceiling, df suffixes incl. a locale comma and a grouped number that
must stay unreadable, every unreadable input, and config migration).
End-to-end against a stand-in ethoscope (scratchpad `fake_ethoscope.py`, mDNS +
the routes the scanner polls, with a disk of my choosing) driven through the real
browser UI:

| Case | Result |
|---|---|
| 93% full, tracking | warns, no start issued |
| 93% full, video | warns, "most recent run" line correctly absent |
| Start anyway | exactly one start POST, no double-start |
| Cancel | no start, no spinner left spinning |
| Free up space… | hands off to `#freeSpaceModal`, run listed as backed up |
| after closing | no `.modal-backdrop`, no `modal-open`, page clickable |
| 44% full | no modal, starts in one click |
| firmware too old (404) | no modal, starts anyway |
| 420 px wide | buttons stack, nothing clipped |

No console errors throughout.

## Discovered During Work

- `EthoscopeScanner._check_storage_warnings()` (`ethoscope_scanner.py:1109`) is
  **dead code**: it reads `_info["machine_info"]["disk_usage"]`, which no device
  endpoint produces, so `send_storage_warning_alert()` has never fired. Reviving
  it wants a per-poll disk figure for the whole fleet — i.e. fixing `used_space`
  first. Left alone here.
- `cleanup_old_data()` (`pi.py:1266`) globs `<dir>/tracking` while the real tree
  is `results/`, so the 85% auto-cleanup can only ever delete videos. Worth a
  decision of its own: the honest fix may be to stop auto-deleting data at all,
  now that the user gets warned instead.
- `tracking.py:419` does `pi.get_partition_info(...)["Use%"]` and
  `get_partition_info` returns `None` on failure — a `TypeError` in
  `ControlThread.__init__` on a device where `df` misbehaves.

---

# The free-space figure never refreshed

Date: 2026-09-17

## Problem (measured, not inferred)

A user freed space on ETHOSCOPE_025 and it still read 93% full an hour later.
Comparing the two sources on the production node:

| | |
|---|---|
| live `df` on the device (`/device/<id>/machineinfo`) | **67% used, 9.2 GB free** |
| what the node reports and the icon draws (`used_space`) | **93%** |

The deletion had worked. The reading was frozen.

`used_space` is set in `ControlThread.__init__` (`tracking.py:419`) and nowhere
else; `_update_info()` — which runs on every status poll — never touched it. A
`ControlThread` is constructed in exactly two places: `device_listener.py:61`
(service start) and `:266` (a `start` command). So the figure only ever changed
when the listener restarted or a new run began, and on a device that is *running*
it is a snapshot of the moment that run started.

Everything downstream was working correctly and faithfully re-transmitting a
stale number:

| Link | Interval |
|---|---|
| device recomputes `used_space` | **never** (now ≤ 60 s) |
| node scanner polls `/data/<id>` | 5 s (60 s when unreachable) |
| browser polls `/device/<id>/data` | 10 s |
| `/machine/<id>` partitions, `/data/runs/<id>` | live, on request |

`ControlThreadVideoRecording._info` omitted `used_space` altogether, so a
recording device — the state that fills a card fastest — reported nothing at all
and drew the grey question-mark icon.

## Fix

- `pi.used_space_percent()` — reads the figure, returns None instead of raising.
  `get_partition_info()` returns None on failure and all three call sites
  subscripted it immediately, so a misbehaving `df` was a `TypeError` in
  `ControlThread.__init__`.
- `_refresh_used_space()` on both control threads, called from `_update_info()`,
  cached for `pi.USED_SPACE_TTL_S` (60 s). The TTL keeps `df` off the poll path —
  info is read every few seconds per device — while bounding staleness to a
  minute.
- The video recorder now carries the field at all, and refreshes it outside its
  `_recorder is None` guard.

**Verified**: 430 device unit tests pass (11 new: the reader's None paths, both
threads replacing a stale figure, both throttling inside the TTL, and an
unreadable `df` leaving the last known value alone).

**Takes effect after a fleet update.** Until a device is updated, its figure
still only moves when its listener restarts or its next run starts — so
ETHOSCOPE_025 will correct itself when its current run ends. Do not restart
`ethoscope_listener.service` on a device that is running: it would end the run.
The low-space warning added in ad12c0f5 reads the disk live, so it shows the true
figure regardless of firmware, and corrects the icon when it fires.

---

## Bug report: live stream dead on newly built Pi 4B ethoscopes (2026-09-17)

Reported: new Pi 4B ethoscopes never produce a live stream; the Pi 3B one does.
Button flips to "Stop" (device reports `streaming`), but no video reaches the node.
Tracking works on the same devices. Node fully updated.

### Reproduction / findings

- [x] Baseline: streaming works end to end on real hardware. ETHOSCOPE_312
      (Pi 3B, imx219, dev @ 785932ce) streamed 224 JPEG frames in 14 s through
      `GET /device/<id>/stream`. Device returned to `stopped` cleanly.
- [x] Synthetic end-to-end (fake camera -> `cameraCaptureThread` MJPEG server ->
      `EthoscopeStreamManager`) relays frames correctly on current `dev`.
- [x] **No Pi-model branch exists anywhere in the streaming path.** The only
      `pi_version()` consumers are `isMachinePI()` and `_tuning_dirs_for_this_pi()`
      (`_FIRST_PISP_MODEL = 5`, so Pi 3 and Pi 4 take the identical branch).
      So "Pi 4B" is a property of *when those devices were built*, not of the code.
- [x] **Reproduced the exact symptom from node/device version skew.** Ran the
      pre-`2e28b763` device streamer (pickle + `struct.pack("Q")` framing) against
      the current node relay: the relay blocks forever in its
      `while b"\r\n\r\n" not in header` loop, swallows the whole stream and yields
      **zero bytes**. The browser `<img>` never paints; the device is unaware and
      keeps reporting `streaming`. `2e28b763` (9 Jun 2026) touched only
      `record.py` + `ethoscope_streaming.py`, which is why tracking is unaffected.
- [x] **Reproduced the silent-failure defect.** With port 8887 already bound,
      `cameraCaptureThread.run()` dies on `OSError: [Errno 98]` before the camera
      loop, yet the recorder still reports `status: streaming`, `error: null`.
      `ControlThreadVideoRecording.run()` sets the status before `start_recording()`
      and nothing downstream ever revises it.

### Discovered During Work

- [ ] Node: detect a device whose 8887 response is not an HTTP header and report
      "device software too old to stream" instead of hanging in the header loop.
      Bound that loop by bytes and by time.
- [ ] Device: surface a dead `cameraCaptureThread` in `_info["error"]` / status
      rather than leaving the device stuck in `streaming`.
- [ ] `GeneralVideoRecorder.stop()` still closes `self._p.connection`, a leftover
      of the pickle era; the attribute no longer exists and the call is a no-op
      inside `try/except`.
- [ ] Race in `EthoscopeStreamManager._is_socket_healthy()`: it flips the shared
      socket's timeout to 0 and back while `_streaming_broadcast_loop` is reading
      the same socket in another thread.

### Follow-up: the reporter's Pi 4s will not boot the August images (2026-09-17)

Root cause found by reading the **published** artefacts, not the repo.

- [x] **`20260819_ethoscope000_pi3_pi4.img.zip` cannot boot a Pi 4.** Its
      `/boot/firmware/config.txt` still carries the legacy block:
      `start_file=start_x.elf` + `fixup_file=fixup_x.dat` (+ `gpu_mem=256`,
      `awb_auto_is_greyworld=1`, `dtparam=camera=on`). `start_x.elf` is Pi 0–3-only
      firmware, so the Pi 4 stops with error 44 — ACT LED **4 long + 4 short,
      "unsupported board type"** — exactly what was reported. Neither a second
      board nor an EEPROM update can help: the firmware reads `config.txt` before
      userspace exists. Predates the fix in `7608dba6` (26 Aug 2026 18:15).
      Everything else a Pi 4 needs is present in that image (`start4.elf`,
      `fixup4.dat`, `bcm2711-rpi-4-b.dtb`, `vc4-kms-v3d.dtbo`, `kernel8.img`), so
      the `start_file` override is the sole blocker.
- [x] **`20260826` is correct**: the managed block is `dtoverlay=vc4-kms-v3d` /
      `gpu_mem=128` / `camera_auto_detect=1`, no `start_file`. Its `config.txt` is
      stamped 26 Aug 17:05, an hour before the commit. It still carries a stray
      `config.txt.camtest.bak` holding the old bad block.
- [x] **The reporter cannot have tested 20260826.** `Last-Modified` on
      `20260826_ethoscope000_pi3_pi4.img.zip` is **Thu, 17 Sep 2026 11:46 GMT**
      (today's re-publish after the `/.zerofill` fix); its manifest says
      `"published": "2026-09-17T11:45:29Z"`. Before today the newest image
      advertised was 20260819. Both of their attempts were effectively that build.

#### Actions

- [ ] **Retire 20260819**: it is still advertised on the resources page as "for
      Pi 3 / Pi 4" while bricking Pi 4 boot. `rm
      /srv/http/ethoscope/images/20260819_ethoscope000_pi3_pi4.img.zip.json` on
      `ctb.gilest.ro` drops it from the list.
- [ ] Repair-in-place for anyone already holding a 20260819 card: mount the FAT
      boot partition on any machine and replace the managed block with the KMS
      one. No re-flash needed.
- [ ] `publish-image.sh` should refuse to publish an image whose `config.txt`
      contains `start_file=` while the name claims `pi4` — the same shape as the
      existing free-space guard. This shipped because nothing checks the boot
      partition before upload.
- [ ] Delete the stray `config.txt.camtest.bak` from the image's boot partition.

### Image hygiene follow-up (2026-09-17)

**One image for both models is possible — 20260826 already is it.** Verified from
the published artefact: no `start_file` override, and every Pi-4 prerequisite
present (`start4.elf`, `fixup4.dat`, `bcm2711-rpi-4-b.dtb`, `vc4-kms-v3d.dtbo`,
`kernel8.img`, `arm_64bit=1`). Firmware auto-picks `start.elf` on Pi 0–3 and
`start4.elf` on Pi 4. No per-model split is warranted; 20260819 simply predates
`7608dba6` and should never have been named `pi3_pi4`.

- [x] **Publish-time guard** (`accessories/publish-image.sh`): `check_boot_firmware()`
      refuses to publish when the name claims pi4+ and `config.txt` pins Pi 0–3-only
      firmware. Reads the FAT partition with `mtype` (no root), loop-mount fallback.
      Override with `ETHOSCOPE_PUBLISH_SKIP_BOOT_CHECK=1`.
      Verified against the real artefacts: 20260819 as `pi3 pi4` → refused naming the
      offending line; 20260826 as `pi3 pi4` → passes; 20260819 as `pi3` only → passes.
      `rootfs_offset()` generalised to `partition_offset N` + `bootfs_offset()`.
      Both checks are skipped for a pre-made `.zip`, now stated in the output.

- [x] **The 20260826 image's checkout is 31 commits behind `dev`.** `/opt/ethoscope`
      sits at `7608dba6` (26 Aug 18:19, `FETCH_HEAD` confirms `branch 'dev'`);
      `dev` is now `3ed036af`. Missed in today's re-publish, which only removed
      `/.zerofill`. No packaging change in those 31 commits (no `pyproject.toml`
      diff, identical `__init__.py` set), so the editable finder in the image still
      maps the right packages and the update can skip pip:

      ```
      sudo ./accessories/ethoscope-image-update.sh --branch dev --no-pip <image>.img
      ./accessories/publish-image.sh <image>.img          # re-date the name first
      ```

- [ ] **Retire 20260819 from the server** — still advertised as "for Pi 3 / Pi 4"
      and still directly downloadable. `rm .../20260819_*.img.zip.json` drops it
      from the page; remove the `.zip` too, since the direct URL is what people
      paste to each other.

- [x] Side note for the streaming report: the reporter's devices were on the
      **20260511** image, which predates `2e28b763` (9 Jun) — so they ran the
      pickle framing. That closes the first half of the report.

### Image retirement + refresh (2026-09-17, in progress)

- [x] **20260819 retired.** Moved (not deleted) to
      `ctb.gilest.ro:/srv/http/ethoscope/images/retired/` — both the `.zip` and its
      manifest. The resources page now lists only 20260826; both direct URLs 404;
      `/latest_sd_image/pi3` and `/pi4` resolve to 20260826. `links.json` carries no
      image entry for it, so nothing resurrects it. The bytes are still there if
      they are ever wanted.
- [x] Stray `config.txt.camtest.bak` deleted from the master image's boot partition
      (`mdel`, no root needed — udisks mounts the FAT partition `uid=1000`).
- [x] Pre-flight on the master image: rootfs clean, 75% free; boot partition had the
      **FAT dirty bit set**, so the refresh run needs `--fsck` as well.
- [x] Acceptance checker written:
      `/tmp/claude-1000/-home-gg-Code-ethoscope-project-ethoscope/84a8ea88-bce1-470f-82af-f000e9c69f4b/scratchpad/verify_image.sh`
      — identity, checkout vs github `dev`, cross-model boot (no `start_file`,
      `start4.elf`/`start.elf`/both DTBs/`kernel8.img` present), free space,
      leftover fill file, both filesystems. Verified it flags all four defects on
      the un-updated master.
- [ ] **Needs root** (no sudo password available to the agent):
      `sudo ./accessories/ethoscope-image.sh --fsck --update --rename --zerofree /home/gg/ethoscope_images/20260826_ethoscope000_pi3_pi4.img`
      `--update` fetches the URL directly, so the image's `origin`
      (`git://node.local/ethoscope.git`, unreachable off-site) does not matter.
      No pip needed: no packaging change between `7608dba6` and `3ed036af`.
- [ ] Rename the file to match `/etc/sdimagename`, re-run the checker, publish, prune.
- [ ] Real boot test on a Pi 3 and a Pi 4. QEMU cannot substitute: its `raspi3b`/
      `raspi4b` machines take `-kernel`/`-dtb` directly and never run `start4.elf`,
      so the firmware path that broke 20260819 is exactly what it would skip.

#### Refresh completed (2026-09-17)

The first `ethoscope-image.sh` run died on `umount: target is busy` **after** the
git update and retag had landed, leaving `/dev/loop0p2` mounted read-write on the
image. The second run then attached a *second* loop device to the same file, so its
`e2fsck` was repairing a filesystem another mount still held live — which is where
the bitmap/free-count mismatches came from. Recovery, all without root:

- `udisksctl unmount -b /dev/loop0p2` cleared the stale mount (the loop was
  autoclear, so it detached itself);
- `e2fsck -fy "<img>?offset=545259520"` — the ext2fs library takes the offset
  syntax and the file is user-owned, so no loop device and no sudo;
- a second `e2fsck -fn` pass confirmed clean with no changes;
- `zerofree -v "<img>?offset=545259520"` also accepts the offset syntax — 849
  dirty free blocks zeroed (small, because the August pass had already done the
  bulk).

**`--fsck`/`--zerofree` never needed root in the first place.** Only the git update
does, because udisks mounts ext4 root-owned.

- [x] Image renamed to `/home/gg/ethoscope_images/20260917_ethoscope000_pi3_pi4.img`;
      stale 20260826 `.zip`/`.json` deleted locally.
- [x] Acceptance checker: **all pass** — retagged to today, checkout `3ed036af` ==
      github `dev`, no `start_file`, KMS block, `start.elf`+`start4.elf`, both DTBs,
      `kernel8.img`, 75% free, no leftover, both filesystems clean.
- [x] Skipping pip confirmed safe on the real artefact: the editable finder maps
      `ethoscope -> /opt/ethoscope/src/ethoscope/ethoscope` (present, populated),
      no new package or namespace directories, and **no change under `services/`**
      between `7608dba6` and `3ed036af`, so the installed units are current.
- [x] `publish-image.sh --dry-run` on the new image passes both guards, including
      the new one: "boot: firmware auto-selected (no start_file override) — Pi 4 OK".
- [ ] Boot test on real hardware, then publish + prune.

#### Boot test PASSED on real Pi 4 hardware (2026-09-17)

Flashed `20260917_ethoscope000_pi3_pi4.img` to SD, booted a Pi 4B. Verified from the
workstation over mDNS (the Pi is on the local LAN; `node` is reached over the VPN at
a different site, so it never appears in the node's device list — look for the
`_ethoscope._tcp` zeroconf record with `avahi-browse -artp` instead).

| check | result |
|---|---|
| boots on Pi 4 | **yes** — `pi_version {model_number: 4, model_type: "Model B Rev"}`, kernel `6.18.39+rpt-rpi-v8` |
| zeroconf | `_ethoscope._tcp` `ETHOSCOPE000-b14bdd6b…` at 192.168.68.130:9000 |
| checkout | `3ed036af`, dated 2026-09-17 — current `dev` |
| rootfs expansion | `/` 29G, 25% used, 21G avail (no `/.zerofill` regression) |
| camera | live detect `imx219` Rotation 180; NoIR tuning **loaded**: `imx219_noir.json` |
| **streaming** | `HTTP/1.0 200 multipart/x-mixed-replace; boundary=frame`; 195 JPEG frames in 12 s (~16 fps) |
| frame content | 640x480 greyscale arena image, mean 134.6 / std 37.4, "FPS: 15.0" overlay — inspected visually, correctly exposed and in focus |
| stop | returns to `stopped`, `error: null` |

That closes the original report end to end: the image boots the model that 20260819
could not, and a device on current code streams over the new MJPEG protocol.

- [x] Published `20260917_ethoscope000_pi3_pi4.img.zip`
      (md5 `2c1968d1727e75548b4a4d75c9c59d99`, 2.0G).
- [x] Moved 20260826 to `images/retired/` after the new one verified remotely.
      Do **not** use `--prune`: it runs before the upload, so it would delete the
      only published image and leave a gap. (It does correctly ignore `retired/` —
      `ls -1 | grep '\.img\.zip$'` matches no directory.)
- [x] **Pi 3 boot verified on the same card** — `pi_version {model_number: 3}`,
      same kernel `6.18.39+rpt-rpi-v8`, same checkout `3ed036af`, `/` 29G at 21%.
      Streaming: correct MJPEG headers, 195 JPEG frames in 12 s, NoIR tuning loaded
      (`imx219_noir.json`), frame inspected visually — well exposed and in focus.
      Back to `stopped`, no error. One image, one card, both models: settled on
      hardware, not inferred.

#### Published and live (2026-09-17)

`https://repo.ethoscope.lab.gilest.ro/images/20260917_ethoscope000_pi3_pi4.img.zip`
— 2.0G, md5 `2c1968d1727e75548b4a4d75c9c59d99`, remote md5 verified by the
publisher. The resources page lists it alone; `latest_sd_image/pi3` and `/pi4` both
resolve to it; both retired images 404. `images/retired/` holds 20260819 and
20260826 (4.8G) if the bytes are ever wanted — `rm -rf` reclaims it.

Pi 4 powered off over the device API (`POST /controls/<id>/poweroff`) so the card
could move to a Pi 3; ping and :9000 both confirmed down before reporting it safe.

## Streaming fixes (2026-09-17)

Three defects, all of which presented as "the device says it is streaming and the
browser shows nothing".

- [x] **The node hung instead of saying why.** `_streaming_broadcast_loop` read
      `recv()` until it found `\r\n\r\n`, unbounded in both bytes and time. Against a
      device older than `2e28b763` (pickle framing) that blank line never comes, so
      the node swallowed the whole stream and yielded nothing, for ever. The
      handshake is now `_read_stream_headers()`, called synchronously from
      `_start_shared_streaming()`: 10 s timeout, 8 KiB cap, and the response is
      validated (`HTTP/1.` prefix checked on the *first* packet, 200 status,
      `multipart/x-mixed-replace`). A device that fails any of these raises
      `StreamUnavailable`, which `GET /device/<id>/stream` turns into a **502 with a
      readable reason** — naming the June 2026 change when the answer is not HTTP.
      `get_stream_for_client()` now connects eagerly and returns an inner generator,
      so the failure arrives before the response is committed.
- [x] **A dead capture thread kept claiming to be busy.** `cameraCaptureThread.run()`
      is now `try/except/finally` around `_acquire()`: the traceback is kept on
      `self.error` and `_release()` always hands back the camera, the stream server
      and the video writer. `ControlThreadVideoRecording._recorder_died()`, called
      from `_update_info()` (i.e. on every status poll), turns a thread that exited
      on its own into `status: stopped` with the traceback in `error`. Guarded by
      `_capture_started` so a poll landing between "status = streaming" and
      `start_recording()` is not mistaken for a death, and cleared first thing in
      `stop()` so a poll during its 10 s join is not either.
- [x] **`_is_socket_healthy()` could never report unhealthy** (found by the jenner
      session, verified here on real sockets): it probed with `recv(0)`, which
      returns `b""` for a live peer and a closed one alike and never raises EAGAIN,
      so the reconnect in `_ensure_streaming_connection()` never fired. Now
      `recv(1, MSG_PEEK | MSG_DONTWAIT)` — `b""` means FIN, EAGAIN means alive, and
      nothing is consumed. Dropping the `settimeout(0)`/`settimeout(None)` pair also
      removes a race: it mutated a socket the broadcast thread reads concurrently,
      which that thread saw as a stream failure and tore down for every viewer.

Also: `_stop_stream_server()` now `shutdown()`s before `close()` and joins the
acceptor. `close()` alone does not release the port while a thread is blocked in
`accept()`, so a failed stream left 8887 bound and the *next* start failed with
EADDRINUSE — one fault turning into an unrelated-looking second one. Proved by a
test that binds the port after a failed run.

And the broadcast loop now pushes the end-of-stream sentinel to every client when
it exits, instead of leaving them on a 30 s queue timeout.

**Tests**: 12 new device tests (`test_recorder_failure_visible.py`) and the node
streaming suite reworked to 52. Device unit suite 444 passed; node unit suite
1774 passed.

- [x] `pytest-timeout` added to both packages' dev deps with `--timeout=120` in
      addopts. A test of mine looped on a bare `MagicMock` socket and took the
      workstation to 79.5 GB RSS before the OOM killer fired; a per-test cap turns
      that into a failed test. `serving_socket()` in the node streaming tests is now
      the sanctioned way to mock a socket a loop reads from, and its docstring says
      why a bare mock defeats every guard in a read loop at once.
