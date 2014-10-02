######################################
# To build the sd card, follow instructions @ http://archlinuxarm.org/platforms/armv6/raspberry-pi
######################################

USER=psv

############# PACKAGES #########################
#### Note we should let pip deal with the python packages dependency
### to setup a computer in the lab just after installing arch:
pacman -Syu
pacman -S base-devel packer git
### Video capture related
pacman -S opencv mplayer ffmpeg gstreamer gstreamer0.10-plugins mencoder
# a desktop environment may be useful:
pacman -S xorg-server xorg-utils xorg-server-utils xorg-xinit xf86-video-fbdev lxde slim
# utilities
pacman -S ntp bash-completion

pacman -S raspberrypi-firmware{,-tools,-bootloader,-example}

pacman -S python2-pip

######################################################################################

# enable networktime protocol
systemctl start ntpd.service
systemctl enable ntpd.service
# setting up ssh server
systemctl enable sshd.service
systemctl start sshd.service

#TODOs: locale/TIMEZONE/keyboard ...

##########################################################################################
sudo useradd -m -g users -G wheel -s /bin/bash $USER
sudo passwd $USER

echo 'exec startlxde' >> /home/$USER/.xinitrc
chown $user /home/$USER/.xinitrc

# to start one could just run:
# systemctl start slim
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
echo 'gpu_mem=256' >>  /boot/config.txt
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

echo "Please REBOOT"

###########################################################################################
# here we should have a startup script set up to:
# 1) set individual hostnames to each pi (eg pi-M_A_C_A_D_D_R), where  M_A_C_A_D_D_R is the eth0 mac address
# 2) update our software stack if needed (from git master/AUR)

