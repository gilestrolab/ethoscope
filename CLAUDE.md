# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

The Ethoscope is a platform for high-throughput ethomics (automated behavioral monitoring) of small organisms like Drosophila melanogaster. The system consists of:

- **Ethoscope devices**: Individual video monitors that track animal behavior in real-time
- **Node server**: Central management system that coordinates multiple devices and collects data
- **Update system**: Manages software updates across the network

## Architecture

The codebase is organized into three main packages:

### 1. Device Package (`src/ethoscope/`)
Core tracking and monitoring functionality for individual Ethoscope devices.

**Key components:**
- `ethoscope.core.monitor.Monitor` - Main orchestrator that coordinates tracking pipeline
- `ethoscope.trackers.adaptive_bg_tracker.AdaptiveBGTracker` - Primary tracking algorithm using adaptive background subtraction
- `ethoscope.hardware.input.cameras` - Camera interfaces (PiCamera, OpenCV)
- `ethoscope.stimulators` - Hardware interaction modules (optomotor, sleep deprivation)
- `ethoscope.control.tracking.ControlThread` - Web API and tracking control
- `scripts/device_server.py` - Main device web server (runs on port 9000)

### 2. Node Package (`src/node/`)
Central server for managing multiple Ethoscope devices and data collection.

**Key components:**
- `scripts/server.py` - Main node web server (runs on port 80 - APIs are in `src/node/ethoscope_node/api`)
- `ethoscope_node.utils.device_scanner` - Device discovery and monitoring
- `ethoscope_node.utils.backups_helpers` - Data synchronization and backup
- `ethoscope_node.utils.etho_db` - Database management for experimental data
- Frontend: Angular.js SPA in `static/` directory (source-only, no build step)

### 3. Update System (`src/updater/`)
Handles software updates for both devices and nodes via git-based distribution.

## Package Independence Policy

**IMPORTANT**: The device and node packages are designed to be independent and should not have cross-package dependencies.

### Rules

1. **No Cross-Package Imports**: Code in `ethoscope` package must not import from `ethoscope_node` package, and vice versa.
2. **Shared Utilities**: If functionality needs to be shared between packages:
   - **Option 1**: Duplicate the code in both packages (preferred for small utilities)
   - **Option 2**: Extract to a separate shared utilities package
   - **Option 3**: Declare formal dependency in `pyproject.toml` (only if absolutely necessary)

### Rationale

- **Independent Deployment**: Devices and nodes can be updated separately
- **Cleaner Architecture**: Clear separation of concerns between tracking and management
- **Isolated Testing**: Each package can be tested in isolation without installing the other
- **CI Efficiency**: Parallel testing and isolated package builds

### Enforcement

Cross-package imports are detected and blocked by:
- **Pre-commit Hook**: `validate-cross-package-imports` runs on every commit
- **Import Check Hook**: `python-import-check` validates all imports can resolve

### Example: Video Utilities

The `list_local_video_files()` function was originally in `ethoscope.utils.video` and used by the node package for backup operations. To maintain package independence, it was duplicated to `ethoscope_node.utils.video_helpers` rather than creating a cross-package dependency.

**Location**: `src/node/ethoscope_node/utils/video_helpers.py:15`

## Development Commands

### Device Package (src/ethoscope/)
```bash
# Install with device dependencies (recommended)
make install

# Development installation (editable)
make install-dev

# Run all tests
make test

# Run specific test suites
make test-unit           # Unit tests only
make test-integration    # Integration tests only

# Generate documentation
make docs

# Check package health
make check

# Clean build artifacts
make clean
```

### Node Package (src/node/)
```bash
# Install Python backend
make install-all

# Development installation (editable)
make install-dev

# Production installation
make install-production

# Clean build artifacts
make clean
```

### Testing

The project has a comprehensive testing infrastructure with standardized structure across both packages:

**Test Structure:**
- **Device Package**: `src/ethoscope/ethoscope/tests/` (unit, integration, fixtures)
- **Node Package**: `src/node/tests/` (unit, integration, functional, fixtures)
- **Central Test Requirements**: `test-requirements.txt` with all testing dependencies
- **Documentation**: `TESTING.md` with comprehensive guidelines

