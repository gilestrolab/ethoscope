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

# Check if the script is running as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root. Use sudo to run it." 1>&2
   exit 1
fi


# Function to perform update
install_apt_packages() {
    echo "Installing system packages and Python dependencies..."
    #Install all the necessary dependencies
    apt-get update && apt-get upgrade -y

    # Check if mysql-connector is available in repositories, otherwise fetch from debian
    if apt-cache show python3-mysql.connector >/dev/null 2>&1; then
        echo "python3-mysql.connector is available in repositories"
        apt-get install -y python3-mysql.connector
    else
        echo "python3-mysql.connector not available in repositories, fetching from debian..."
        wget http://ftp.uk.debian.org/debian/pool/main/m/mysql-connector-python/python3-mysql.connector_8.0.15-4_all.deb && dpkg -i python3-mysql.connector_8.0.15-4_all.deb
    fi

    apt-get install -y \
        python3-bottle python3-cheroot python3-cherrypy3 python3-opencv python3-pymysql \
        python3-git python3-matplotlib python3-mock python3-netifaces python3-serial \
        python3-usb python3-sklearn python3-setuptools python3-zeroconf python3-protobuf \
        python3-picamera2 mariadb-server mariadb-client ntp systemd-resolved
    echo "All necessary packages were installed. Now reboot."        
}

# Check for "--apt-install" flag. If present, updates but leaves everything else.
if [ "$1" == "--apt-install" ]; then
  install_apt_packages
  exit 0
fi

echo "Creating ethoscope user account..."
useradd -m ethoscope
echo -e "ethoscope\nethoscope" | sudo passwd ethoscope
gpasswd -a ethoscope root

echo "Cloning ethoscope software repository..."
git clone https://github.com/gilestrolab/ethoscope.git /opt/ethoscope

echo "Configuring git repository (dev branch, node remote)..."
cd /opt/ethoscope/
git checkout dev
git remote set-url origin git://node/ethoscope.git
git config --global --add safe.directory /opt/ethoscope

echo "Installing ethoscope Python package..."
cd /opt/ethoscope/src/ethoscope
pip3 install -e .

echo "Installing systemd service files..."
ln -s /opt/ethoscope/scripts/{ethoscope_device.service,ethoscope_listener.service,ethoscope_GPIO_listener.service} /usr/lib/systemd/system/
cp /opt/ethoscope/src/updater/ethoscope_update.service /usr/lib/systemd/system/

echo "Setting up default machine identity (ETHOSCOPE_000)..."
echo "ETHOSCOPE_000" > /etc/machine-name
echo "ETHOSCOPE_000" > /etc/hostname

echo "Creating ethoclient command line tool..."
echo $'#!/bin/env bash\npython /opt/ethoscope/src/ethoscope/scripts/ethoclient.py $@' > /usr/bin/ethoclient
chmod +x /usr/bin/ethoclient

echo "Configuring login prompt with network information..."
echo 'Ethoscope Linux \r  (\n) (\l)' > /etc/issue
echo 'Ethernet IP: \4{eth0}' >> /etc/issue
echo 'WIFI IP: \4{wlan0}' >> /etc/issue
echo 'Time on Device: \d \t' >> /etc/issue

#echo "activates remote journal upload"
#echo $'[Upload]\nURL=http://node:19532\n' > /etc/systemd/journal-upload.conf

echo "Configuring NTP time synchronization with node..."
echo 'server node' > /etc/ntp.conf
echo 'server 127.127.1.0' >> /etc/ntp.conf
echo 'fudge 127.127.1.0 stratum 10' >> /etc/ntp.conf
echo 'restrict default kod limited nomodify nopeer noquery notrap' >> /etc/ntp.conf
echo 'restrict 127.0.0.1' >> /etc/ntp.conf
echo 'restrict ::1' >> /etc/ntp.conf
echo 'driftfile /var/lib/ntp/ntp.drift' >> /etc/ntp.conf

echo "Enabling ethoscope device services..."
systemctl enable ethoscope_device.service ethoscope_listener.service ethoscope_update.service ethoscope_GPIO_listener.service
systemctl enable ntpd.service mysqld.service sshd.service avahi-daemon.service
#systemctl enable fake-hwclock fake-hwclock-save.timer

echo "Configuring network interfaces (ethernet + WiFi)..."
echo $'[Match]\nName=eth0\n\n[Network]\nDHCP=yes\n\n[DHCPv4]\nRouteMetric=10\n' > /etc/systemd/network/20-wired.network
echo $'[Match]\nName=wlan0\n\n\n[Network]\nDHCP=yes\n\n[DHCPv4]\nRouteMetric=20\n' > /etc/systemd/network/25-wireless.network

systemctl enable systemd-networkd systemd-resolved
# Disable networkd-wait-online to prevent boot hangs (known issue)
systemctl disable systemd-networkd-wait-online
systemctl disable NetworkManager ModemManager

wpa_passphrase ETHOSCOPE_WIFI ETHOSCOPE_1234 > /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
systemctl enable wpa_supplicant
systemctl enable wpa_supplicant@wlan0.service

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

