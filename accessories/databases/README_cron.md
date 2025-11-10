# Database Maintenance Cron Scripts

This directory contains scripts for automated database maintenance tasks.

## retire_inactive_devices.py

Retires Ethoscope devices that haven't been seen for a specified number of days (default: 90 days).

### Usage

```bash
# Run with default settings (90 day threshold)
python3 retire_inactive_devices.py

# Custom threshold (30 days)
python3 retire_inactive_devices.py --threshold-days 30

# Dry run to see what would be retired
python3 retire_inactive_devices.py --dry-run

# Custom config directory
python3 retire_inactive_devices.py --config-dir /custom/path

# Debug mode
python3 retire_inactive_devices.py --debug
```

### Cron Setup

To run this script automatically via cron, add an entry to your crontab:

```bash
# Edit crontab
sudo crontab -e

# Add one of these entries:

# Run daily at 3 AM
0 3 * * * /usr/bin/python3 /path/to/ethoscope/accessories/databases/retire_inactive_devices.py

# Run weekly on Sunday at 2 AM
0 2 * * 0 /usr/bin/python3 /path/to/ethoscope/accessories/databases/retire_inactive_devices.py

# Run monthly on the 1st at 1 AM
0 1 1 * * /usr/bin/python3 /path/to/ethoscope/accessories/databases/retire_inactive_devices.py
```

### What it does

1. Connects to the Ethoscope database
2. Identifies devices that haven't been seen for more than the threshold days
3. Sets their `active` status to 0 (retired)
4. Also runs cleanup operations:
   - Cleans up stale "busy" devices
   - Purges unnamed/invalid device entries

### Logging

The script logs all operations. In production, you may want to redirect output:

```bash
# Redirect to log file
0 3 * * * /usr/bin/python3 /path/to/retire_inactive_devices.py >> /var/log/ethoscope_maintenance.log 2>&1
```
