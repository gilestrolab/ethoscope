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
- `scripts/server.py` - Main node web server (runs on port 80)
- `ethoscope_node.utils.device_scanner` - Device discovery and monitoring
- `ethoscope_node.utils.backups_helpers` - Data synchronization and backup
- `ethoscope_node.utils.etho_db` - Database management for experimental data
- Frontend: Angular.js SPA in `static/` directory (source-only, no build step)

### 3. Update System (`src/updater/`)
Handles software updates for both devices and nodes via git-based distribution.

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
These can be reinstalled using `accessories/

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

## Development Workflow

1. **Device Development**: Work in `src/ethoscope/` for tracking algorithms, hardware interfaces, and device-specific features
2. **Node Development**: Work in `src/node/` for web interface, device management, and data collection
3. **Testing**: Always run tests before committing changes
4. **Branching**: Use `dev` branch for development, `master` for stable releases

## Database Structure

- SQLite databases store tracking data with timestamps
- Each device maintains its own database
- Node server aggregates data from multiple devices
- Backup system syncs databases to central storage

## Hardware Integration

- Camera interfaces support PiCamera and generic OpenCV cameras
- GPIO interfaces for hardware control (stimulators, sensors)
- Serial communication for external hardware (Lynx motion controllers)
- Network discovery via Zeroconf for automatic device detection

## Important Notes

- Python 3.7+ required for device package, 3.8+ for node package
- OpenCV is used extensively for computer vision operations
- CherryPy/Bottle used for web servers
- Frontend uses Angular.js (legacy version, source-only)
- System designed for Raspberry Pi deployment but works on other Linux systems

## Development Environment Setup

- **Virtual Environment Commands**:
  - Run `source ~/Data/virtual_envs/python/ethoscope/bin/activate` to load the appropriate venv environment for the ethoscope and the node