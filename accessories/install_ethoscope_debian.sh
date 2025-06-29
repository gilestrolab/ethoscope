#!/bin/bash

#===============================================================================
# Ethoscope Device Installation Script for Debian/Raspbian
#===============================================================================
#
# Purpose: Complete installation and configuration of ethoscope software on
#          Raspberry Pi devices running Debian/Raspbian OS
#
# Target Platform: Raspberry Pi (tested on Pi 4) with Debian/Raspbian
# Prerequisites: Fresh Debian/Raspbian installation with network connectivity
#
# What this script does:
# 1. Installs required system packages and Python dependencies
# 2. Creates ethoscope user account
# 3. Clones ethoscope software from GitHub to /opt/ethoscope
# 4. Configures systemd services for device operation
# 5. Sets up MariaDB database with ethoscope user
# 6. Configures network settings (ethernet + WiFi)
# 7. Sets up NTP time synchronization with node
# 8. Configures Raspberry Pi specific hardware (camera, I2C, etc.)
#
# Usage:
#   sudo ./install_ethoscope_debian.sh           # Full installation
#   sudo ./install_ethoscope_debian.sh --apt-install  # Package installation only
#
# Author: Giorgio Gilestro <giorgio@gilest.ro>
# License: GPL3
# Repository: https://github.com/gilestrolab/ethoscope
#===============================================================================

set -e  # Exit on any error

#===============================================================================
# UTILITY FUNCTIONS
#===============================================================================

check_root() {
    if [[ $EUID -ne 0 ]]; then
       echo "This script must be run as root. Use sudo to run it." 1>&2
       exit 1
    fi
}

detect_pi_model() {
    # Get the hardware model from /proc/cpuinfo
    local model=$(grep 'Model' /proc/cpuinfo | awk -F': ' '{print $2}')
    local revision=$(grep 'Revision' /proc/cpuinfo | awk '{print $3}')
    
    # Determine Pi model for filename
    if [[ "$revision" == "a01041" || "$revision" == "a21041" || "$revision" == "a22042" ]]; then
        PI_MODEL="pi2"
    elif [[ "$revision" == "a02082" || "$revision" == "a22082" || "$revision" == "a32082" || "$revision" == "a020d3" ]]; then
        PI_MODEL="pi3"
    elif [[ "$revision" =~ ^[bc][0-9a-f]{5}$ ]]; then
        PI_MODEL="pi4"
    elif [[ "$revision" =~ ^d[0-9a-f]{5}$ ]]; then
        PI_MODEL="pi5"
    else
        PI_MODEL="pi"
    fi
    
    echo "Detected Raspberry Pi model: $PI_MODEL (revision: $revision)"
}

determine_config_paths() {
    # Initialize configuration paths
    MYCNF=""
    BOOTCFG=""
    
    if [ -f "/etc/os-release" ]; then
        . /etc/os-release
        
        if [[ "$ID" == "debian" ]]; then
            MYCNF="/etc/mysql/mariadb.conf.d/ethoscope.cnf"
            BOOTCFG="/boot/firmware/config.txt"
        elif [[ "$ID" == "arch" ]]; then
            MYCNF="/etc/my.cnf.d/ethoscope.cnf"
            BOOTCFG="/boot/config.txt"
        fi
    fi
}

#===============================================================================
# PACKAGE INSTALLATION
#===============================================================================

install_mysql_connector() {
    echo "Installing python3-mysql.connector..."
    
    # Try Raspberry Pi OS repositories first (safest for ARM architecture)
    if ! dpkg -l | grep -q python3-mysql.connector; then
        echo "Trying Raspberry Pi OS repositories..."
        if apt-cache show python3-mysql.connector >/dev/null 2>&1; then
            apt-get install -y python3-mysql.connector
        else
            echo "python3-mysql.connector not available in Raspberry Pi OS repos"
        fi
    fi
    
    # Verify installation works, use pip as fallback
    if ! python3 -c "import mysql.connector; print('mysql.connector is working')" 2>/dev/null; then
        echo "System package not available, installing via pip..."
        pip3 install mysql-connector-python --break-system-packages
        
        # Final verification
        if ! python3 -c "import mysql.connector; print('mysql.connector is working')" 2>/dev/null; then
            echo "ERROR: Could not install mysql.connector module"
            exit 1
        else
            echo "mysql.connector successfully installed via pip"
        fi
    else
        echo "mysql.connector is working"
    fi
}