**Running Tests:**
```bash
# Project-wide test runner
python run_tests.py                    # Run all tests
python run_tests.py --coverage         # Run with coverage
python run_tests.py --package device   # Device tests only
python run_tests.py --package node     # Node tests only

# Device package tests
cd src/ethoscope/
make test              # All tests
make test-unit         # Unit tests only
make test-integration  # Integration tests only
./ethoscope/tests/run_all_tests.sh     # Shell script

# Node package tests
cd src/node/
make test              # All tests
make test-unit         # Unit tests only
make test-integration  # Integration tests only
make test-functional   # Functional tests only
./run_tests.sh         # Shell script
```

**Test Categories:**
- **Unit Tests**: Fast, isolated component tests with mocked dependencies
- **Integration Tests**: Component interaction tests with realistic scenarios
- **Functional Tests**: End-to-end workflow tests (node package only)
- **Hardware Tests**: Real hardware integration tests (marked with `@pytest.mark.hardware`)

**Mock Objects & Fixtures:**
- **Hardware Mocks**: Complete camera, stimulator, sensor, GPIO, and serial port implementations
- **Device Mocks**: Ethoscope device fleet simulation with network discovery
- **Database Mocks**: SQLite and generic database mocking with test data
- **Test Fixtures**: Comprehensive fixtures in `conftest.py` for both packages

**Coverage & Quality:**
- **Coverage Targets**: 70% overall, 85% unit tests, 90% critical components
- **Reports**: HTML, XML, and terminal coverage reports
- **Quality Checks**: Integrated flake8, mypy, and bandit security scanning
- **CI/CD Ready**: Standardized structure compatible with automated testing

**Best Practices:**
- Always write tests when adding new functionality
- Use appropriate test types (unit for components, integration for interactions)
- Mock external dependencies (hardware, network, databases)
- Run tests before committing changes
- Use descriptive test names and include docstrings
- Mark slow tests with `@pytest.mark.slow` and hardware tests with `@pytest.mark.hardware`

## Key System Services

The system uses systemd services for deployment, all find in `/services`.
These can be reinstalled using `accessories/upgrade_scripts/install_services.sh`

On the ethoscope:
- `ethoscope_device.service` - WEB facing API / interacts with listener through a socket
- `ethoscope_listener.service` - Main device tracking/recording service
- `ethoscope_update.service` - Software update management for the ethoscope
- `ethoscope_GPIO_listener.service` - Listens to buttons connected to the PI GPIO and associates actions

On the node:
- `ethoscope_node.service` - Central node management server
- `ethoscope_backup_node.service` - Central node backup management server
- `ethoscope_backup_mysql.service` - Data backup for mariadbdata
- `ethoscope_backup_video.service` - rsync based file backup for videos (h264)
- `ethoscope_backup_sqlite.service` - rsync based file backup for SQLite db
- `ethoscope_backup_unified.service` - Covers both rsync backup services (default)
- `ethoscope_sensor_virtual.service` - Provides a virtual sensor that gives real life weather info about a specified location
- `ethoscope_virtuascope.service` - Starts a virtual ethoscope on the node

## SSH Key Management

The node automatically manages passwordless SSH authentication to ethoscope devices for rsync-based backup operations.

### Overview

- **Purpose**: Enable passwordless rsync backups from ethoscope devices to the node
- **Key Location**: `{ETHOSCOPE_DATA}/config/keys/` (RSA 2048-bit key pair), resolved
  by `resolve_config_dir()` — i.e. `$ETHOSCOPE_CONFIG_DIR` if set, else
  `{data dir}/config`. Typically `/ethoscope_data/config/keys/`.
- **Target User**: `ethoscope` user on ethoscope devices
- **Password**: Default password is "ethoscope" (used only for initial key transfer)

### Key Permissions

Directory `0750`, private key `0600`, public key `0644`, with the group set to `node`
by default — the group that comes with the `node` account on a standard install.

**The private key must stay `0600`.** OpenSSH's `sshkey_perm_ok()` refuses to load a
private key with any group or other bit set *when the caller owns it*, so a
group-readable key is not a shared key — it is a key its own owner cannot use:

```
Permissions 0640 for '/ethoscope_data/config/keys/id_rsa' are too open.
Load key ".../id_rsa": bad permissions
```

