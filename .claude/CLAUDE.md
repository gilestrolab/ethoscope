# Ethoscope Project - Claude Instructions

## Project Overview
This is the ethoscope platform for automated behavioral monitoring of small model organisms. The project consists of two main components:

- **Device package** (`src/`) - Core ethoscope software that runs on individual devices
- **Node server** (`node_src/`) - Central web interface and coordination server with Angular 1.8.3 + Bootstrap 4

## Framework Status
- **Angular**: Upgraded from 1.7.8 to 1.8.3 ✅
- **Bootstrap**: Upgraded from 3.x to 4.x ✅
- **Build System**: Babel transpilation for ES6+ JavaScript ✅
- **Race Conditions**: Fixed modal form population issues ✅
- **Form Ordering**: Implemented consistent ordering with OrderedDict ✅

## Installation Commands

### Node Server (node_src) - Complete Installation
```bash
make install-all        # Install Python backend + npm frontend (recommended)
make install-dev        # Development mode with editable Python package
make install-production # Production deployment
```

### Device Package (src) - Ethoscope Device
```bash
make install            # Standard installation with device dependencies
make install-dev        # Development with editable package
make install-production # Production deployment
make test               # Run comprehensive test suite
```

## Development Workflow

### Frontend Development (node_src)
- **Source files**: Edit in `static/js/controllers/` 
- **Built files**: Browser loads from `static/dist/js/`
- **Build commands**:
  - `npm run build` - Build production assets
  - `npm run dev` - Watch mode for development
  - `make build` - Makefile shortcut

### Important Notes
- **Always run `npm run build`** after editing JavaScript source files
- The browser loads built files from `static/dist/js/`, not source files
- Use `npm run dev` for file watching during development
- Source vs built files separation is critical for the build system

### Testing
- **Node**: Run frontend tests and backend API tests
- **Device**: `make test` runs unit tests, integration tests, API tests
- Test both components before committing changes

## Recent Major Changes
- Frontend framework modernization (Angular 1.8.3, Bootstrap 4)
- Unified installation system with Makefiles for both packages
- Comprehensive documentation (README.md) for both src/ and node_src/
- Build system integration with Babel transpilation
- Race condition fixes in modal forms and consistent form section ordering

## Build System
- **Frontend**: Babel transpiles ES6+ → browser-compatible JavaScript
- **Backend**: Standard Python packaging with pyproject.toml
- **Integration**: Single command installation handles both components