install_apt_packages() {
    echo "Installing system packages and Python dependencies on $PI_MODEL..."
    apt-get update && apt-get upgrade -y

    apt-get install -y \
        python3-bottle python3-cheroot python3-cherrypy3 python3-opencv python3-pymysql \
        python3-git python3-matplotlib python3-mock python3-netifaces python3-serial \
        python3-usb python3-sklearn python3-setuptools python3-zeroconf python3-protobuf \
        python3-picamera2 mariadb-server mariadb-client ntp systemd-resolved \
        python3-pip python3-venv
    
    # Install mysql-connector with fallback logic
    install_mysql_connector
    
    echo "All necessary packages were installed. Now reboot."        
}

#===============================================================================
# USER MANAGEMENT
#===============================================================================

setup_ethoscope_user() {
    echo "Setting up ethoscope user account..."
    if id "ethoscope" &>/dev/null; then
        echo "User 'ethoscope' already exists, skipping user creation"
    else
        echo "Creating ethoscope user account..."
        useradd -m ethoscope
    fi
    echo -e "ethoscope\nethoscope" | passwd ethoscope
    usermod -a -G root ethoscope
}

#===============================================================================
# SOFTWARE INSTALLATION
#===============================================================================

install_ethoscope_software() {
    echo "Cloning ethoscope software repository..."
    if [[ -d "/opt/ethoscope" ]]; then
        echo "Removing existing /opt/ethoscope directory for clean installation..."
        rm -rf /opt/ethoscope
    fi
    git clone https://github.com/gilestrolab/ethoscope.git /opt/ethoscope

    echo "Configuring git repository (dev branch, node remote)..."
    cd /opt/ethoscope/
    git checkout dev
    git remote set-url origin git://node/ethoscope.git
    git config --global --add safe.directory /opt/ethoscope

    echo "Installing ethoscope Python package..."
    cd /opt/ethoscope/src/ethoscope
    pip3 install -e . --break-system-packages

    echo "Installing systemd service files..."
    rm -rf /usr/lib/systemd/system/{ethoscope_device,ethoscope_listener,ethoscope_GPIO_listener,ethoscope_update}.service >> /dev/null
    ln -s /opt/ethoscope/scripts/{ethoscope_device,ethoscope_listener,ethoscope_GPIO_listener,ethoscope_update}.service /usr/lib/systemd/system/

    echo "Creating ethoclient command line tool..."
    echo $'#!/bin/env bash\npython /opt/ethoscope/src/ethoscope/scripts/ethoclient.py $@' > /usr/bin/ethoclient
    chmod +x /usr/bin/ethoclient
}

#===============================================================================
# SYSTEM CONFIGURATION
#===============================================================================

configure_system_identity() {
    echo "Setting up default machine identity (ETHOSCOPE_000)..."
    echo "ETHOSCOPE_000" > /etc/machine-name
    echo "ETHOSCOPE_000" > /etc/hostname

    echo "Configuring login prompt with network information..."
    echo 'Ethoscope Linux \r  (\n) (\l)' > /etc/issue
    echo 'Ethernet IP: \4{eth0}' >> /etc/issue
    echo 'WIFI IP: \4{wlan0}' >> /etc/issue
    echo 'Time on Device: \d \t' >> /etc/issue

    echo "Limiting systemd journal log space to 250MB..."
    echo 'SystemMaxUse=250MB' >> /etc/systemd/journald.conf

    echo "Generating en_GB.UTF-8 locale..."
    echo "en_GB.UTF-8 UTF-8" >> /etc/locale.gen
    locale-gen

    # Create a timestamp for this SD card image installation
    echo $(date +%Y%m%d)_ethoscope_${PI_MODEL}.img > /etc/sdimagename
}

