# Unified Rsync Backup Tool

## Overview

The `rsync_backup_tool.py` provides a unified approach to backing up both ethoscope results (databases) and videos using rsync. This eliminates the need for separate backup tools and API-based file discovery.

## Key Features

- **Unified Backup**: Single tool for both results and videos
- **Direct Rsync**: No API dependencies, direct file synchronization  
- **Flexible Configuration**: Backup results-only, videos-only, or both
- **Progress Tracking**: Real-time progress monitoring and status reporting
- **SSH Authentication**: Secure backup using SSH keys
- **Incremental Sync**: Rsync's built-in differential synchronization

## Directory Structure

The tool syncs the following directories from ethoscope to node:

```
Ethoscope → Node
/ethoscope_data/results/ → {results_dir}/
/ethoscope_data/videos/  → {videos_dir}/
```

Both maintain the same nested structure:
```
/{results|videos}/{etho_id}/{ETHOSCOPE_XXX}/{timestamp}/
```

## Usage

### Basic Usage

```bash
# Backup both results and videos (default)
python3 rsync_backup_tool.py

# Backup with custom directories
python3 rsync_backup_tool.py -r /data/results -v /data/videos

# Backup specific ethoscope
python3 rsync_backup_tool.py -e 004
```

### Backup Type Selection

```bash
# Backup only results/databases
python3 rsync_backup_tool.py --results-only

# Backup only videos  
python3 rsync_backup_tool.py --videos-only

# Unified backup (default - both results and videos)
python3 rsync_backup_tool.py --unified
```

### Advanced Options

```bash
# Debug mode with verbose logging
python3 rsync_backup_tool.py -D

# Specify node server for device discovery
python3 rsync_backup_tool.py -i node.example.com

# Force backup of multiple ethoscopes
python3 rsync_backup_tool.py -e "004,007,010"
```

## Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `-r, --results-dir` | Destination for results/database files | From config |
| `-v, --videos-dir` | Destination for video files | Auto-derived |
| `-i, --server` | Node server for device discovery | localhost |
| `-e, --ethoscope` | Force backup specific ethoscope(s) | All active |
| `--unified` | Backup both results and videos | True |
| `--results-only` | Backup only database files | False |
| `--videos-only` | Backup only video files | False |
| `-D, --debug` | Enable debug logging | False |
| `-s, --safe` | Enable safe mode | False |

## HTTP API

The tool provides an HTTP server on port 8093 for status monitoring:

```bash
# Get backup status
curl http://localhost:8093/

# Get detailed status for all devices
curl http://localhost:8093/status
```

## Comparison with Previous Tools

| Feature | rsync_backup_tool.py | video_backup_tool.py | backup_tool.py |
|---------|---------------------|---------------------|----------------|
| **Data Types** | Results + Videos | Videos only | Databases only |
| **Transfer Method** | Direct rsync | API + rsync | MySQL connection |
| **Dependencies** | SSH only | API + SSH | MySQL + API |
| **File Discovery** | None (direct sync) | API enumeration | Database query |
| **Progress Tracking** | Real-time rsync | Real-time rsync | Database rows |
| **Configuration** | Flexible options | Video-specific | Database-specific |

## Configuration

### SSH Key Setup

The tool requires SSH keys for authentication. These are typically managed by the ethoscope system and should be automatically available in `/etc/ethoscope/keys/`.

### Directory Configuration

Default directories come from `EthoscopeConfiguration`:
- Results: `CFG.content['folders']['results']['path']`
- Videos: `CFG.content['folders']['video']['path']`

### Service Mode

To run as a continuous service:

```bash
# Start HTTP server (runs continuously)
python3 rsync_backup_tool.py

# The server will:
# 1. Discover active ethoscopes every 5 minutes
# 2. Initiate backup jobs for devices with new data
# 3. Provide status via HTTP API on port 8093
```

## Rsync Command Structure

The tool generates rsync commands like:

```bash
# Results backup
rsync -avz --progress --partial --timeout=300 \
  -e 'ssh -i /etc/ethoscope/keys/id_rsa -o StrictHostKeyChecking=no' \
  ethoscope@192.168.1.100:/ethoscope_data/results/ \
  /ethoscope_data/results/

# Videos backup  
rsync -avz --progress --partial --timeout=300 \
  -e 'ssh -i /etc/ethoscope/keys/id_rsa -o StrictHostKeyChecking=no' \
  ethoscope@192.168.1.100:/ethoscope_data/videos/ \
  /ethoscope_data/videos/
```

## Migration from Previous Tools

### From video_backup_tool.py

```bash
# Old command
python3 video_backup_tool.py -d /data/videos

# New equivalent
python3 rsync_backup_tool.py --videos-only -v /data/videos
```

### From backup_tool.py

```bash
# Old command
python3 backup_tool.py -d /data/results

# New equivalent  
python3 rsync_backup_tool.py --results-only -r /data/results
```

### Combined Backup

```bash
# Previously required two separate tools
python3 backup_tool.py -d /data/results &
python3 video_backup_tool.py -d /data/videos &

# Now unified in single tool
python3 rsync_backup_tool.py -r /data/results -v /data/videos
```

## Implementation Details

### UnifiedRsyncBackupClass

The core backup logic is implemented in `UnifiedRsyncBackupClass` which:

1. Inherits from `BaseBackupClass` for consistent interface
2. Supports selective backup of results and/or videos
3. Uses rsync for robust, incremental file transfer
4. Provides real-time progress monitoring
5. Handles SSH authentication automatically
6. Reports detailed status information

### Integration with GenericBackupWrapper

The tool extends `GenericBackupWrapper` to:

1. Use `UnifiedRsyncBackupClass` instead of separate backup classes
2. Maintain existing threading and status tracking
3. Provide HTTP API compatibility
4. Support device discovery and management

## Troubleshooting

### SSH Authentication Issues

```bash
# Check SSH key availability
ls -la /etc/ethoscope/keys/

# Test SSH connection manually
ssh -i /etc/ethoscope/keys/id_rsa ethoscope@{device_ip} "ls /ethoscope_data"
```

### Directory Permission Issues

```bash
# Ensure destination directories are writable
sudo chown -R ethoscope:ethoscope /ethoscope_data/results
sudo chown -R ethoscope:ethoscope /ethoscope_data/videos
```

### Debug Mode

Use `-D` flag for detailed logging:

```bash
python3 rsync_backup_tool.py -D -e 004
```

## Future Enhancements

1. **results → tracking rename**: Directory rename can be implemented as separate enhancement
2. **Bandwidth limiting**: Add rsync bandwidth limiting options
3. **Compression options**: Configurable compression levels
4. **Retry logic**: Enhanced retry mechanisms for failed transfers
5. **Monitoring integration**: Integration with monitoring systems
