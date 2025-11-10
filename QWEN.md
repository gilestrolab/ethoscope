# Ethoscope Project - Developer Context

## Project Overview

The Ethoscope project is a platform for high-throughput ethomics - the study of animal behavior. It consists of two main components:

1.  **Device Package (`src/ethoscope`)**: Runs on individual ethoscope devices for real-time video tracking, analysis, and behavioral intervention. Key features include computer vision tracking algorithms, modular stimulator interfaces, and data logging.
2.  **Node Server (`src/node`)**: A central computer that syncs and controls multiple ethoscope devices. Contains both a Python backend and a web frontend built with Angular.

The project uses Python 3.7+ as its primary language, with OpenCV for computer vision and a web framework (CherryPy/Bottle) for device interfaces. The node server's frontend was previously using a build system but is now source-only.

## Key Technologies

*   **Language**: Python 3.7+
*   **Computer Vision**: OpenCV
*   **Web Frameworks**: CherryPy/Bottle (device), Angular 1.8.3 (node)
*   **Frontend**: Bootstrap 4 (node)
*   **Build System**: Make, pip
*   **Testing**: pytest
*   **Code Quality**: black, ruff

## Architecture

```
ethoscope/
├── src/
│   ├── ethoscope/            # Device package
│   │   ├── core/             # Core tracking and monitoring
│   │   ├── trackers/         # Video tracking algorithms
│   │   ├── roi_builders/     # Region of Interest detection
│   │   ├── stimulators/      # Behavioral intervention modules
│   │   ├── hardware/         # Camera and device interfaces
│   │   ├── utils/            # Utility functions
│   │   ├── web_utils/        # Web server interfaces
│   │   ├── tests/            # Test suite
│   │   └── scripts/          # Device executables (device_server.py, ethoclient.py)
│   └── node/                 # Node server
│       ├── ethoscope_node/   # Python backend
│       ├── scripts/          # Backend server scripts
│       ├── static/           # Frontend web assets (source-only)
│       └── tests/            # Backend tests
├── prototypes/               # Developmental trials
├── scripts/                  # System service files and installation scripts
├── accessories/              # Utility scripts
└── Docker/                   # Docker configurations
```

## Building and Running

### Device Package (`src/ethoscope`)

*   **Install** (recommended): `make install`
*   **Development Install**: `make install-dev`
*   **Production Install**: `make install-production`
*   **Manual Install**: `pip install .[device]` or `pip install -e .[device,dev]`

### Node Server (`src/node`)

*   **Install All** (recommended): `make install-all`
*   **Development Install**: `make install-dev`
*   **Production Install**: `make install-production`
*   **Manual Install**: `pip install .` or `pip install -e .`

### Running Services

*   **Device Server**: `device_server` or `python scripts/device_server.py`
*   **Node Server**: Run the appropriate script from `src/node/scripts/`

## Testing

The project has a comprehensive testing setup using `pytest` for both device and node packages.

### Running Tests

*   **All Tests**: `python run_tests.py`
*   **Device Tests**: `cd src/ethoscope && make test` or `python -m pytest ethoscope/tests/`
*   **Node Tests**: `cd src/node && make test` or `python -m pytest tests/`
*   **Specific Test Types**:
    *   Device: `make test-unit`, `make test-integration`
    *   Node: `make test-unit`, `make test-integration`, `make test-functional`

### Advanced Testing

*   **Coverage**: `python run_tests.py --coverage`
*   **Quality Checks**: `python run_tests.py --quality` (runs flake8, mypy)
*   **Security Checks**: `python run_tests.py --security` (runs bandit)
*   **Verbose Output**: Add `-v` flag

## Development Conventions

*   **Code Style**: The project uses `black` for code formatting and `ruff` for linting. Check `pyproject.toml` for configurations.
*   **Version Control**:
    *   `main` branch: Stable, tested software.
    *   `dev` branch: Fairly stable development version.
    *   Workflow: Create issue branches from `dev`, test thoroughly, merge to `dev`, then deploy. Only merge `dev` to `main` after extensive testing.
*   **Dependencies**:
    *   Device dependencies (OpenCV, etc.) are specified in `src/ethoscope/setup.py` and `requirements.txt`.
    *   Node dependencies are managed via `pip` for the backend.
*   **Frontend Development**: The node frontend is now source-only. Changes to JavaScript files in `src/node/static/js/` are directly used without a build step.

## Important Notes

1.  **Editable Installs**: For development, use editable installs (`pip install -e`) to avoid reinstalling the package after every code change.
2.  **Frontend**: The frontend for the node server is now source-only, simplifying the development workflow.
3.  **Testing**: Always run tests after making changes. The `run_tests.py` script provides a unified interface for testing both packages.