configure_time_sync() {
    echo "Configuring NTP time synchronization with node..."
    echo 'server node' > /etc/ntp.conf
    echo 'server 127.127.1.0' >> /etc/ntp.conf
    echo 'fudge 127.127.1.0 stratum 10' >> /etc/ntp.conf
    echo 'restrict default kod limited nomodify nopeer noquery notrap' >> /etc/ntp.conf
    echo 'restrict 127.0.0.1' >> /etc/ntp.conf
    echo 'restrict ::1' >> /etc/ntp.conf
    echo 'driftfile /var/lib/ntp/ntp.drift' >> /etc/ntp.conf
}

enable_system_services() {
    echo "Enabling ethoscope device services..."
    systemctl enable ethoscope_device.service ethoscope_listener.service ethoscope_update.service ethoscope_GPIO_listener.service
    systemctl enable ntpd.service mysqld.service sshd.service avahi-daemon.service
}

#===============================================================================
# NETWORK CONFIGURATION
#===============================================================================

configure_network() {
    echo "Configuring network interfaces (ethernet + WiFi)..."
    
    # Disable conflicting network managers first
    systemctl disable NetworkManager ModemManager dhcpcd || true
    systemctl stop NetworkManager ModemManager dhcpcd || true
    
    # Create wired network config for eth0
    cat > /etc/systemd/network/20-wired.network << 'EOF'
[Match]
Name=eth0

[Network]
DHCP=yes
LinkLocalAddressing=yes

[DHCPv4]
RouteMetric=10
UseDNS=yes
EOF

    # WiFi configuration  
    cat > /etc/systemd/network/25-wireless.network << 'EOF'
[Match]
Name=wlan0

[Network]
DHCP=yes
LinkLocalAddressing=yes

[DHCPv4]
RouteMetric=20
UseDNS=yes
EOF

    # Enable systemd-networkd and resolved
    systemctl enable systemd-networkd systemd-resolved
    systemctl disable systemd-networkd-wait-online  # Prevent boot hangs
    
    # Ensure interfaces are up
    echo "Bringing up network interfaces..."
    ip link set eth0 up || true
    ip link set wlan0 up || true
    
    # Create resolved configuration
    mkdir -p /etc/systemd/resolved.conf.d
    cat > /etc/systemd/resolved.conf.d/ethoscope.conf << 'EOF'
[Resolve]
DNS=8.8.8.8 1.1.1.1
FallbackDNS=8.8.4.4 1.0.0.1
EOF
}

configure_wifi() {
    echo "Configuring Wi-Fi country and unblocking rfkill..."
    # Set Wi-Fi country to GB (adjust as needed)
    if command -v raspi-config >/dev/null 2>&1; then
        echo "Setting Wi-Fi country to GB using raspi-config..."
        raspi-config nonint do_wifi_country GB
    else
        echo "raspi-config not available, setting Wi-Fi country manually..."
        if [[ ! -f /etc/wpa_supplicant/wpa_supplicant.conf ]] || ! grep -q "country=" /etc/wpa_supplicant/wpa_supplicant.conf; then
            echo "country=GB" >> /etc/wpa_supplicant/wpa_supplicant.conf
        fi
    fi

    # Unblock Wi-Fi if rfkill is blocking it
    if command -v rfkill >/dev/null 2>&1; then
        echo "Unblocking Wi-Fi with rfkill..."
        rfkill unblock wifi
        rfkill unblock all
    else
        echo "rfkill not available, skipping Wi-Fi unblock"
    fi

    wpa_passphrase ETHOSCOPE_WIFI ETHOSCOPE_1234 > /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
    systemctl enable wpa_supplicant
    systemctl enable wpa_supplicant@wlan0.service
}

#===============================================================================
# DATABASE CONFIGURATION
#===============================================================================

