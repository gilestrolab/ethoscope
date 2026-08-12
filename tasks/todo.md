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
