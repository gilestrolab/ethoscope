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
- Tests are located in `src/ethoscope/ethoscope/tests/`
- Use `python -m pytest` to run tests
- Integration tests require mock devices/hardware
- Test configuration files are in `tests/integration_server_tests/`

## Key System Services

The system uses systemd services for deployment:

- `ethoscope_device.service` - Main device tracking service
- `ethoscope_node.service` - Central node management server
- `ethoscope_backup.service` - Data backup and synchronization
- `ethoscope_video_backup.service` - Video file backup
- `ethoscope_update.service` - Software update management

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