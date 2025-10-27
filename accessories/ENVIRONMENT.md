# Ethoscope Environment Variables

This document describes the environment variable configuration system for ethoscope installations.

## Overview

Ethoscope supports configuration through environment variables, which provide a centralized way to manage system-wide settings. This is particularly useful for:

- Customizing installation paths for non-standard deployments
- Simplifying script configuration across the system
- Enabling consistent behavior across services and cron jobs
- Supporting containerized deployments (Docker)

## Installation

1. **Copy the template file:**
   ```bash
   sudo cp /opt/ethoscope/accessories/environment.template /etc/ethoscope/environment
   ```

2. **Edit the configuration:**
   ```bash
   sudo nano /etc/ethoscope/environment
   ```

3. **Customize the values** according to your installation needs (see Configuration Reference below)

4. **Restart services** to apply changes:
   ```bash
   sudo systemctl restart ethoscope_node    # For node installations
   sudo systemctl restart ethoscope_device  # For device installations
   ```

## How It Works

### Systemd Services

The `ethoscope_node.service` automatically loads environment variables using the `EnvironmentFile` directive:

```ini
[Service]
EnvironmentFile=-/etc/ethoscope/environment
ExecStart=/usr/bin/python /opt/ethoscope/src/node/scripts/server.py
```

The `-` prefix means the file is optional - the service will still start even if the file doesn't exist.

### Shell Scripts

Shell scripts (like those in `accessories/cronie_scripts/`) automatically source the environment file:

```bash
# Load environment variables if available
if [ -f /etc/ethoscope/environment ]; then
    source /etc/ethoscope/environment
fi
```

### Python Scripts

Python scripts use `os.getenv()` to read environment variables with fallback defaults:

```python
import os

data_dir = os.getenv("ETHOSCOPE_DATA_DIR", "/ethoscope_data")
config_dir = os.getenv("ETHOSCOPE_CONFIG_DIR", "/etc/ethoscope")
```

## Configuration Reference

### Core Paths

#### `ETHOSCOPE_DATA_DIR`
- **Default:** `/ethoscope_data`
- **Description:** Root directory for all ethoscope data (results, videos, sensors, templates)
- **Used by:** Node server, backup scripts, video conversion scripts

#### `ETHOSCOPE_CONFIG_DIR`
- **Default:** `/etc/ethoscope`
- **Description:** Configuration directory (contains ethoscope.conf, database, SSH keys)
- **Used by:** Node server, device server, configuration management

#### `ETHOSCOPE_RESULTS_DIR`
- **Default:** `${ETHOSCOPE_DATA_DIR}/results`
- **Description:** Directory for experiment results and SQLite databases
- **Used by:** Node server, backup scripts, database integrity checker

#### `ETHOSCOPE_VIDEOS_DIR`
- **Default:** `${ETHOSCOPE_DATA_DIR}/videos`
- **Description:** Directory for video recordings
- **Used by:** Node server, backup scripts, h264_to_mp4 converter

#### `ETHOSCOPE_SENSORS_DIR`
- **Default:** `${ETHOSCOPE_DATA_DIR}/sensors`
- **Description:** Directory for sensor data
- **Used by:** Node server, sensor scanner

#### `ETHOSCOPE_TEMPLATES_DIR`
- **Default:** `${ETHOSCOPE_DATA_DIR}/roi_templates`
- **Description:** Directory for ROI (Region of Interest) templates
- **Used by:** Node server, ROI template management

#### `ETHOSCOPE_TMP_DIR`
- **Default:** `/tmp/ethoscope`
- **Description:** Temporary directory for downloads and processing
- **Used by:** Various scripts for temporary file storage

### Node Server Configuration

#### `NODE_PORT`
- **Default:** `80`
- **Description:** Port for the node web server
- **Used by:** `server.py` when starting the node web interface
- **Note:** Requires root privileges for ports < 1024

#### `NODE_DEBUG`
- **Default:** `false`
- **Description:** Enable verbose debug logging (true/false)
- **Used by:** `server.py` for log level configuration

### Backup Configuration

