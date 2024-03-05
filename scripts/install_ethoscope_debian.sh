#!/bin/bash

# Check if the script is running as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root. Use sudo to run it." 1>&2
   exit 1
fi

echo "Create ethoscope user and change passwd"
useradd -m ethoscope
echo -e "ethoscope\nethoscope" | sudo passwd ethoscope
gpasswd -a ethoscope root

echo "clone and rename folders"
git clone https://github.com/gilestrolab/ethoscope.git /opt/ethoscope-device
ln -s /opt/ethoscope-device/scripts/ethoscope_updater /opt/

echo "setting dev branch and changing remote git source to the node"
cd /opt/ethoscope-device/
git checkout dev
git remote set-url origin git://node/ethoscope.git

echo "make and install python wheel"
cd /opt/ethoscope-device/src
python setup.py develop

echo "install systemd files"
cp /opt/ethoscope-device/scripts/{ethoscope_device.service,ethoscope_listener.service,ethoscope_GPIO_listener.service} /usr/lib/systemd/system/
cp /opt/ethoscope-device/scripts/ethoscope_updater/ethoscope_update.service /usr/lib/systemd/system/

echo "create 000 machine files"
echo "ETHOSCOPE_000" > /etc/machine-name
echo "ETHOSCOPE_000" > /etc/hostname

echo "create an ethoclient command"
echo $'#!/bin/env bash\npython /opt/ethoscope-device/src/scripts/ethoclient.py $@' > /usr/bin/ethoclient
chmod +x /usr/bin/ethoclient

echo "create a verbose login prompt"
echo 'Ethoscope Linux \r  (\n) (\l)' > /etc/issue
echo 'Ethernet IP: \4{eth0}' >> /etc/issue
echo 'WIFI IP: \4{wlan0}' >> /etc/issue
echo 'Time on Device: \d \t' >> /etc/issue

#echo "activates remote journal upload"
#echo $'[Upload]\nURL=http://node:19532\n' > /etc/systemd/journal-upload.conf

echo "configure the NTP file"
echo 'server node' > /etc/ntp.conf
echo 'server 127.127.1.0' >> /etc/ntp.conf
echo 'fudge 127.127.1.0 stratum 10' >> /etc/ntp.conf
echo 'restrict default kod limited nomodify nopeer noquery notrap' >> /etc/ntp.conf
echo 'restrict 127.0.0.1' >> /etc/ntp.conf
echo 'restrict ::1' >> /etc/ntp.conf
echo 'driftfile /var/lib/ntp/ntp.drift' >> /etc/ntp.conf

echo "enabling DEVICE specific systemd service files"
systemctl enable ethoscope_device.service ethoscope_listener.service ethoscope_update.service ethoscope_GPIO_listener.service
systemctl enable ntpd.service mysqld.service sshd.service mysqld.service avahi-daemon.service
#systemctl enable fake-hwclock fake-hwclock-save.timer

echo "create the default network configuration files"
echo $'[Match]\nName=eth0\n\n[Network]\nDHCP=yes\n\n[DHCPv4]\nRouteMetric=10\n' > /etc/systemd/network/20-wired.network
echo $'[Match]\nName=wlan0\n\n\n[Network]\nDHCP=yes\n\n[DHCPv4]\nRouteMetric=20\n' > /etc/systemd/network/25-wireless.network

systemctl enable systemd-networkd systemd-resolved
systemctl disable NetworkManager ModemManager

wpa_passphrase ETHOSCOPE_WIFI ETHOSCOPE_1234 > /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
systemctl enable wpa_supplicant
systemctl enable wpa_supplicant@wlan0.service

echo "Set up mysql database"
mysql_install_db --user=mysql --basedir=/usr --datadir=/var/lib/mysql
systemctl start mysqld.service
mysql -u root -e "CREATE USER 'ethoscope'@'localhost' IDENTIFIED BY 'ethoscope'"
mysql -u root -e "CREATE USER 'ethoscope'@'%' IDENTIFIED BY 'ethoscope'"
mysql -u root -e "GRANT ALL PRIVILEGES ON *.* TO 'ethoscope'@'localhost' WITH GRANT OPTION";
mysql -u root -e "GRANT ALL PRIVILEGES ON *.* TO 'ethoscope'@'%' WITH GRANT OPTION";
chown -R mysql:mysql /var/lib/mysql

echo "setup mariadb/mysql configuration"

# Initialize MYCNF variable
MYCNF=""

# Check for OS-specific configurations
if [ -f "/etc/os-release" ]; then
    # Source the os-release file to use its variables
    . /etc/os-release
    
    # Check if running on Raspbian
    if [[ "$ID" == "debian" ]]; then
        MYCNF="/etc/mysql/mariadb.conf.d/ethoscope.cnf"
        BOOTCFG="/boot/firmware/config.txt"
    # Check if running on Arch Linux
    elif [[ "$ID" == "arch" ]]; then
        MYCNF="/etc/my.cnf.d/ethoscope.cnf"
        BOOTCFG="/boot/config.txt"
    fi
fi

echo '[server]' > "$MYCNF"
echo 'log-bin=mysql-bin' >> "$MYCNF"
echo 'binlog_format=mixed' >> "$MYCNF"
echo 'expire_logs_days = 10' >> "$MYCNF"
echo 'max_binlog_size  = 100M' >> "$MYCNF"

echo "limiting journal log space"
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
    echo 'awb_auto_is_greyworld=1' >> /boot/config.txt

    echo 'Loading bcm2835 module'
    echo 'bcm2835-v4l2' > /etc/modules-load.d/picamera.conf
fi


echo "generating locale"
echo "en_GB.UTF-8 UTF-8" >> /etc/locale.gen
locale-gen

echo "disable bluetooth"
echo 'dtoverlay=disable-bt' >> "$BOOTCFG"

echo 'hdmi_force_hotplug=1' >> "$BOOTCFG"

#https://madflex.de/use-i2c-on-raspberry-pi-with-archlinux-arm/
echo "adding support to I2C"
echo 'dtparam=i2c_arm=on' >> "$BOOTCFG"
echo 'i2c-dev' >> /etc/modules-load.d/raspberrypi.conf

echo "Please reboot this PI now."
