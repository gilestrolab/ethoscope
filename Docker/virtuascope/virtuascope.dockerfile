# These build instructions will create a docker container running the virtuascope

# Use Debian base image (same as Raspberry Pi OS)
FROM debian:bookworm

# Update system and install basic packages
RUN apt-get update && apt-get upgrade -y

# Install basic system packages
RUN apt-get install -y \
    sqlite3 \
    build-essential \
    python3-dev \
    libcap-dev \
    pkg-config \
    git \
    nano \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1

# Install Python system packages
RUN apt-get install -y \
    python3-pip \
    python3-venv \
    python3-setuptools \
    python3-usb \
    python3-protobuf

# Create system-wide pip config to allow system package installation
RUN mkdir -p /etc && cat > /etc/pip.conf << 'EOF'
[global]
break-system-packages = true
timeout = 300
EOF

# Create ethoscope user
RUN useradd -m ethoscope \
    && echo "ethoscope:ethoscope" | chpasswd \
    && usermod -a -G root ethoscope

# Clone and install ethoscope software
RUN git clone https://github.com/gilestrolab/ethoscope.git /opt/ethoscope

# Configure git repository (dev branch)
RUN cd /opt/ethoscope/ \
    && git checkout ${ETHOSCOPE_BRANCH:-dev} \
    && git config --global --add safe.directory /opt/ethoscope

# Install ethoscope Python package
RUN cd /opt/ethoscope/src/ethoscope \
    && pip3 install -e . --break-system-packages --timeout 300

# Remove machine-name file to activate VIRTUASCOPE mode
RUN rm -f /etc/machine-name

# Clean up packages
RUN apt-get clean && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /opt/ethoscope/src/ethoscope/scripts
USER root

# Command to run when the container starts
CMD ["python3", "/opt/ethoscope/src/ethoscope/scripts/device_server.py", "-D"]
