# Ethoscope Node Server

This directory contains the complete Ethoscope node server - both the Python backend and the web frontend built with Angular 1.8.3 and Bootstrap 4.

## Prerequisites

- Python 3.7+ with pip
- Node.js (version 14 or higher) 
- npm (comes with Node.js)

## Installation

### Complete Installation (Recommended)
Install both backend and frontend in one command:
```bash
make install-all
```

### Development Installation
For development with editable Python package:
```bash
make install-dev
```

### Manual Installation
```bash
# Install Python backend
pip install .                    # Production
# OR
pip install -e .                 # Development (editable)

# Install and build frontend
npm install
npm run build
```

### Legacy Installation
The original installation method (still supported):
```bash
sudo python setup.py develop
```

*Note: You do not need to reinstall the Python package every time you make changes to Python code when using editable installs.*

## Development

### File Watching Mode
For development with automatic rebuilds when files change:
```bash
make dev
# OR
npm run dev
```

### Production Build
```bash
make build
# OR
npm run build
```

## Framework Versions

- **Angular**: 1.8.3 (upgraded from 1.7.8)
- **Bootstrap**: 4.x (upgraded from 3.x)
- **Build System**: Babel with ES6+ transpilation

## Build System

The build system uses Babel to transpile modern JavaScript (ES6+) to browser-compatible code:

- **Source files**: `static/js/controllers/` and `static/js/script.js`
- **Output directory**: `static/dist/js/`
- **Configuration**: `package.json` and Babel presets

## Important Notes

1. **Source vs Built Files**: The browser loads files from `static/dist/js/`, not the source files in `static/js/controllers/`. Always run `npm run build` after making changes to source files.

2. **Development Workflow**: 
   - Edit source files in `static/js/controllers/`
   - Run `npm run build` or `npm run dev` to transpile
   - Browser loads transpiled files from `static/dist/js/`

3. **Deployment**: In production, ensure the build step is run as part of the deployment process.

## Integration with Node Installation

For new node installations, ensure the following steps are included:

1. Install Node.js and npm on the system
2. Run `cd /opt/ethoscope-git/node_src && make install-all`
3. Ensure the ethoscope node service can access the built files

### Production Deployment
For production environments:
```bash
cd /opt/ethoscope-git/node_src
make install-production
```

This installs the Python package without editable mode and builds optimized frontend assets.

## Directory Structure

```
node_src/
├── package.json          # npm configuration and build scripts
├── package-lock.json     # Locked dependency versions
├── Makefile              # Build system shortcuts
├── setup.py              # Python package installation (legacy)
├── pyproject.toml        # Python package configuration (modern)
├── ethoscope_node/       # Python backend package
│   ├── __init__.py
│   └── utils/            # Backend utilities
├── scripts/              # Backend server scripts
│   ├── server.py         # Main node server
│   ├── backup_tool.py    # Backup management
│   └── video_backup_tool.py
├── static/               # Frontend web assets
│   ├── js/
│   │   ├── controllers/  # Source JavaScript files (edit these)
│   │   └── script.js     # Main application file
│   ├── dist/
│   │   └── js/           # Built JavaScript files (browser loads these)
│   ├── css/              # CSS files (Bootstrap 4 + custom styles)
│   ├── pages/            # HTML templates
│   └── fonts/            # Web fonts
└── README.md             # This file
```

## Troubleshooting

### Build Issues
- Ensure Node.js and npm are installed: `node --version && npm --version`
- Run `npm install` to install dependencies
- Check for syntax errors in source files
- Verify permissions on output directory

### Browser Loading Issues
- Verify files exist in `static/dist/js/`
- Check browser developer tools for 404 errors
- Ensure build process completed successfully
- Check web server configuration serves static files correctly

### Development Issues
- Use `npm run dev` for file watching during development
- Check console output for Babel transpilation errors
- Ensure source files use modern JavaScript syntax correctly