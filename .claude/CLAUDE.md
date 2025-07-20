# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Architecture

The ethoscope platform is a distributed system for automated behavioral monitoring of small model organisms. It consists of two main packages:

### Device Package (`src/node`)
The core ethoscope software that runs on individual Raspberry Pi devices. Key components:
- **`ethoscope.core`**: Monitor, ROI, and tracking unit abstractions
- **`ethoscope.trackers`**: Computer vision algorithms (AdaptiveBGModel, etc.)
- **`ethoscope.stimulators`**: Behavioral intervention modules (sleep deprivation, odour, optomotor)
- **`ethoscope.hardware`**: Camera interfaces (PiCamera, V4L2) and GPIO control
- **`ethoscope.web_utils.control_thread`**: Main device control loop and web API
- **`scripts/device_server.py`**: Web server providing device control interface

### Node Server (`src/ethoscope`)
Central coordination server with Python backend and Angular frontend:
- **`ethoscope_node.utils`**: Device scanning, backup management, database operations
- **`scripts/server.py`**: Main node web server (Bottle framework)
- **`static/js/controllers/`**: Angular 1.8.3 frontend controllers (source files)
- **`static/dist/js/`**: Babel-transpiled JavaScript (browser loads these)

## Development Commands

### Installation
```bash
# Node server (Python backend + Angular frontend)
cd node_src && make install-dev

# Device package (with hardware dependencies)
cd src && make install-dev

# Test device package
cd src && make test
```

### Frontend Development (Critical Build Process)
```bash
cd node_src

# Build after editing source files (REQUIRED)
npm run build

# Watch mode for development
npm run dev

# Source files: static/js/controllers/*.js
# Built files: static/dist/js/*.js (browser loads these)
```

### Testing
```bash
# Device package comprehensive testing
cd src && make test                    # All tests
cd src && make test-unit              # Unit tests only
cd src && make test-integration       # Integration tests only

# Specific test execution
cd src && python -m pytest ethoscope/tests/unittests/test_target_roi_builder.py
cd src && bash ethoscope/tests/integration_server_tests/test_config.sh
```

## Key Architecture Patterns

### Device Control Flow
Devices run a control thread (`control_thread.py`) that orchestrates:
1. **Camera input** → **Tracker** → **ROI Builder** → **Monitor**
2. **Stimulator** modules trigger based on behavioral data
3. **Web API** exposes control endpoints for the node server

### Node-Device Communication
- Node scans network for devices using `EthoscopeScanner`
- Devices register with node and receive experiment configurations
- Node aggregates data and provides centralized web interface

### Frontend Build System
- **Source**: Modern ES6+ JavaScript in `static/js/controllers/`
- **Build**: Babel transpiles to browser-compatible JavaScript
- **Output**: `static/dist/js/` (what browsers actually load)
- **Critical**: Always build after editing source files

### Option System Architecture
Both tracking and recording use `OrderedDict` for consistent form ordering:
- **`control_thread.py`**: Defines available trackers, stimulators, ROI builders
- **Frontend**: Dynamically generates forms based on server options
- **Key fix**: Race condition in form population resolved with `selectedOptionName` parameter

## Branching Strategy
- **`master`**: Stable releases only (last updated March 2022)
- **`dev`**: Active development branch used in @gilestrolab
- **Workflow**: Feature branches → `dev` → testing → `master`

## Hardware Dependencies
- **Raspberry Pi 3/4**: Primary target platform
- **Camera modules**: PiCamera or USB cameras via V4L2
- **GPIO interfaces**: For stimulators and sensors
- **MySQL/MariaDB**: Data storage on devices


## Local development
- use `source /home/gg/Data/virtual_envs/python/ethoscope/bin/activate` to activate the appropriate virtual environment
- run the server with `cd /home/gg/Data/ethoscope_project/ethoscope/src/node/scripts && python server.py -D --port 8080` and optionally specific flags about the location of configs and results