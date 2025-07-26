# Ethoscope Virtuascope Docker Setup

This directory contains Docker configuration for running a virtual ethoscope device (virtuascope) that simulates real ethoscope hardware for testing and development.

## Overview

The virtuascope provides:
- Virtual ethoscope device running on port 9000
- MariaDB database for data storage
- Simulated camera input (uses /dev/video0 if available)
- Full ethoscope API compatibility for testing

## Quick Start

1. **Setup v4l2loopback on host** (required for virtual video):
   ```bash
   # If module needs rebuilding for current kernel:
   sudo dkms install v4l2loopback/0.13.2 -k $(uname -r)
   
   # Load the module to create virtual video device:
   sudo modprobe v4l2loopback video_nr=10 card_label="Virtual Ethoscope Camera"
   ```

2. Ensure the ethoscope network exists (start node services first):
   ```bash
   cd ../node
   docker compose up -d
   ```

3. Start the virtuascope:
   ```bash
   docker compose up -d
   ```

4. Access the virtual device at: http://localhost:9000

## Services

### ethoscope-virtual
- **Image**: Built from `virtuascope.dockerfile` (Debian-based)
- **Port**: 9000 (ethoscope device API)
- **Function**: Simulates ethoscope device with tracking capabilities
- **Camera**: Uses virtual video device from video-streamer

### video-streamer
- **Image**: Built from `video-streamer.dockerfile` (Ubuntu + ffmpeg)
- **Function**: Streams remote video (YouTube, etc.) to virtual camera device
- **Device**: Uses `/dev/video10` created by host v4l2loopback module
- **Host Dependency**: Requires v4l2loopback module loaded on host system

### ethoscope-mariadb
- **Image**: mariadb:latest
- **Port**: 3306 (internal only)
- **Function**: Database storage for tracking data
- **Credentials**: Root password "ethoscope", configured via init script

## Configuration

### Network
The virtuascope shares the `ethoscope_network` with the node services, enabling:
- Automatic device discovery by the node
- Network communication between virtual and real devices
- Consistent networking behavior

### Volumes
- `ethoscope_data`: Persistent data storage
- `mariadb_socket`: Unix socket communication
- `mariadb_data`: Database persistence

### Video Configuration
The video-streamer service supports several environment variables:

- **VIDEO_URL**: Remote video source (YouTube, direct URLs, RTSP streams)
- **VIRTUAL_DEVICE**: Virtual camera device path (default: /dev/video10)
- **LOOP**: Loop video playback (true/false, default: true)

Example configuration:
```yaml
environment:
  - VIDEO_URL=https://www.youtube.com/watch?v=uGsWPLsU6ws
  - VIRTUAL_DEVICE=/dev/video10
  - LOOP=true  # Set to false for single playback
```

### Development Mode
Uncomment the source mount in docker-compose.yml for live code updates:
```yaml
volumes:
  - ../../:/opt/ethoscope:ro
```

## Database Setup

The MariaDB container automatically configures:
- Root user with password "ethoscope"
- Ethoscope user with full privileges
- Node user with read-only access

Database initialization is handled by `init_db_credentials.sql`.

## Virtuascope Mode

The container removes `/etc/machine-name` to activate virtuascope mode, which:
- Enables virtual camera simulation
- Provides mock hardware interfaces
- Allows testing without physical ethoscope hardware

## Video Sources

The video-streamer supports multiple input types:

### YouTube Videos
```yaml
- VIDEO_URL=https://www.youtube.com/watch?v=uGsWPLsU6ws
```

### Direct Video Files
```yaml
- VIDEO_URL=https://example.com/path/to/video.mp4
```

### RTSP Streams
```yaml
- VIDEO_URL=rtsp://camera.example.com:554/stream
```

### Local Files (mount as volume)
```yaml
volumes:
  - ./test-videos:/videos
environment:
  - VIDEO_URL=/videos/sample.mp4
```

## Troubleshooting

### Video Streaming Issues
- Check that the video URL is accessible
- Verify `/dev/video10` device is created by the video-streamer
- Ensure privileged mode is enabled for kernel module loading

### Camera Device Issues
To use physical camera instead of virtual:
```yaml
devices:
  - /dev/video0:/dev/video0   # Use physical camera
  #- /dev/video10:/dev/video0  # Use virtual video device
```

### Network Issues
Ensure the node services are running first to create the shared network:
```bash
cd ../node && docker compose up -d
```

### Build Issues
Large packages (scipy) may timeout during build. The dockerfile includes extended timeout settings (300s) to handle this.

### Kernel Module Issues

**On Arch/Manjaro systems:**
```bash
# Install v4l2loopback if not already installed
yay -S v4l2loopback-dkms

# Rebuild for current kernel if needed
sudo dkms install v4l2loopback/0.13.2 -k $(uname -r)

# Load the module
sudo modprobe v4l2loopback video_nr=10 card_label="Virtual Ethoscope Camera"

# Verify device was created
ls -la /dev/video*
```

**On Debian/Ubuntu systems:**
```bash
# Install v4l2loopback
sudo apt install v4l2loopback-dkms v4l2loopback-utils

# Load the module
sudo modprobe v4l2loopback video_nr=10 card_label="Virtual Ethoscope Camera"
```

**Make module load persistent:**
```bash
# Add to modules load configuration
echo 'v4l2loopback video_nr=10 card_label="Virtual Ethoscope Camera"' | sudo tee /etc/modules-load.d/v4l2loopback.conf
```

## Integration

The virtuascope integrates seamlessly with:
- Node web interface (device appears in device list)
- Backup systems (data is backed up like real devices)
- Update system (receives software updates)
- Monitoring tools (appears as regular ethoscope)