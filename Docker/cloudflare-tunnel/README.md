# Cloudflare Tunnel for Ethoscope

This Docker setup creates a secure tunnel to Cloudflare, allowing external access to your ethoscope node through the internet without opening firewall ports or configuring port forwarding.

## Overview

The Cloudflare Tunnel creates a secure outbound connection from your ethoscope node to Cloudflare's network. This allows users to access your node via a subdomain like `node-admin.ethoscope.net` (when using auto mode) or `your-custom-id.ethoscope.net` without exposing your local network.

## Prerequisites

1. **Cloudflare Account**: Ensure `ethoscope.net` is managed by Cloudflare
2. **Cloudflare Zero Trust**: Access to Cloudflare Zero Trust dashboard
3. **Docker**: Docker and docker-compose installed on your system
4. **Ethoscope Node**: Main ethoscope node must be running

## Setup Instructions

### Step 1: Create Cloudflare Tunnel

1. Go to [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/)
2. Navigate to **Access** > **Tunnels**
3. Click **Create a tunnel**
4. Choose **Cloudflared** as the connector type
5. Enter a name for your tunnel (e.g., "ethoscope-node-tunnel")
6. Copy the tunnel token provided

### Step 2: Configure Environment

1. Copy the environment template:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` file and add your tunnel token:
   ```bash
   TUNNEL_TOKEN=your_actual_cloudflare_tunnel_token_here
   NODE_ID=auto  # Creates node-<admin_username>.ethoscope.net
   # OR
   NODE_ID=custom-name  # Creates custom-name.ethoscope.net
   ```

### Step 3: Configure Public Hostname in Cloudflare

1. In the Cloudflare tunnel dashboard, go to the **Public Hostnames** tab
2. Click **Add a public hostname**
3. Configure:
   - **Subdomain**: Enter your node ID:
     - If using `NODE_ID=auto`: Enter `node-<admin_username>` (e.g., "node-beckwith")
     - If using custom ID: Enter your custom name (e.g., "lab-node-01")
   - **Domain**: Select "ethoscope.net"
   - **Type**: HTTP
   - **URL**: `http://ethoscope-node:80` (internal Docker network)

### Step 4: Start the Tunnel

#### Option A: Using systemd service (Recommended for production)

**Prerequisites:** Install cloudflared binary:
```bash
# Install cloudflared (if not already installed)
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
```

**Install and configure:**
```bash
# Install the tunnel service (if not already installed)
sudo /opt/ethoscope/accessories/upgrade_scripts/install_services.sh --node

# Configure via web interface (recommended) OR manually edit configuration:
# The tunnel token is stored in /etc/ethoscope/ethoscope.conf under the 'tunnel' section
# The node server automatically creates the environment file for the systemd service

# Start the tunnel service
sudo systemctl start ethoscope_tunnel

# Enable auto-start on boot
sudo systemctl enable ethoscope_tunnel
```

#### Option B: Using Docker Compose (for testing)

```bash
# Start the tunnel (uses host networking to access node on port 80)
cd /path/to/ethoscope/Docker/cloudflare-tunnel
docker-compose up -d
```

### Step 5: Verify Connection

1. Check tunnel status:
   ```bash
   docker-compose logs cloudflare-tunnel
   ```

2. Test external access:
   ```bash
   # If using auto mode (NODE_ID=auto)
   curl https://node-<admin_username>.ethoscope.net/api/devices
   
   # If using custom ID
   curl https://your-custom-id.ethoscope.net/api/devices
   ```

## Node ID Configuration

The tunnel supports two modes for generating the subdomain:

- **Auto mode** (`NODE_ID=auto`): Creates `node-<admin_username>.ethoscope.net`
  - Uses the admin username from ethoscope configuration
  - Example: If admin user is "beckwith", creates `node-beckwith.ethoscope.net`

- **Custom mode** (`NODE_ID=custom-name`): Creates `custom-name.ethoscope.net`
  - Uses the exact string provided
  - Example: `NODE_ID=lab-node-01` creates `lab-node-01.ethoscope.net`

## Integration with Ethoscope Node

### Architecture
- **Configuration**: Tunnel token stored in `/etc/ethoscope/ethoscope.conf` (tunnel section)
- **Environment File**: Node server automatically creates `/etc/ethoscope/tunnel.env` for systemd
- **Service**: Native `cloudflared` binary managed by systemd service
- **Web Interface**: Full control via ethoscope web interface

### Usage
The tunnel can be controlled through the ethoscope web interface:

1. Go to your node's web interface
2. Navigate to **More** > **System** 
3. Find the **Internet Tunnel (Remote Access)** section
4. Use the toggle to enable/disable the tunnel
5. Click "Configure" to set up your Cloudflare tunnel token

## Management Commands

```bash
# Start tunnel
docker-compose up -d

# Stop tunnel
docker-compose down

# View logs
docker-compose logs -f cloudflare-tunnel

# Check status
docker-compose ps

# Restart tunnel
docker-compose restart cloudflare-tunnel
```

## Troubleshooting

### Common Issues

1. **Tunnel token invalid**: Verify token is correctly copied from Cloudflare dashboard
2. **Network not found**: Ensure main ethoscope node Docker network is running
3. **Connection refused**: Check that ethoscope-node container is accessible on port 80

### Debug Commands

```bash
# Check tunnel container logs
docker-compose logs cloudflare-tunnel

# Test internal network connectivity
docker-compose exec cloudflare-tunnel wget -O- http://ethoscope-node:80/

# Verify tunnel registration
# Check Cloudflare dashboard for active tunnel connection
```

### Log Locations

- Container logs: `docker-compose logs cloudflare-tunnel`
- Cloudflare dashboard: Shows tunnel connection status and traffic

## Security Notes

- The tunnel creates outbound-only connections (no inbound ports opened)
- All traffic is encrypted through Cloudflare's network
- Access can be controlled via Cloudflare Access policies if needed
- No changes required to local firewall or router configuration

## Support

For issues related to:
- **Tunnel setup**: Check Cloudflare Zero Trust documentation
- **Ethoscope integration**: Check ethoscope project documentation
- **Container issues**: Check Docker logs and network configuration