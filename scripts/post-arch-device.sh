#!/bin/sh

# This file can be downloaded at http://tinyurl.com/oyuh92j
######################################
# To build the sd card, follow instructions @ http://archlinuxarm.org/platforms/armv6/raspberry-pi
# Then run this script.
# After boot, one can log a s `root` (password = `root`)
# And run: `systemctl start slim` to start the window manager
######################################

set -e # stop if any error happens

export USER_NAME=ethoscope
export PASSWORD=ethoscope
export DATA_DIR=/ethoscope_data
export DB_NAME=ethoscope_db
export TARGET_GIT_INSTALL=/opt/ethoscope-git
export UPDATER_LOCATION_IN_GIT=scripts/ethoscope_updater
export TARGET_UPDATER_DIR=/opt/ethoscope_updater
export NODE_IP=192.169.123.1
export BARE_GIT_NAME=ethoscope.git




############# PACKAGES #########################
echo 'Installing and updating packages'

pacman -Syu --noconfirm
pacman -S base-devel git gcc-fortran rsync wget --noconfirm --needed
### Video capture related
pacman -S opencv mplayer ffmpeg gstreamer gstreamer0.10-plugins mencoder --noconfirm --needed
# a desktop environment may be useful:
pacman -S xorg-server xorg-utils xorg-server-utils xorg-xinit xf86-video-fbdev lxde slim --noconfirm --needed
# utilities
pacman -S ntp bash-completion --noconfirm --needed
pacman -S raspberrypi-firmware{,-tools,-bootloader,-examples} --noconfirm --needed

# preinstalling dependencies will save compiling time on python packages
pacman -S python2-pip python2-numpy python2-bottle python2-pyserial mysql-python python2-cherrypy python2-scipy --noconfirm --needed

# mariadb
pacman -S mariadb --noconfirm --needed
pacman -S fake-hwclock --noconfirm --needed

#setup Wifi dongle
#pacman -S netctl
pacman -S wpa_supplicant ifplugd wpa_actiond --noconfirm --needed
pacman -S libev --noconfirm --needed

pip2 install 'picamera[array]'

echo 'Description=ethoscope_wifi network' > /etc/netctl/wlan0
echo 'Interface=wlan0' >> /etc/netctl/wlan0
echo 'Connection=wireless' >> /etc/netctl/wlan0
echo 'Security=wpa' >> /etc/netctl/wlan0
echo 'IP=dhcp' >> /etc/netctl/wlan0
echo 'TimeoutDHCP=60' >> /etc/netctl/wlan0
echo 'ESSID=ETHOSCOPE_WIFI' >> /etc/netctl/wlan0
# Prepend hexadecimal keys with \"
# If your key starts with ", write it as '""<key>"'
# See also: the section on special quoting rules in netctl.profile(5)

#TODO set new password
echo 'Key=ETHOSCOPE_1234' >> /etc/netctl/wlan0




# Uncomment this if your ssid is hidden
#echo 'Hidden=yes'

######################################################################################
echo 'Description=eth0 Network' > /etc/netctl/eth0
echo 'Interface=eth0' >> /etc/netctl/eth0
echo 'Connection=ethernet' >> /etc/netctl/eth0
echo 'IP=dhcp' >> /etc/netctl/eth0
######################################################################################


#Updating ntp.conf

echo "server $NODE_IP" > /etc/ntp.conf
echo 'server 127.127.1.0' >> /etc/ntp.conf
echo 'fudge 127.127.1.0 stratum 10' >> /etc/ntp.conf
echo 'restrict default kod limited nomodify nopeer noquery notrap' >> /etc/ntp.conf
echo 'restrict 127.0.0.1' >> /etc/ntp.conf
echo 'restrict ::1' >> /etc/ntp.conf
echo 'driftfile /var/lib/ntp/ntp.drift' >> /etc/ntp.conf

######################################################################################



######################################################################################

echo 'Enabling startuup deamons'

systemctl disable systemd-networkd
ip link set eth0 down
# Enable networktime protocol
systemctl start ntpd.service
systemctl enable ntpd.service
systemctl enable fake-hwclock  fake-hwclock-save.timer
systemctl start fake-hwclock
# Setting up ssh server
systemctl enable sshd.service
systemctl start sshd.service
#setting up wifi
#Fixme this does not work if the pi is not connected to a ethoscope_wifi



netctl-auto enable wlan0
netctl-auto start wlan0
systemctl enable netctl-auto@wlan0.service
systemctl start netctl-auto@wlan0.service
systemctl enable netctl-ifplugd@wlan0.service
systemctl start netctl-ifplugd@wlan0.service


