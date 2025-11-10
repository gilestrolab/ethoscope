# Ethoscope Node Docker Setup

This directory contains Docker configuration for running the Ethoscope node system in containers.

## Quick Start

1. Copy the environment template:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` to configure your paths (optional - defaults should work for most setups)

3. Start the services:
   ```bash
   docker compose up -d
   ```

## Services

The docker-compose configuration provides these services:

- **ethoscope-node** (port 80): Main web interface and API
- **ethoscope-node-backup** (port 8090): MySQL backup service
- **ethoscope-node-rsync-backup** (port 8093): File backup service (SQLite, videos)
- **ethoscope-node-update** (port 8888): Software update server
- **ethoscope-git-server** (port 9418): Git daemon for updates
- **ethoscope-vsftpd** (port 21): FTP server for data access

## Configuration

### Environment Variables

- `ETHOSCOPE_BRANCH`: Git branch to use (default: dev)
- `ETHOSCOPE_DATA`: Host path for data storage (default: /ethoscope_data)
- `ETHOSCOPE_CONFIG`: Host path for configuration (default: /etc/ethoscope)

### Volume Mounts

The containers bind-mount host directories for persistent storage:
- Data: `/ethoscope_data` → container `/ethoscope_data`
- Config: `/etc/ethoscope` → container `/etc/ethoscope`

Ensure these directories exist and have appropriate permissions before starting.

## Platform Notes

**Linux**: Recommended platform with full mDNS/Avahi support for automatic device discovery.

**Windows**: Network host mode not supported. Manual device IP configuration required as automatic discovery won't work.

## Development

For development, uncomment the source mount in docker-compose.yml:
```yaml
volumes:
  - ../../:/opt/ethoscope:ro
```

This mounts the host ethoscope repository into the container for live code updates.