#### `BACKUP_REMOTE_HOST`
- **Default:** Empty (must be configured)
- **Description:** Remote host for rsync backups (user@hostname format)
- **Example:** `backup@node.lab.example.com`
- **Used by:** `sync` script, backup services

#### `BACKUP_REMOTE_PATH`
- **Default:** `/mnt/data`
- **Description:** Remote path for backup storage
- **Used by:** `sync` script, backup services

### Update Service Configuration

#### `UPDATE_SERVICE_URL`
- **Default:** `http://localhost:8888`
- **Description:** URL for the update service
- **Used by:** Update management, web interface update redirects

#### `UPDATE_BRANCH`
- **Default:** `dev`
- **Description:** Git branch to use for updates (dev, main, etc.)
- **Used by:** Update service for pulling software updates

### Python Environment

#### `PYTHON_BIN`
- **Default:** Empty (uses system default)
- **Description:** Path to Python interpreter
- **Example:** `/usr/bin/python3.9`
- **Used by:** Scripts that need specific Python version

#### `PYTHONPATH`
- **Default:** `/opt/ethoscope/src`
- **Description:** Python module search path for ethoscope modules
- **Used by:** Python scripts to locate ethoscope packages

### Advanced Configuration

#### `ETHOSCOPE_DOCKERIZED`
- **Default:** Empty (auto-detection)
- **Description:** Override Docker detection (set to "true" if running in container)
- **Used by:** `server.py` for Docker-specific behavior

#### `SYSTEMCTL_BIN`
- **Default:** Empty (auto-detection)
- **Description:** Path to systemctl binary
- **Used by:** Scripts that manage systemd services

### Service-Specific Variables

#### `VIRTUASCOPE_ENABLED`
- **Default:** `false`
- **Description:** Enable virtual ethoscope instances on the node
- **Used by:** Virtuascope service initialization

#### `VIRTUASCOPE_COUNT`
- **Default:** `1`
- **Description:** Number of virtual ethoscope instances to run
- **Used by:** Virtuascope service initialization

#### `SENSOR_POLL_INTERVAL`
- **Default:** `60`
- **Description:** Sensor polling interval in seconds
- **Used by:** Sensor scanner and virtual sensor services

#### `GPIO_SHUTDOWN_BUTTON_PIN`
- **Default:** `3`
- **Description:** GPIO pin number for shutdown button
- **Used by:** GPIO listener service

#### `GPIO_SAFE_SHUTDOWN_DELAY`
- **Default:** `3`
- **Description:** Delay in seconds before initiating shutdown
- **Used by:** GPIO listener service

## Usage Examples

### Example 1: Custom Data Directory

If you want to store ethoscope data on a mounted drive:

```bash
# /etc/ethoscope/environment
ETHOSCOPE_DATA_DIR="/mnt/external_drive/ethoscope_data"
```

All subdirectories will automatically use this base:
- Results: `/mnt/external_drive/ethoscope_data/results`
- Videos: `/mnt/external_drive/ethoscope_data/videos`
- Sensors: `/mnt/external_drive/ethoscope_data/sensors`

### Example 2: Development Setup

For development with custom paths:

```bash
# /etc/ethoscope/environment
ETHOSCOPE_DATA_DIR="/home/developer/ethoscope_test_data"
ETHOSCOPE_CONFIG_DIR="/home/developer/ethoscope_config"
NODE_PORT=8080
NODE_DEBUG=true
```

Or use command-line arguments directly:
```bash
python server.py -e /home/developer/ethoscope_test_data -c /home/developer/ethoscope_config -p 8080 -D
```

### Example 3: Backup Configuration

Configure automatic backups to a remote server:

```bash
# /etc/ethoscope/environment
BACKUP_REMOTE_HOST="backup@storage.example.com"
BACKUP_REMOTE_PATH="/backup/ethoscope_lab_node01"
```

Then enable the backup service:
```bash
sudo systemctl enable --now ethoscope_backup_unified.service
```

### Example 4: Docker Deployment

For containerized deployments:

