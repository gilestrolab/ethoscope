#!/bin/bash

# Check if the script is run as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

# Function to perform update
update_repository() {
  echo "Updating repository and changing origin..."
  rm -rf /opt/ethoscope*
  git clone https://github.com/gilestrolab/ethoscope.git /opt/ethoscope

  cd /opt/ethoscope
  git checkout dev
  git remote set-url origin git://node/ethoscope.git
  cd /opt/ethoscope/src/ethoscope
  pip install -e . --break-system-packages

  systemctl enable ethoscope_device
  systemctl enable ethoscope_listener

  echo "Repository updated and origin changed."
}

# Check for "--update" flag. If present, updates but leaves everything else.
if [ "$1" == "--update" ]; then
  update_repository
  exit 0
fi

# Rest of the script executes if "--update" flag is not provided
update_repository

echo "set correct date"
date -s "$(wget --method=HEAD -qSO- --max-redirect=0 google.com 2>&1 | grep Date: | cut -d' ' -f5-10)"

echo "create 000 machine files"
echo "ETHOSCOPE_000" > /etc/machine-name
echo "ETHOSCOPE_000" > /etc/hostname

# Set timezone to UTC
sudo timedatectl set-timezone UTC

echo "create the default network configuration files"
echo $'[Match]\nName=eth0\n\n[Network]\nDHCP=yes\n\n[DHCPv4]\nRouteMetric=10\n' > /etc/systemd/network/20-wired.network
echo $'[Match]\nName=wlan0\n\n\n[Network]\nDHCP=yes\n\n[DHCPv4]\nRouteMetric=20\n' > /etc/systemd/network/25-wireless.network

# Clean the Pacman cache if running on Arch Linux, otherwise use apt-get
if command -v pacman &> /dev/null; then
  echo "Cleaning Pacman cache..."
  pacman -Scc --noconfirm
elif command -v apt-get &> /dev/null; then
  echo "Cleaning APT cache..."
  apt-get clean
else
  echo "No recognized package manager found. Skipping cache clean."
fi

echo "Now shutdown"
