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
