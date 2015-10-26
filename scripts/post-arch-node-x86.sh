#!/bin/sh

# This file can be downloaded at http://tinyurl.com/oyuh92j
######################################
# To build the sd card, follow instructions @ http://archlinuxarm.org/platforms/armv6/raspberry-pi
# Then run this script.
# After boot, one can log a s `root` (password = `root`)
# And run: `systemctl start slim` to start the window manager
######################################

set -e # stop if any error happens

export USER_NAME=node
export PASSWORD=node
export DATA_DIR=/ethoscope_results
export STABLE_BRANCH=master
export UPSTREAM_GIT_REPO=https://github.com/gilestrolab/ethoscope.git
export LOCAL_BARE_PATH=/srv/git/ethoscope.git
export TARGET_UPDATER_DIR=/opt/ethoscope_updater
export TARGET_GIT_INSTALL=/opt/ethoscope-git
export UPDATER_LOCATION_IN_GIT=scripts/ethoscope_updater
export NODE_IP=192.169.123.1
export WL_INTERFACE=wlan0


############# PACKAGES #########################
echo 'Installing and updating packages'

# pacman-db-update
# pacman-key --init
pacman -Syu --noconfirm
pacman -S base-devel git gcc-fortran rsync wget fping --noconfirm --needed

### Video capture related Not needed in Node
#pacman -S opencv mplayer ffmpeg gstreamer gstreamer0.10-plugins mencoder --noconfirm --needed
# a desktop environment may be useful:
pacman -S xorg-server xorg-utils xorg-server-utils xorg-xinit xf86-video-fbdev lxde slim --noconfirm --needed
# utilities
pacman -S ntp bash-completion --noconfirm --needed
pacman -S dnsmasq --noconfirm --needed

# preinstalling dependencies will save compiling time on python packages
pacman -S python2-pip python2-numpy python2-bottle python2-pyserial mysql-python python2-netifaces python2-cherrypy python2-futures --noconfirm --needed

# mariadb
pacman -S mariadb --noconfirm --needed

#setup Wifi dongle
#pacman -S netctl
pacman -S wpa_supplicant --noconfirm --needed
pacman -S libev --noconfirm --needed

#Create a Bare repository with only the production branch in node, it is on /var/
echo 'creating bare repo'
mkdir -p /srv/git
git clone --bare $UPSTREAM_GIT_REPO $LOCAL_BARE_PATH

#Create a local working copy from the bare repo on node
echo 'Installing ethoscope package'
git clone $LOCAL_BARE_PATH $TARGET_GIT_INSTALL

cd $TARGET_GIT_INSTALL/node_src
pip2 install -e .
cd -




echo 'Description=psv wifi network' > /etc/netctl/ethoscope_wifi
echo "Interface=$WL_INTERFACE" >> /etc/netctl/ethoscope_wifi
echo 'Connection=wireless' >> /etc/netctl/ethoscope_wifi
echo 'Security=wpa' >> /etc/netctl/ethoscope_wifi
echo 'IP=dhcp' >> /etc/netctl/ethoscope_wifi
echo 'ESSID=ETHOSCOPE_WIFI' >> /etc/netctl/ethoscope_wifi
# Prepend hexadecimal keys with \"
# If your key starts with ", write it as '""<key>"'
# See also: the section on special quoting rules in netctl.profile(5)
echo 'Key=ETHOSCOPE_1234' >> /etc/netctl/ethoscope_wifi
# Uncomment this if your ssid is hidden
#echo 'Hidden=yes'

#
#####################################################################################
echo 'Description=eth0 Network' > /etc/netctl/eth0
echo 'Interface=eth0' >> /etc/netctl/eth0
echo 'Connection=ethernet' >> /etc/netctl/eth0
echo 'IP=dhcp' >> /etc/netctl/eth0
######################################################################################

#Creating service for device_server.py
cp ./ethoscope_node.service /etc/systemd/system/ethoscope_node.service
cp ./ethoscope_backup.service /etc/systemd/system/ethoscope_backup.service


#configuring dns server:
echo "interface=$WL_INTERFACE" >/etc/dnsmasq.conf
echo "dhcp-option = 6,$NODE_IP" >> /etc/dnsmasq.conf
echo "no-hosts" >> /etc/dnsmasq.conf
echo "addn-hosts=/etc/host.dnsmasq" >> /etc/dnsmasq.conf
#domain=polygonaltreenetwork.com,192.169.123.0/24

echo "$NODE_IP    node" >> /etc/hosts.dnsmasq


systemctl daemon-reload
######################################################################################

######################################################################################
echo 'Enabling startuup deamons'

systemctl disable systemd-networkd
ip link set eth0 down
# Enable networktime protocol
systemctl start ntpd.service
systemctl enable ntpd.service
# Setting up ssh server
systemctl enable sshd.service
systemctl start sshd.service
systemctl start git-daemon.socket
systemctl enable git-daemon.socket

#setting up wifi
# FIXME this not work if not psv-wifi
netctl start ethoscope_wifi || echo 'No ethoscope_wifi connection'
netctl enable ethoscope_wifi
netctl enable eth0
netctl start eth0


#node service
systemctl start ethoscope_node.service
systemctl enable ethoscope_node.service
systemctl enable ethoscope_backup.service

##########################################################################################
# add password without stoping
echo 'Creating default user'

pass=$(perl -e 'print crypt($ARGV[0], "password")' $PASSWORD)
useradd -m -g users -G wheel -s /bin/bash  -p $pass $USER_NAME || echo 'user exists'



###########################################################################################
# The hostname is derived from the **eth0** MAC address, NOT the wireless one
#mac_addr=$(ip link show  eth0  |  grep -ioh '[0-9A-F]\{2\}\(:[0-9A-F]\{2\}\)\{5\}' | head -1 | sed s/://g)
# The hostname is derived from the **machine-id**, located in /etc/machine-id

device_id=$(cat /etc/machine-id)
#hostname=PI_$device_id
hostname='node'
echo "Hostname is $hostname"
hostnamectl set-hostname $hostname


cp $TARGET_GIT_INSTALL/$UPDATER_LOCATION_IN_GIT $TARGET_UPDATER_DIR -r
cd $TARGET_UPDATER_DIR
cp ethoscope_update_node.service /etc/systemd/system/ethoscope_update_node.service

systemctl daemon-reload
systemctl enable ethoscope_update_node.service


#todo set up update daemon
