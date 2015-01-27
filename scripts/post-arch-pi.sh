#!/bin/sh

# This file can be downloaded at http://tinyurl.com/oyuh92j
######################################
# To build the sd card, follow instructions @ http://archlinuxarm.org/platforms/armv6/raspberry-pi
# Then run this script.
# After boot, one can log a s `root` (password = `root`)
# And run: `systemctl start slim` to start the window manager
######################################

set -e # stop if any error happens

USER_NAME=psv
PASSWORD=psv


############# PACKAGES #########################
# pacman-db-update
# pacman-key --init
pacman -Syu --noconfirm
pacman -S base-devel git gcc-fortran --noconfirm --needed
### Video capture related
pacman -S opencv mplayer ffmpeg gstreamer gstreamer0.10-plugins mencoder --noconfirm --needed
# a desktop environment may be useful:
pacman -S xorg-server xorg-utils xorg-server-utils xorg-xinit xf86-video-fbdev lxde slim --noconfirm --needed
# utilities
pacman -S ntp bash-completion --noconfirm --needed
pacman -S raspberrypi-firmware{,-tools,-bootloader,-examples} --noconfirm --needed

# preinstalling dependencies will save compiling time on python packages
pacman -S python2-pip python2-numpy python2-bottle python2-pyserial --noconfirm --needed

######################################################################################

# Enable networktime protocol
systemctl start ntpd.service
systemctl enable ntpd.service
# Setting up ssh server
systemctl enable sshd.service
systemctl start sshd.service

#TODOs: locale/TIMEZONE/keyboard ...

##########################################################################################
# add password without stopping
pass=$(perl -e 'print crypt($ARGV[0], "password")' $PASSWORD)
useradd -m -g users -G wheel -s /bin/bash  -p $pass $USER_NAME


echo 'exec startlxde' >> /home/$USER_NAME/.xinitrc
chown $USER_NAME /home/$USER_NAME/.xinitrc


############################################

echo 'start_file=start_x.elf' > /boot/config.txt
echo 'fixup_file=fixup_x.dat' >> /boot/config.txt
echo 'disable_camera_led=1' >> /boot/config.txt
#gpu_mem_512=64
#gpu_mem_256=64

##Turbo
echo 'arm_freq=1000' >> /boot/config.txt
echo 'core_freq=500' >> /boot/config.txt
echo 'sdram_freq=500' >> /boot/config.txt
echo 'over_voltage=6' >> /boot/config.txt

### TODO test, is that enough?
echo 'gpu_mem=128' >>  /boot/config.txt
echo 'cma_lwm=' >>  /boot/config.txt
echo 'cma_hwm=' >>  /boot/config.txt
echo 'cma_offline_start=' >>  /boot/config.txt

# disable I2C module to allow cammera to work. 
# See http://archlinuxarm.org/forum/viewtopic.php?f=31&t=7616
# NOT NEEDED
### echo "blacklist i2c_bcm2708" > /etc/modprobe.d/blacklist.conf


# to use the camera through v4l2
modprobe bcm2835-v4l2
echo "bcm2835-v4l2" > /etc/modules-load.d/picamera.conf



#SEE https://wiki.archlinux.org/index.php/arduino#Configuration
gpasswd -a $USER_NAME uucp
gpasswd -a $USER_NAME lock
gpasswd -a $USER_NAME tty


###########################################################################################
# The hostname is derived from the **eth0** MAC address, NOT the wireless one
#mac_addr=$(ip link show  eth0  |  grep -ioh '[0-9A-F]\{2\}\(:[0-9A-F]\{2\}\)\{5\}' | head -1 | sed s/://g)
# The hostname is derived from the **machine-id**, located in /etc/machine-id
device_id =$(cat /etc/machine-id)
hostname=PI_$device_id
hostnamectl set-hostname $hostname

# our software.
# TODO use AUR!
wget https://github.com/gilestrolab/pySolo-Video/archive/psv_prerelease.tar.gz -O psv.tar.gz
tar -xvf psv.tar.gz
cd pySolo-Video-*/src
pip2 install .