setup_mariadb() {
    echo "Setting up MariaDB database..."
    # Initialize MariaDB data directory if not already done
    if [ ! -d "/var/lib/mysql/mysql" ]; then
        echo "Initializing MariaDB data directory..."
        mysql_install_db --user=mysql --basedir=/usr --datadir=/var/lib/mysql
    fi

    # Ensure proper ownership
    chown -R mysql:mysql /var/lib/mysql

    # Start MariaDB service
    systemctl start mysqld.service

    # Wait for MariaDB to be ready
    echo "Waiting for MariaDB to start..."
    for i in {1..30}; do
        if mysqladmin ping >/dev/null 2>&1; then
            echo "MariaDB is ready"
            break
        fi
        if [ $i -eq 30 ]; then
            echo "ERROR: MariaDB failed to start within 30 seconds"
            exit 1
        fi
        sleep 1
    done

    # Set up ethoscope database user
    echo "Creating ethoscope database user..."
    mysql -u root <<EOF
-- Create ethoscope user for local and network connections
CREATE USER IF NOT EXISTS 'ethoscope'@'localhost' IDENTIFIED BY 'ethoscope';
CREATE USER IF NOT EXISTS 'ethoscope'@'%' IDENTIFIED BY 'ethoscope';

-- Grant necessary permissions including RELOAD and GRANT OPTION
GRANT ALL PRIVILEGES ON *.* TO 'ethoscope'@'localhost' WITH GRANT OPTION;
GRANT ALL PRIVILEGES ON *.* TO 'ethoscope'@'%' WITH GRANT OPTION;

-- Flush privileges to ensure changes take effect
FLUSH PRIVILEGES;
EOF

    if [ $? -eq 0 ]; then
        echo "Database user created successfully"
    else
        echo "ERROR: Failed to create database user"
        exit 1
    fi
}

configure_mariadb() {
    echo "Configuring MariaDB for ethoscope use on $PI_MODEL..."
    
    # Set memory limits based on Pi model
    local buffer_pool_size="64M"
    local log_file_size="16M"
    local key_buffer_size="16M"
    local max_connections="50"
    
    if [[ "$PI_MODEL" == "pi2" ]]; then
        buffer_pool_size="32M"
        log_file_size="8M"
        key_buffer_size="8M"
        max_connections="25"
    elif [[ "$PI_MODEL" == "pi3" ]]; then
        buffer_pool_size="64M"
        log_file_size="16M"
        key_buffer_size="16M"
        max_connections="40"
    elif [[ "$PI_MODEL" == "pi4" ]]; then
        buffer_pool_size="128M"
        log_file_size="32M"
        key_buffer_size="32M"
        max_connections="75"
    elif [[ "$PI_MODEL" == "pi5" ]]; then
        buffer_pool_size="256M"
        log_file_size="64M"
        key_buffer_size="64M"
        max_connections="100"
    fi
    
    # Ensure config directory exists
    if [ -n "$MYCNF" ]; then
        mkdir -p "$(dirname "$MYCNF")"
        
        echo "Creating MariaDB configuration at $MYCNF..."
        cat > "$MYCNF" <<EOF
[server]
# Binary logging configuration for replication/backup
log-bin          = mysql-bin
binlog_format    = mixed
expire_logs_days = 10
max_binlog_size  = 100M

# Network configuration - allow connections from ethoscope network
bind-address     = 0.0.0.0

# Performance optimizations for $PI_MODEL
innodb_buffer_pool_size = $buffer_pool_size
innodb_log_file_size = $log_file_size
key_buffer_size = $key_buffer_size
max_connections = $max_connections

# Reduce disk I/O for SD card longevity
innodb_flush_log_at_trx_commit = 2
sync_binlog = 0
EOF
        
        echo "MariaDB configuration written successfully for $PI_MODEL"
    else
        echo "WARNING: Could not determine MariaDB config location for this OS"
    fi
}

#===============================================================================
# HARDWARE CONFIGURATION
#===============================================================================

