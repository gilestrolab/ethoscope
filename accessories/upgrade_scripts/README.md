# Ethoscope Upgrade Scripts

This directory contains scripts to help users upgrade their ethoscope installations when there are breaking changes to the repository structure.

## Current Scripts

### migrate_to_unified_structure.sh

**Purpose:** Migrate from the old separate directory structure to the new unified structure introduced in the dev branch reorganization.

**Migration Details:**
- **From:** `/opt/ethoscope-device` and `/opt/ethoscope-node` (separate directories)
- **To:** `/opt/ethoscope` (unified directory)

**Prerequisites:**
1. **IMPORTANT:** Pull the latest dev branch first: `git pull origin dev`
2. Git handles the file reorganization automatically
3. This script handles the system-level changes

**What it does:**
1. Detects current installation type (node, device, or both)
2. Stops running ethoscope services
3. Moves old directories to `/opt/ethoscope`
4. Removes old systemd service files
5. Creates symbolic links to new service files in `/opt/ethoscope/scripts/`
6. Installs Python packages in development mode
7. Enables and restarts services

**Usage:**

```bash
# Check current installation state
sudo ./migrate_to_unified_structure.sh --check

# Interactive migration (recommended)
sudo ./migrate_to_unified_structure.sh

# Automatic migration (for scripted deployments)
sudo ./migrate_to_unified_structure.sh --auto

# Rollback if something went wrong
sudo ./migrate_to_unified_structure.sh --rollback

# Show help
sudo ./migrate_to_unified_structure.sh --help
```

**Safety Features:**
- Graceful service management (stop/start)
- Error handling and warnings for edge cases
- Detects conflicts (both old and new directories existing)
- Clear logging of all operations

**When to use:**
Run this script when upgrading to the new dev branch after the repository reorganization. The script is idempotent - it's safe to run multiple times.

**Prerequisites:**
- Root access (script must be run with sudo)
- Existing ethoscope installation using old directory structure
- Systemd-based system (most modern Linux distributions)

## Post-Migration

After successful migration:

1. **Verify Services:** Check that all ethoscope services are running correctly:
   ```bash
   sudo systemctl status ethoscope_device  # For device installations
   sudo systemctl status ethoscope_node    # For node installations
   sudo systemctl status ethoscope_update
   ```

2. **Test Functionality:** Verify that your ethoscope devices and node are functioning correctly after the migration.

3. **The new structure:** Your installation is now at `/opt/ethoscope` with:
   - Device code: `/opt/ethoscope/src/ethoscope/`
   - Node code: `/opt/ethoscope/src/node/`
   - Updater: `/opt/ethoscope/src/updater/`
   - Service files: `/opt/ethoscope/scripts/`

## Troubleshooting

**Migration fails:**
- Check the error output and logs
- If both old and new directories exist, resolve manually
- Report issues to the ethoscope project

**Services not starting:**
- Check service status: `sudo systemctl status <service_name>`
- Check service logs: `sudo journalctl -u <service_name>`
- Verify file paths in service files

**Permission issues:**
- Ensure script is run with sudo
- Check file ownership: `ls -la /opt/ethoscope`
- Fix if needed: `sudo chown -R root:root /opt/ethoscope`

## For Developers

When adding new upgrade scripts:

1. Name scripts descriptively indicating what they migrate
2. Include comprehensive error handling and rollback capability
3. Add extensive logging and user feedback
4. Test on various installation scenarios
5. Update this README with script documentation

## Version Compatibility

| Script | Compatible Versions | Required For |
|--------|-------------------|--------------|
| migrate_to_unified_structure.sh | All versions → dev branch 2025 | Repository reorganization |

---

For support or issues with upgrade scripts, please open an issue on the [ethoscope GitHub repository](https://github.com/gilestrolab/ethoscope/issues).