An earlier release set `0640` to match the system-wide `IdentityFile` the node
advertises; that broke `ssh` for the account owning the key, which on a normal install
is the admin's own. The group still owns the directory and the public key — the half
of the sharing ssh does allow (traversing the directory, `ssh-copy-id`, fingerprints).
Accounts that need to reach the devices as themselves want their own key on the
devices, not a copy of this one.

Point `ETHOSCOPE_SSH_KEY_GROUP` at another group to override the name (systemd picks
it up from the bootstrap env file alongside the path settings). If the group does not
exist the node logs a warning naming the `groupadd`/`usermod` commands and carries on.

`install_services.sh --node` creates the `node` user and group, and adds the admin
running the installer (`$SUDO_USER`) to the group. Group membership only takes effect
at the user's next login.

Only `ensure_ssh_keys()` asserts these permissions — at node start, and when the pair
is first generated; that is also what repairs a node left at `0640` by the earlier
release. Callers that merely need a path for `ssh -i` use `get_ssh_key_paths()`, which
never rewrites them: the backup loop and the device scanner run every few minutes, and
having them re-apply the modes silently undid any deliberate local change.

### The `/etc/ssh/ssh_config` stanza

`_setup_system_ssh_config()` owns a block in `/etc/ssh/ssh_config` between
`# Ethoscope SSH configuration` and `# End of Ethoscope SSH configuration`. It is
rewritten whenever it no longer matches, so a key path that moves between releases
follows. It used to be written once and never revisited, which left nodes advertising
`/etc/ethoscope/keys/id_rsa` after the config-dir move and every `ssh` to a device
failing with `no such identity`.

Note this only covers the system-wide file. A hand-written `~/.ssh/config` naming the
old path is invisible to the node and has to be fixed by hand.

**Location**: `src/node/ethoscope_node/utils/configuration.py:1425`

### Automatic Key Transfer

The system automatically transfers SSH keys when:

1. **Device Discovery**: When an ethoscope first comes online, the node waits 10 seconds for device stabilization, then automatically transfers its SSH public key
2. **Status Changes**: When a device transitions from offline/unreachable to an accessible state (stopped, running, recording, streaming, busy)
3. **Manual Configuration**: When device machine settings are updated via the web interface

### Visual Indicator

The ethoscope detail page displays an SSH key icon in the status bar:

- **Green Key** (🔑): Passwordless SSH is configured and working
- **Orange/Red Key** (🔑): Passwordless SSH is not configured or failing

The icon appears in the top-right status area, near the hard drive and response time icons.

**Location**: `src/node/static/pages/ethoscope.html:32`

### Implementation Details

**Backend** (`src/node/ethoscope_node/scanner/ethoscope_scanner.py`):
- `check_ssh_key_installed()` - Tests passwordless SSH using BatchMode (line 1375)
- `setup_ssh_authentication()` - Transfers public key using sshpass and ssh-copy-id (line 1314)
- `_handle_device_coming_online()` - Auto-transfers keys with 10s stabilization delay (line 798)
- Status tracked in `device._info["ssh_key_installed"]` field

**Retry Behavior**:
- If initial transfer fails, the system retries on the next device status change
- No continuous retries to avoid excessive SSH connection attempts
- Failures are logged for troubleshooting

### Manual SSH Key Transfer

If automatic transfer fails, you can manually transfer the key:

```bash
# On the node
sshpass -p "ethoscope" ssh-copy-id -i /ethoscope_data/config/keys/id_rsa.pub ethoscope@<device-ip>

# Or without sshpass (will prompt for password)
ssh-copy-id -i /ethoscope_data/config/keys/id_rsa.pub ethoscope@<device-ip>
```

### Troubleshooting

**SSH key icon shows orange/red:**
1. Check network connectivity to ethoscope device
2. Verify ethoscope user password is "ethoscope"
3. Check `{ETHOSCOPE_DATA}/config/keys/` exists on node with proper permissions
4. Review node logs for SSH transfer errors
5. Try manual SSH key transfer (see above)

**Passwordless SSH not working despite green icon:**
1. SSH status may be cached - wait for next device status change
2. Check `/home/ethoscope/.ssh/authorized_keys` on ethoscope device
3. Verify SSH daemon is running on ethoscope
4. Check firewall rules if applicable

## Updating the platform from the command line

`accessories/update_platform.py` is the CLI equivalent of the web updater. It drives
the same HTTP API that `src/updater/update_server.py` serves, so the two cannot drift
apart, and it applies the same safety rules: **a device that is running, recording or
streaming is never updated**, not even with `--force`.

