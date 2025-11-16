Ethoscope
============

[![CI](https://github.com/gilestrolab/ethoscope/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/gilestrolab/ethoscope/actions/workflows/ci.yml)
[![Code Quality](https://github.com/gilestrolab/ethoscope/actions/workflows/quality.yml/badge.svg?branch=main)](https://github.com/gilestrolab/ethoscope/actions/workflows/quality.yml)
[![codecov](https://codecov.io/gh/gilestrolab/ethoscope/branch/main/graph/badge.svg)](https://codecov.io/gh/gilestrolab/ethoscope)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![GitHub release](https://img.shields.io/github/v/release/gilestrolab/ethoscope)](https://github.com/gilestrolab/ethoscope/releases)
[![Documentation](https://img.shields.io/badge/docs-lab.gilest.ro-brightgreen)](https://lab.gilest.ro/ethoscope-manual)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

The **Ethoscope** is a platform for high-throughput ethomics: automated behavioral monitoring of small organisms like *Drosophila melanogaster*. This is the GitHub repository for the software part of the [ethoscope platform](https://lab.gilest.ro/ethoscope).

All technical information regarding ethoscope is compiled in [our documentation](https://lab.gilest.ro/ethoscope-manual).

## What's New in v2.0

Version 2.0 is a major release with significant improvements:

- **CI/CD Pipeline**: Automated testing, quality checks, and releases via GitHub Actions
- **Testing Infrastructure**: 80%+ code coverage with comprehensive test suites
- **Authentication System**: User management and session handling
- **Enhanced Notifications**: Multi-channel alerts (Email, Slack, Mattermost)
- **Improved Backups**: Robust MySQL, SQLite, and video backup systems
- **Docker Support**: Full containerization for development and deployment
- **Code Quality**: Pre-commit hooks, linting, and security scanning
- **Documentation**: Comprehensive guides for testing, deployment, and CI/CD

See the [release notes](https://github.com/gilestrolab/ethoscope/releases/tag/v2.0) for full details.

## Quick Start

### Installation

For device package:
```bash
cd src/ethoscope
make install
```

For node package:
```bash
cd src/node
make install-all
```

### Docker Development Environment

For quick testing and development:
```bash
cd Docker/node
docker compose up -d
```

See [Docker documentation](Docker/node/README.md) for details.

### Testing

Run all tests:
```bash
python run_tests.py
```

Run with coverage:
```bash
python run_tests.py --coverage
```

See [TESTING.md](docs/TESTING.md) for comprehensive testing documentation.

## Organisation of the Code

* **`src/ethoscope/`** - Main Python package for video monitors (devices). Can also be used as a standalone offline tracking tool.
* **`src/node/`** - Software stack for the node server that synchronizes and controls multiple devices.
* **`services/`** - Systemd service files for device and node daemons.
* **`accessories/`** - Utility scripts, database tools, and hardware configurations.
* **`Docker/`** - Docker configurations for node, virtuascope, and development environments.
* **`docs/`** - Comprehensive documentation for features and systems.
* **`.github/`** - CI/CD workflows and GitHub Actions configuration.

## Development Workflow

### Branching System

* **`main`** - Stable releases only. Protected branch with required CI checks.
* **`dev`** - Development branch used in @gilestrolab for testing and integration.

### Workflow

1. Create feature/bugfix branches from `dev`
2. Implement changes with tests
3. Submit pull request to `dev`
4. CI runs automated tests and quality checks
5. After review and approval, merge to `dev`
6. Deploy to @gilestrolab devices for real-world testing
7. After several weeks of stable operation, merge `dev` to `main`
8. Create release tag for public deployment

**Latest stable release**: v2.0 (November 2025)

### Code Quality

The project uses pre-commit hooks to maintain code quality:

```bash
# Install pre-commit hooks
./scripts/setup_pre_commit.sh

# Run hooks manually
pre-commit run --all-files
```

Hooks include:
- **Formatting**: black, isort/ruff
- **Linting**: ruff, flake8
- **Security**: bandit, detect-secrets
- **Testing**: Integration tests for critical changes

## Features

### Device (Ethoscope) Package
- **Real-time Tracking**: Adaptive background subtraction for robust animal tracking
- **ROI Templates**: Built-in templates for common experimental setups (20-tube, 30-tube, arenas)
- **Multi-Stimulator**: Support for sleep deprivation, optomotor, odor delivery, and custom stimulators
- **Video Recording**: Synchronized video recording with tracking data
- **Hardware Integration**: GPIO control, camera support (PiCamera, PiCamera2, USB cameras)

### Node Package
- **Device Management**: Centralized control of multiple ethoscope devices
- **Authentication**: User management with role-based access control
- **Backup System**: Automated MySQL, SQLite, and video backups with integrity checking
- **Notifications**: Multi-channel alerts (Email, Slack, Mattermost) for device issues
- **Web Interface**: AngularJS-based frontend for monitoring and control
- **Database Management**: SQLite and MySQL support with caching and resilience

### Infrastructure
- **CI/CD**: Automated testing across Python 3.9-3.12, quality checks, and releases
- **Testing**: 80%+ code coverage with unit, integration, and functional tests
- **Docker**: Development environments for node, virtuascope, and sandbox testing
- **Pre-commit Hooks**: Automated code formatting, linting, and security scanning

## Architecture

The ethoscope platform consists of:

1. **Ethoscope Devices**: Raspberry Pi-based video monitors with camera and optional hardware modules
2. **Node Server**: Central management server that coordinates devices and collects data
3. **Update System**: Git-based software distribution and update management

See [CLAUDE.md](CLAUDE.md) for detailed architecture documentation.

## Documentation

- **[Testing Guide](docs/TESTING.md)** - Comprehensive testing documentation
- **[CI/CD Documentation](.github/CICD.md)** - GitHub Actions workflows and pipelines
- **[Backup System](docs/BACKUP_STATUS_API.md)** - Backup status and management
- **[Multi-Stimulator](docs/MULTI_STIMULATOR_FEATURE.md)** - Using multiple stimulators
- **[Sleep Restriction](docs/SLEEP_RESTRICTION_USAGE_GUIDE.md)** - Sleep restriction protocols
- **[Package Structure](CLAUDE.md)** - Architecture and package organization

## Contributing

We welcome contributions! Please:

1. Fork the repository
2. Create a feature branch from `dev`
3. Write tests for new functionality
4. Ensure all tests pass and code quality checks succeed
5. Submit a pull request to `dev`

See our [CI/CD documentation](.github/CICD.md) for details on automated checks.

## Citation

If you use ethoscope in your research, please cite:

> Geissmann Q, Garcia Rodriguez L, Beckwith EJ, Gilestro GF (2019)
> **Ethoscopes: An open platform for high-throughput ethomics**
> *PLOS Biology* 17(10): e3000461
> https://doi.org/10.1371/journal.pbio.3000461

## Support

- **Documentation**: https://lab.gilest.ro/ethoscope-manual
- **Issues**: https://github.com/gilestrolab/ethoscope/issues
- **Lab Website**: https://lab.gilest.ro

## License

Ethoscope source code is licensed under **GPL-3.0** (see [LICENSE](LICENSE)).

---

**Maintained by**: [Gilestro Lab](https://lab.gilest.ro)
**Latest Release**: [v2.0](https://github.com/gilestrolab/ethoscope/releases/tag/v2.0)
