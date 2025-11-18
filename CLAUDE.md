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
- **Key Location**: `/etc/ethoscope/keys/` (RSA 2048-bit key pair)
- **Target User**: `ethoscope` user on ethoscope devices
- **Password**: Default password is "ethoscope" (used only for initial key transfer)

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
sshpass -p "ethoscope" ssh-copy-id -i /etc/ethoscope/keys/id_rsa.pub ethoscope@<device-ip>

# Or without sshpass (will prompt for password)
ssh-copy-id -i /etc/ethoscope/keys/id_rsa.pub ethoscope@<device-ip>
```

### Troubleshooting

**SSH key icon shows orange/red:**
1. Check network connectivity to ethoscope device
2. Verify ethoscope user password is "ethoscope"
3. Check `/etc/ethoscope/keys/` exists on node with proper permissions
4. Review node logs for SSH transfer errors
5. Try manual SSH key transfer (see above)

**Passwordless SSH not working despite green icon:**
1. SSH status may be cached - wait for next device status change
2. Check `/home/ethoscope/.ssh/authorized_keys` on ethoscope device
3. Verify SSH daemon is running on ethoscope
4. Check firewall rules if applicable

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
- **CI Workflow** (`.github/workflows/ci.yml`): Runs tests across Python 3.8-3.12, generates coverage reports
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

# Run the setup script
./scripts/setup_pre_commit.sh

# Or manually
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

## Hardware Integration

- Camera interfaces support PiCamera and generic OpenCV cameras
- GPIO interfaces for hardware control (stimulators, sensors)
- Serial communication for external hardware (Lynx motion controllers, Arduinos)
- Network discovery via Zeroconf for automatic device detection

## Important Notes

- Python 3.7+ required for device package, 3.8+ for node package
- OpenCV is used extensively for computer vision operations
- CherryPy/Bottle used for web servers
- Frontend uses Angular.js (legacy version, source-only)
- System designed for Raspberry Pi deployment but works on other Linux systems

## See also
@CLAUDE.local.md