```bash
# from the node itself
./accessories/update_platform.py

# from a workstation, look before you leap
./accessories/update_platform.py --host node --dry-run
```

What it does, in order:

1. `GET /bare/update` — refreshes the node's bare repository from its remote.
2. `GET /devices` + `GET /device/check_update/node` — surveys the fleet and the node.
3. `POST /group/update` for every ethoscope that is out of date *and* idle; the node
   updates each device and restarts its services.
4. Re-surveys the fleet and confirms what actually landed on disk.
5. Updates and restarts the node **last**, then waits for it to come back.
6. Prints a summary and exits non-zero if anything failed or could not be confirmed.

The node goes last on purpose: restarting it also restarts `ethoscope_update_node`,
which is the server the script is talking to, so doing it first would cut the
connection while the devices were still being worked on.

Useful flags: `--dry-run`, `--yes` (required when stdin is not a tty), `--only GLOB` /
`--skip GLOB` (match name or id), `--devices-only` / `--node-only`, `--restart-node`
(restart the node even when its checkout is current), `--force` (also update machines
that look up to date — still never the busy ones), `--batch-size N`, `--json`.

Exit codes: `0` all good, `1` something failed or stayed unconfirmed, `2` the update
server could not be reached at all.

**Location**: `accessories/update_platform.py`, with the API client and the
state/eligibility rules in `accessories/update_platform_api.py` and tests in
`src/updater/tests/test_update_platform_cli.py`.

The older `accessories/update-node-cli.sh` predates this and only updates the node it
runs on, by shelling out to git and systemctl directly.

## Development Workflow

1. **Device Development**: Work in `src/ethoscope/` for tracking algorithms, hardware interfaces, and device-specific features
2. **Node Development**: Work in `src/node/` for web interface, device management, and data collection
3. **Testing**: Always run tests before committing changes
4. **Branching**: Use `dev` branch for development, `main` for stable releases
5. **Code Quality**: Use pre-commit hooks to ensure code quality before commits
6. **CI/CD**: All changes are automatically tested via GitHub Actions

## CI/CD Pipeline

The project uses GitHub Actions for continuous integration and deployment:

**Workflows:**
- **CI Workflow** (`.github/workflows/ci.yml`): Runs tests across Python 3.11-3.12, generates coverage reports
- **Code Quality** (`.github/workflows/quality.yml`): Linting, type checking, security scanning
- **Release** (`.github/workflows/release.yml`): Automated releases from version tags

**Status:** View workflow runs and badges in README.md

**Documentation:** See `.github/CICD.md` for detailed CI/CD documentation

## Pre-Commit Hooks

The project uses pre-commit hooks to enforce code quality standards locally before pushing to GitHub.

**Installation:**
```bash
# Activate your venv first
source .venv/bin/activate

# Install and configure
pip install pre-commit
pre-commit install
```

**Hooks Included:**
- **Formatting**: black, isort
- **Linting**: flake8, ruff
- **Security**: bandit, detect-secrets
- **File checks**: trailing whitespace, YAML/JSON validation, etc.
- **Custom checks**: Python syntax, import validation

**Usage:**
```bash
# Runs automatically on git commit
git commit -m "Your message"

# Run manually on all files
pre-commit run --all-files

# Run manually on staged files
pre-commit run

# Skip hooks (not recommended)
git commit --no-verify
```

**Manual-only hooks** (run with `--hook-stage manual`):
- `python-import-check`: Verify imports work in venv
- `critical-tests`: Run tests for critical file changes
- `update-copyright`: Update copyright years

**Configuration:** `.pre-commit-config.yaml`

## Database Structure

- SQLite databases store tracking data with timestamps
- Each device maintains its own database
- Node server aggregates data from multiple devices
- Backup system rsyncs databases to central storage

### Result Writer Options

The system supports multiple result writer backends for storing tracking data:

1. **SQLiteResultWriter** (Default, Recommended)
   - Stores data in local SQLite databases
   - No additional setup required
   - Backed up via rsync to node server
   - Best performance and reliability

2. **MySQLResultWriter** (Optional, Hidden by Default)
   - Stores data in MariaDB/MySQL database server
   - Requires manual configuration and service setup
   - Hidden from web UI by default (since v1.5)
   - Enable only if you have specific need for centralized database