# Set up ethoscope database user with appropriate permissions
echo "Creating ethoscope database user..."
mysql -u root <<EOF
-- Create ethoscope user for local and network connections
CREATE USER IF NOT EXISTS 'ethoscope'@'localhost' IDENTIFIED BY 'ethoscope';
CREATE USER IF NOT EXISTS 'ethoscope'@'%' IDENTIFIED BY 'ethoscope';

-- Grant necessary permissions (more restrictive than ALL PRIVILEGES)
GRANT CREATE, DROP, SELECT, INSERT, UPDATE, DELETE, INDEX, ALTER ON *.* TO 'ethoscope'@'localhost';
GRANT CREATE, DROP, SELECT, INSERT, UPDATE, DELETE, INDEX, ALTER ON *.* TO 'ethoscope'@'%';

-- Flush privileges to ensure changes take effect
FLUSH PRIVILEGES;
EOF

if [ $? -eq 0 ]; then
    echo "Database user created successfully"
else
    echo "ERROR: Failed to create database user"
    exit 1
fi

echo "Configuring MariaDB for ethoscope use..."

# Initialize MYCNF variable
MYCNF=""

# Check for OS-specific configurations
if [ -f "/etc/os-release" ]; then
    # Source the os-release file to use its variables
    . /etc/os-release
    
    # Check if running on Raspbian/Debian
    if [[ "$ID" == "debian" ]]; then
        MYCNF="/etc/mysql/mariadb.conf.d/ethoscope.cnf"
        BOOTCFG="/boot/firmware/config.txt"
    # Check if running on Arch Linux
    elif [[ "$ID" == "arch" ]]; then
        MYCNF="/etc/my.cnf.d/ethoscope.cnf"
        BOOTCFG="/boot/config.txt"
    fi
fi

# Ensure config directory exists
if [ -n "$MYCNF" ]; then
    mkdir -p "$(dirname "$MYCNF")"
    
    echo \"Creating MariaDB configuration at $MYCNF...\"
    cat > "$MYCNF" <<EOF
[server]
# Binary logging configuration for replication/backup
log-bin          = mysql-bin
binlog_format    = mixed
expire_logs_days = 10
max_binlog_size  = 100M

# Network configuration - allow connections from ethoscope network
bind-address     = 0.0.0.0

# Performance optimizations for Raspberry Pi
innodb_buffer_pool_size = 64M
innodb_log_file_size = 16M
key_buffer_size = 16M
max_connections = 50

# Reduce disk I/O for SD card longevity
innodb_flush_log_at_trx_commit = 2
sync_binlog = 0
EOF
    
    echo \"MariaDB configuration written successfully\"
else
    echo \"WARNING: Could not determine MariaDB config location for this OS\"
fi

echo "Limiting systemd journal log space to 250MB..."
echo 'SystemMaxUse=250MB' >> /etc/systemd/journald.conf

# Get the hardware model from /proc/cpuinfo
model=$(grep 'Model' /proc/cpuinfo | awk -F': ' '{print $2}')

# Alternatively, use the Revision field for more specific control
revision=$(grep 'Revision' /proc/cpuinfo | awk '{print $3}')

# Only if running on Raspberry Pi 2 or 3
# This checks the revision code; adjust as needed based on the specific models you're targeting
# Reference: https://elinux.org/RPi_HardwareHistory
# Note: Revision codes can vary, ensure to include all relevant codes for Pi 2 and 3
if [[ "$revision" == "a01041" || "$revision" == "a21041" || "$revision" == "a22042" ||
      "$revision" == "a02082" || "$revision" == "a22082" || "$revision" == "a32082" ||
      "$revision" == "a020d3" ]]; then
    echo "This script is running on a Raspberry Pi 2 or 3."
    echo "install picamera settings into the boot/config.txt"
    echo 'start_file=start_x.elf' > "$BOOTCFG"
    echo 'fixup_file=fixup_x.dat' >> "$BOOTCFG"
    echo 'disable_camera_led=1' >> "$BOOTCFG"
    echo 'gpu_mem=256' >> "$BOOTCFG"
    echo 'cma_lwm=' >> "$BOOTCFG"
    echo 'cma_hwm=' >> "$BOOTCFG"
    echo 'cma_offline_start=' >> "$BOOTCFG"

    # https://github.com/raspberrypi/firmware/issues/1167
    echo 'awb_auto_is_greyworld=1' >> "$BOOTCFG"

    echo 'Loading bcm2835 module'
    echo 'bcm2835-v4l2' > /etc/modules-load.d/picamera.conf
fi


echo "Generating en_GB.UTF-8 locale..."
echo "en_GB.UTF-8 UTF-8" >> /etc/locale.gen
locale-gen

echo "Disabling Bluetooth (not needed for ethoscope)..."
echo 'dtoverlay=disable-bt' >> "$BOOTCFG"

echo 'hdmi_force_hotplug=1' >> "$BOOTCFG"

#https://madflex.de/use-i2c-on-raspberry-pi-with-archlinux-arm/
echo "Enabling I2C support for hardware interfaces..."
echo 'dtparam=i2c_arm=on' >> "$BOOTCFG"
echo 'i2c-dev' >> /etc/modules-load.d/raspberrypi.conf

# Create a timestamp for this SD card image installation
echo $(date +%Y%m%d)_ethoscope_pi4.img > /etc/sdimagename

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