netctl enable eth0
netctl start eth0
systemctl enable netctl@eth0.service
systemctl start netctl@eth0.service
systemctl enable netctl-ifplugd@eth0.service
systemctl start netctl-ifplugd@eth0.service
#device service

#TODO s: locale/TIMEZONE/keyboard ...

##########################################################################################
# add password without stoping
#echo 'Creating default user'
#
#pass=$(perl -e 'print crypt($ARGV[0], "password")' $PASSWORD)
#useradd -m -g users -G wheel -s /bin/bash  -p $pass $USER_NAME || echo 'warning: user exists'
#
#echo 'exec startlxde' >> /home/$USER_NAME/.xinitrc
#chown $USER_NAME /home/$USER_NAME/.xinitrc
#echo 'Setting permissions for using arduino'
##SEE https://wiki.archlinux.org/index.php/arduino#Configuration
#gpasswd -a $USER_NAME uucp
#gpasswd -a $USER_NAME lock
#gpasswd -a $USER_NAME tty



############################################
echo 'Generating boot config'

echo 'start_file=start_x.elf' > /boot/config.txt
echo 'fixup_file=fixup_x.dat' >> /boot/config.txt
echo 'disable_camera_led=1' >> /boot/config.txt
echo 'gpu_mem=256' >>  /boot/config.txt
echo 'cma_lwm=' >>  /boot/config.txt
echo 'cma_hwm=' >>  /boot/config.txt
echo 'cma_offline_start=' >>  /boot/config.txt


echo 'Loading bcm2835 module'

#to use the camera through v4l2
# modprobe bcm2835-v4l2
echo "bcm2835-v4l2" > /etc/modules-load.d/picamera.conf


###########################################################################################
# The hostname is derived from the **eth0** MAC address, NOT the wireless one
#mac_addr=$(ip link show  eth0  |  grep -ioh '[0-9A-F]\{2\}\(:[0-9A-F]\{2\}\)\{5\}' | head -1 | sed s/://g)
# The hostname is derived from the **machine-id**, located in /etc/machine-id

device_id=$(cat /etc/machine-id)
hostname=PI_$device_id
echo "Hostname is $hostname"
hostnamectl set-hostname $hostname



echo "setting up mysql"
mysql_install_db --user=mysql --basedir=/usr --datadir=/var/lib/mysql
systemctl start mysqld.service
systemctl enable mysqld.service

## not even useful:
#mysql -u root -e "create database $DB_NAME";

mysql -u root -e "CREATE USER \"$USER_NAME\"@'localhost' IDENTIFIED BY \"$PASSWORD\""
mysql -u root -e "CREATE USER \"$USER_NAME\"@'%' IDENTIFIED BY \"$PASSWORD\""
mysql -u root -e "GRANT ALL PRIVILEGES ON *.* TO \"$USER_NAME\"@'localhost' WITH GRANT OPTION";
mysql -u root -e "GRANT ALL PRIVILEGES ON *.* TO \"$USER_NAME\"@'%' WITH GRANT OPTION";


# This disables binary logs to save on I/O, space
# 1 backup:
cp /etc/mysql/my.cnf  /etc/mysql/my.cnf-bak
# remove log-bin lines
cat /etc/mysql/my.cnf-bak | grep -v log-bin >  /etc/mysql/my.cnf


##########
#Create a local working copy from the bare repo, located on node
echo 'Cloning from Node'

# FIXME this needs a node in the network to set up the git
git clone git://$NODE_IP/$BARE_GIT_NAME $TARGET_GIT_INSTALL

# our software.
cd $TARGET_GIT_INSTALL/src
pip2 install -e .

cp $TARGET_GIT_INSTALL/$UPDATER_LOCATION_IN_GIT $TARGET_UPDATER_DIR -r
cd $TARGET_UPDATER_DIR

cp ethoscope_update.service /etc/systemd/system/ethoscope_update.service
cp clean_mysql.service /etc/systemd/system/clean_mysql.service

systemctl daemon-reload
systemctl enable ethoscope_device.service
systemctl enable ethoscope_updater.service
systemctl enable clean_mysql.service



# Disable power management
echo 'options 8192cu rtw_power_mgnt=0' > /etc/modprobe.d/8192cu.conf

#manual intervention =
# from http://www.martinglover.co.uk/speed-up-mysql-queries
#Add in the below line of code under the [mysqld] section:
# skip-name-resolve

#use tmpfs so we don't use too much disk io
echo 'tmpfs /tmp tmpfs defaults,noatime,mode=1777 0 0' >> /etc/fstab; cat /etc/fstab

echo 'SUCCESS, please reboot'


cp ./ethoscope_device.service /etc/systemd/system/ethoscope_device.service

#todo set up update daemon