```bash
# /etc/ethoscope/environment
ETHOSCOPE_DOCKERIZED=true
SYSTEMCTL_BIN=/usr/bin/systemctl.py
NODE_PORT=80
```

## Precedence and Override Behavior

Environment variables follow this precedence (highest to lowest):

1. **Command-line arguments** - Explicitly passed flags (e.g., `--port 8080`)
2. **Environment variables** - Values from `/etc/ethoscope/environment`
3. **Default values** - Hardcoded defaults in the scripts

This allows flexible configuration where:
- Production systems use `/etc/ethoscope/environment` for site-wide settings
- Developers can override with command-line arguments for testing
- Scripts work out-of-the-box with sensible defaults

## Scripts Using Environment Variables

### Node Server (`server.py`)
Supports: `NODE_PORT`, `NODE_DEBUG`, `ETHOSCOPE_DATA_DIR`, `ETHOSCOPE_CONFIG_DIR`

```bash
# Uses environment variables as defaults
python server.py

# Override specific values
python server.py --port 8081 --debug
```

### Backup Sync (`accessories/cronie_scripts/sync`)
Supports: `BACKUP_REMOTE_HOST`, `BACKUP_REMOTE_PATH`, `ETHOSCOPE_VIDEOS_DIR`, `ETHOSCOPE_RESULTS_DIR`

```bash
# Uses environment variables
/opt/ethoscope/accessories/cronie_scripts/sync

# Override remote host
/opt/ethoscope/accessories/cronie_scripts/sync -h user@other-server.com
```

### Database Checker (`accessories/cronie_scripts/check_databases.sh`)
Supports: `ETHOSCOPE_RESULTS_DIR`

```bash
# Uses environment variables
/opt/ethoscope/accessories/cronie_scripts/check_databases.sh

# Override data directory
/opt/ethoscope/accessories/cronie_scripts/check_databases.sh --path /custom/path
```

### Video Converter (`accessories/h264_to_mp4.py`)
Supports: `ETHOSCOPE_VIDEOS_DIR`

```bash
# Uses environment variables
python /opt/ethoscope/accessories/h264_to_mp4.py

# Override video directory
python /opt/ethoscope/accessories/h264_to_mp4.py -p /custom/videos
```

## Troubleshooting

### Environment variables not taking effect

1. **Verify the file exists:**
   ```bash
   ls -l /etc/ethoscope/environment
   ```

2. **Check file syntax:**
   ```bash
   source /etc/ethoscope/environment && env | grep ETHOSCOPE
   ```

3. **Restart the service:**
   ```bash
   sudo systemctl restart ethoscope_node
   ```

4. **Check service logs:**
   ```bash
   sudo journalctl -u ethoscope_node -f
   ```

### Permission issues

The environment file should be readable by the service user:

```bash
sudo chmod 644 /etc/ethoscope/environment
sudo chown root:root /etc/ethoscope/environment
```

### Debugging

Enable debug mode to see which values are being used:

```bash
# In /etc/ethoscope/environment
NODE_DEBUG=true
```

Then check the service logs to see the loaded configuration values.

## Related Files

- **Template:** `/opt/ethoscope/accessories/environment.template`
- **Active Configuration:** `/etc/ethoscope/environment`
- **Service File:** `/opt/ethoscope/services/ethoscope_node.service`
- **Node Server:** `/opt/ethoscope/src/node/scripts/server.py`
- **Cronie Scripts:** `/opt/ethoscope/accessories/cronie_scripts/`

## Best Practices

1. **Always use the template** as a starting point - it contains all available variables with documentation
2. **Only set variables you need to change** - let others use defaults
3. **Use absolute paths** for all directory settings
4. **Quote values with spaces** using double quotes
5. **Test changes** by restarting services and checking logs
6. **Document custom values** with inline comments in the environment file
7. **Keep backups** of your environment file when making changes

## See Also

- [Ethoscope Documentation](https://lab.gilest.ro/ethoscope-manual)
- [Node Server README](../src/node/README.md)
- [Upgrade Scripts README](./upgrade_scripts/README.md)