configure_raspberry_pi_hardware() {
    local revision=$(grep 'Revision' /proc/cpuinfo | awk '{print $3}')
    
    echo "Configuring Raspberry Pi $PI_MODEL hardware..."
    
    # Common settings for all Pi versions
    echo "Disabling Bluetooth (not needed for ethoscope)..."
    echo 'dtoverlay=disable-bt' >> "$BOOTCFG"

    echo "Enable default HDMI output"
    echo 'hdmi_force_hotplug=1' >> "$BOOTCFG"

    echo "Enabling I2C support for hardware interfaces..."
    echo 'dtparam=i2c_arm=on' >> "$BOOTCFG"
    echo 'i2c-dev' >> /etc/modules-load.d/raspberrypi.conf

    # Camera configuration based on Pi model
    echo "Configuring camera for $PI_MODEL..."
    echo 'disable_camera_led=1' >> "$BOOTCFG"
    
    if [[ "$PI_MODEL" == "pi2" || "$PI_MODEL" == "pi3" ]]; then
        echo "Configuring legacy camera (Pi 2/3)..."
        echo 'start_file=start_x.elf' >> "$BOOTCFG"
        echo 'fixup_file=fixup_x.dat' >> "$BOOTCFG"
        echo 'gpu_mem=256' >> "$BOOTCFG"
        echo 'cma_lwm=' >> "$BOOTCFG"
        echo 'cma_hwm=' >> "$BOOTCFG"
        echo 'cma_offline_start=' >> "$BOOTCFG"

        # https://github.com/raspberrypi/firmware/issues/1167
        echo 'awb_auto_is_greyworld=1' >> "$BOOTCFG"

        echo 'Loading bcm2835 module for legacy camera'
        echo 'bcm2835-v4l2' > /etc/modules-load.d/picamera.conf
        
    elif [[ "$PI_MODEL" == "pi4" ]]; then
        echo "Configuring camera for Pi 4..."
        echo 'dtoverlay=vc4-kms-v3d' >> "$BOOTCFG"
        echo 'gpu_mem=256' >> "$BOOTCFG"
        echo 'dtoverlay=imx219' >> "$BOOTCFG"
        
    elif [[ "$PI_MODEL" == "pi5" ]]; then
        echo "Configuring camera for Pi 5..."
        echo 'dtoverlay=vc4-kms-v3d' >> "$BOOTCFG"
        echo 'gpu_mem=256' >> "$BOOTCFG"
        echo 'dtoverlay=imx219' >> "$BOOTCFG"
        
    else
        echo "Unknown Pi model, using basic camera configuration..."
        echo 'gpu_mem=128' >> "$BOOTCFG"
        echo 'dtoverlay=imx219' >> "$BOOTCFG"
    fi
    
    # Enable camera interface for all models
    echo 'camera_auto_detect=1' >> "$BOOTCFG"
    echo 'dtparam=camera=on' >> "$BOOTCFG"
}

#===============================================================================
# MAIN EXECUTION
#===============================================================================

main() {
    check_root
    detect_pi_model
    determine_config_paths
    
    setup_ethoscope_user
    install_ethoscope_software
    configure_system_identity
    configure_time_sync
    enable_system_services
    configure_network
    configure_wifi
    setup_mariadb
    configure_mariadb
    configure_raspberry_pi_hardware
    
    echo ""
    echo "==============================================="
    echo "Ethoscope installation completed successfully!"
    echo "==============================================="
    echo ""
    echo "Next steps:"
    echo "1. Reboot this Raspberry Pi: sudo reboot"
    echo "2. After reboot, the device will be accessible as ETHOSCOPE_000"
    echo "3. Change the device ID from 000 to a unique number"
    echo "4. Connect to the ethoscope network node for full functionality"
    echo ""
    echo "Please reboot now: sudo reboot"
}

# Check for "--apt-install" flag
if [ "$1" == "--apt-install" ]; then
  check_root
  install_apt_packages
  exit 0
fi

# Run main installation
main