3. **dbAppender**
   - Appends data to existing database
   - Used for resuming interrupted experiments

### Enabling MySQL/MariaDB Result Writer

By default, MySQLResultWriter is hidden from the web UI to simplify the user experience. Most users should use SQLiteResultWriter. If you have a specific need for MySQL/MariaDB:

**1. Enable in Configuration**

Edit `/etc/ethoscope/ethoscope.conf` and set:

```json
{
  "device_options": {
    "enable_mysql_result_writer": true
  }
}
```

**2. Enable Backup Service**

The MariaDB backup service is not enabled by default. To enable it:

```bash
sudo systemctl enable --now ethoscope_backup_mysql.service
```

**3. Restart Node Server**

After changing the configuration, restart the node server for changes to take effect:

```bash
sudo systemctl restart ethoscope_node.service
```

**4. Verify in Web UI**

Open the ethoscope detail page and start tracking. MySQLResultWriter should now appear in the "Result Writer" dropdown.

**Note**: You may need to clear your browser cache if the option doesn't appear immediately.

### MariaDB Credentials

If using MySQLResultWriter, the default credentials are:
- **Database**: `{machine_name}_db`
- **User**: `ethoscope`
- **Password**: `ethoscope`

**Location**: `src/ethoscope/ethoscope/control/tracking.py:219`

## Hardware Integration

- Camera interfaces support PiCamera and generic OpenCV cameras
- GPIO interfaces for hardware control (stimulators, sensors)
- Serial communication for external hardware (Lynx motion controllers, Arduinos)
- Network discovery via Zeroconf for automatic device detection

## Releasing a new SD image

Images are hosted on the lab server (`ctb.gilest.ro`), not on box.com. Publishing is
one command — no commit, no pull, no container restart:

```bash
# prepare the image (update /opt/ethoscope, shrink, retag, zero free space)
sudo ./accessories/ethoscope-image.sh --all /path/to/ethoscope.img

# zip, checksum, upload, verify, publish
./accessories/publish-image.sh /path/to/ethoscope.img
```

`publish-image.sh` reads `/etc/sdimagename` out of the image to derive the published
name, compresses it, uploads it with a resumable `rsync`, verifies the checksum
remotely, and only then uploads a sidecar `<file>.img.zip.json` manifest. Because the
manifest lands last, an interrupted upload is never advertised — just re-run the
command and it resumes. Run it as a normal user (it uses your ssh keys); reading the
image needs no root. Use `--dry-run` to rehearse, `--prune N` to keep only the N newest
images on the server.

### Where things live

| Piece | Location |
|---|---|
| Image files + manifests | `ctb.gilest.ro:/srv/http/ethoscope/images/` |
| Public download URL | `https://repo.ethoscope.lab.gilest.ro/images/<name>.img.zip` |
| Stable per-model redirect | `https://ethoscope-resources.lab.gilest.ro/latest_sd_image/pi4` |
| Web server for the files | `repo.ethoscope` container — `Docker/image_server/docker-compose.yml` |
| Resources API | `ethoscope-resources` container — `Docker/resource_server/` |

`pa_server.py` builds its image list from the sidecar manifests (newest first) and
appends any entry in `contents/links.json` that no manifest supersedes — so the LiveCD
ISO and the older box.com links keep working, and are retired simply by re-publishing
that image. `links.json` and `news.txt` are now re-read whenever they change on disk;
only a change to `pa_server.py` itself needs
`docker compose up -d --build` (the Dockerfile copies it in at build time).

To roll back a release, delete the sidecar manifest on the server
(`rm /srv/http/ethoscope/images/<name>.img.zip.json`) — the previous image becomes the
newest again immediately, and the file itself stays downloadable by direct URL.

## Important Notes

- Python 3.11+ required for both device and node packages. The code uses PEP 604
  unions (`X | None`) and `zip(..., strict=)`, which are 3.10+, and ruff/black
  target py311. Raspbian Bullseye (3.9) is no longer supported.
- OpenCV is used extensively for computer vision operations
- CherryPy/Bottle used for web servers
- Frontend uses Angular.js (legacy version, source-only)
- System designed for Raspberry Pi deployment but works on other Linux systems

## See also
@CLAUDE.local.md
