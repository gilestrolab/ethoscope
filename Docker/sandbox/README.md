# Ethoscope Sandbox Container

This Docker container provides a clean Arch Linux environment for testing the Ethoscope package installation and dependencies without affecting your host system.

## Purpose

The sandbox container is useful for:
- Testing package installations from the ethoscope repository
- Verifying dependency resolution
- Debugging installation issues in a clean environment
- Testing package builds and installation procedures
- Experimenting with pacman configurations

## Dependencies

All Python dependencies are installed via pacman (Arch Linux package manager) to ensure system-level compatibility:
- Python 3.x
- bottle, cherrypy (web frameworks)
- mysql-connector, zeroconf, netifaces (networking)
- numpy, opencv, scipy (scientific computing)
- pyserial, psutil (hardware/system)
- gitpython, requests, dateutil (utilities)
- mattermostdriver (from AUR)

The ethoscope repository is also configured in pacman for potential package testing.

## Usage

### Build and Start the Container

```bash
cd Docker/sandbox
docker compose up -d
```

This will:
- Build the sandbox image from `sandbox.dockerfile`
- Start the container named `ethoscope_sandbox`
- Map container port 80 to host port 9000

### Access the Container

```bash
# Interactive shell
docker compose exec sandbox /bin/bash

# Or using docker directly
docker exec -it ethoscope_sandbox /bin/bash
```

### Test Package Installation

Once inside the container:

```bash
# Install ethoscope packages from the repository
pacman -Sy ethoscope-device
pacman -Sy ethoscope-node

# Or clone and install from source
cd /root
git clone https://github.com/gilestrolab/ethoscope.git
cd ethoscope/src/ethoscope
make install

# Test node package
cd ../node
make install
```

### Test Development Installation

```bash
# Clone the repository
cd /root
git clone https://github.com/gilestrolab/ethoscope.git
cd ethoscope

# Test device package installation
cd src/ethoscope
make install-dev
make test

# Test node package installation
cd ../node
make install-dev
make test
```

### Stop the Container

```bash
docker compose down
```

### Rebuild the Container

If you modify the Dockerfile:

```bash
docker compose build
docker compose up -d
```

Or rebuild from scratch:

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

## Port Mapping

- **Container Port 80** → **Host Port 9000**
  - Any service running on port 80 inside the container is accessible at `http://localhost:9000` on the host machine
  - Useful for testing web servers after package installation

## Editor

The container includes both `micro` and `nano` text editors for editing files inside the container.

## Transferring Files to the Container

To copy files from your host to the container:

```bash
# Copy a file into the container
docker cp /path/to/local/file ethoscope_sandbox:/root/

# Copy a directory into the container
docker cp /path/to/local/directory ethoscope_sandbox:/root/

# Copy from container to host
docker cp ethoscope_sandbox:/root/file /path/to/local/
```

## Notes

- The container runs as root by default (after building AUR packages as the `sandbox` user)
- Changes made inside the container are ephemeral unless you commit them to a new image
- The sandbox user is configured with passwordless sudo for package building
- The ethoscope pacman repository is pre-configured at `https://repo.ethoscope.lab.gilest.ro/`
- Use `docker cp` to transfer files between host and container as needed
- The container provides a completely isolated environment for testing installations
