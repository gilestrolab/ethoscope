# Ethoscope Device Package

This directory contains the core ethoscope package that runs on individual ethoscope devices for automated behavioral monitoring and analysis.

## Overview

The Ethoscope is a platform for high-throughput ethomics - the study of animal behavior. This package provides the core APIs, tracking algorithms, and device interfaces that power individual Ethoscope units.

**Key Features:**
- Real-time video tracking and analysis
- Modular stimulator and sensor interfaces  
- Data logging and experiment management
- Integration with the broader Ethoscope ecosystem

## Prerequisites

- Python 3.7+ with pip
- OpenCV dependencies (for video processing)
- Hardware-specific dependencies (camera, GPIO, etc.)

## Installation

### Quick Installation (Recommended)
```bash
make install
```

### Development Installation
For development with editable package:
```bash
make install-dev
```

### Production Installation
For production deployment on devices:
```bash
make install-production
```

### Manual Installation
```bash
# Install with all device dependencies
pip install .[device]

# Development installation (editable)
pip install -e .[device,dev]

# Basic installation (minimal dependencies)
pip install .
```

### Legacy Installation
The original installation method (still supported):
```bash
sudo python setup.py develop
```

*Note: You do not need to reinstall the package every time you make changes to Python code when using editable installs.*

## Package Structure

### Core Components
- **`ethoscope.core`** - Fundamental tracking and monitoring classes
- **`ethoscope.trackers`** - Computer vision tracking algorithms
- **`ethoscope.roi_builders`** - Region of Interest detection and management
- **`ethoscope.stimulators`** - Behavioral intervention modules
- **`ethoscope.hardware`** - Camera and interface abstractions

### Device Scripts
- **`device_server.py`** - Main device server for web interface and control
- **`device_listener.py`** - Network discovery and registration
- **`ethoclient.py`** - Command-line client for device interaction

### Testing Framework
- **Unit tests** - Component-level testing
- **Integration tests** - End-to-end API testing
- **Static test files** - Sample videos and images for testing

## Dependencies

### Core Dependencies (always installed)
- `numpy>=1.6.1` - Numerical computations
- `scipy>=0.15.1` - Scientific computing

### Device Dependencies (install with `[device]`)
- `opencv-python>=4.0.0` - Computer vision and video processing
- `picamera>=1.8` - Raspberry Pi camera interface
- `cherrypy>=3.6.0` - Web server framework
- `bottle>=0.12.8` - Lightweight web framework
- `mysql-connector-python>=8.0.16` - Database connectivity
- `pyserial>=2.7` - Serial communication
- `GitPython>=1.0.1` - Git integration for updates

### Development Dependencies (install with `[dev]`)
- `pytest>=6.0.0` - Testing framework
- `pytest-cov>=2.10.0` - Coverage reporting
- `Sphinx>=1.4.4` - Documentation generation
- `mock>=2.0.0` - Testing utilities

## Usage

### Running the Device Server
```bash
# Using installed script
device_server

# Or directly
python scripts/device_server.py
```

### Command-line Client
```bash
# Using installed command
ethoclient --help

# Or directly  
python scripts/ethoclient.py --help
```

### Development and Testing
```bash
# Run all tests
make test

# Run specific test suites
python -m pytest ethoscope/tests/unittests/
python -m pytest ethoscope/tests/integration_api_tests/

# Generate documentation
make docs
```

## Integration with Device Installation

This package is typically installed as part of the complete ethoscope device setup. The device installation script should include:

1. Install system dependencies (OpenCV, camera drivers, etc.)
2. Run `cd /opt/ethoscope-device/src && make install-production`
3. Configure systemd services
4. Set up device-specific configuration

## Development Workflow

1. **Code Changes**: Edit files in the `ethoscope/` package
2. **Testing**: Run `make test` to verify changes
3. **Documentation**: Update docstrings and generate docs with `make docs`
4. **No Reinstallation**: If installed with `-e`, changes are immediately available

## Directory Structure

```
src/
├── pyproject.toml        # Modern Python package configuration
├── setup.py              # Legacy setup (minimal)
├── requirements.txt      # Pinned dependency versions
├── Makefile              # Build and installation shortcuts
├── ethoscope/            # Main Python package
│   ├── core/            # Core tracking and monitoring
│   ├── trackers/        # Video tracking algorithms
│   ├── roi_builders/    # Region of Interest detection
│   ├── stimulators/     # Behavioral intervention modules
│   ├── hardware/        # Camera and device interfaces
│   ├── utils/           # Utility functions and helpers
│   ├── web_utils/       # Web server and control interfaces
│   └── tests/           # Comprehensive test suite
├── scripts/              # Device executable scripts
│   ├── device_server.py # Main device web server
│   ├── device_listener.py # Network discovery service
│   └── ethoclient.py    # Command-line interface
└── docs/                # Sphinx documentation
```

## Troubleshooting

### Installation Issues
- Ensure Python 3.7+ is installed: `python --version`
- Install system dependencies for OpenCV: camera drivers, etc.
- Check hardware permissions (camera, GPIO access)
- Verify pip version: `pip --version`

### Runtime Issues
- Check device permissions and hardware connections
- Verify network connectivity for node communication
- Review logs: `journalctl -u ethoscope_device.service`
- Test hardware with integration tests

### Development Issues
- Use `pip install -e .[device,dev]` for development
- Run tests frequently: `make test`
- Check import errors with simple import test
- Generate fresh documentation: `make docs`

## Hardware Requirements

- **Raspberry Pi 3/4** or compatible ARM board
- **Camera module** - Pi Camera or USB camera
- **Storage** - SD card with sufficient space
- **Network** - Ethernet or WiFi connectivity
- **Optional** - GPIO devices for stimulation/sensing

## More Information

- **Homepage**: https://github.com/gilestrolab/ethoscope
- **Documentation**: http://lab.gilest.ro/ethoscope  
- **Manual**: https://lab.gilest.ro/ethoscope-manual
- **License**: GPL-3.0
