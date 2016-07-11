This document explains how to setup an "ethoscope" **from scratch**.
It assumes you have experience with Unix/Linux tools.
It should be much easier and faster to burn a card from one our [available sd-card images](ethoscope.md).
Once you have burn one card, it is straightforward to make your own image file and burn it to multiple cards.


Getting the basic OS on the card
=======================================
We use Archlinux as the main operating system for the ethoscope platform.
The first part is to get Arch on the card.
This procedure is explained [here](https://archlinuxarm.org/platforms/armv7/broadcom/raspberry-pi-2).


Customisation
================
Once you have the card ready. we can start putting the software we need and changing configuration to have a working ethoscope.

Essential prerequisites
---------------------------------

Before you start you will need:

* a wifi dongle in the pi2 (so we can access the node, pi3 has wifi on board)
* a working internet connection via ethernet cable (so we can download extra software)
* a node running at `192.169.123.1` [see here](node.md)
* a working `ETHOSCOPE_WIFI` network [see here](network.md)
* a screen and a keyboard plugged in the pi make things simpler
 

Extra packages
--------------------------------

At this stage, you should have powered your pi and reach a login screen.
The username *and* passwords are `root`.

We will install a few software we need (or may need in the future), using `pacman`, the package manager:


```bash
# update/upgrade
pacman -Syu --noconfirm
pacman -S base-devel git gcc-fortran rsync wget --noconfirm --needed
# video processing / image analysis tools
pacman -S opencv libcl eigen mplayer ffmpeg gstreamer gstreamer0.10-plugins mencoder --noconfirm --needed
# a desktop environment may be useful:
pacman -S xorg-server xorg-utils xorg-server-utils xorg-xinit xf86-video-fbdev lxde slim --noconfirm --needed
# utilities
pacman -S ntp bash-completion --noconfirm --needed
# check we have all the firmware
pacman -S raspberrypi-firmware{,-tools,-bootloader,-examples} --noconfirm --needed
# preinstalling dependencies will save compiling time on python packages
pacman -S ipython2 python2-pip python2-numpy python2-bottle python2-pyserial mysql-python python2-cherrypy python2-scipy python2-pillow --noconfirm --needed
# mariadb (MySQL)
pacman -S mariadb --noconfirm --needed
# Emulate hardware clock in case ntp fails
pacman -S fake-hwclock --noconfirm --needed
#for setting up wireless/rooming 
pacman -S wpa_supplicant ifplugd wpa_actiond --noconfirm --needed
pacman -S libev --noconfirm --needed
pacman -S watchdog macchanger --noconfirm --needed
# we use pip to get picamera (python API to PiNoir)
pip2 install 'picamera[array]'
```

Environment variables
---------------------------

Here we define a few variables used in the rest of the installation 

```
# mysql credentials
USER_NAME=ethoscope
PASSWORD=ethoscope
DB_NAME=ethoscope_db
# where ethoscope saves temporary local files (e.g. videos)
DATA_DIR=/ethoscope_data
# where to install and find our software
TARGET_GIT_INSTALL=/opt/ethoscope-git
UPDATER_LOCATION_IN_GIT=scripts/ethoscope_updater
UPSTREAM_GIT_REPO=https://github.com/gilestrolab/ethoscope.git
TARGET_UPDATER_DIR=/opt/ethoscope_updater
BARE_GIT_NAME=ethoscope.git
# network stuff
NETWORK_SSID=ETHOSCOPE_WIFI
NETWORK_PASSWORD=ETHOSCOPE_1234
#ip addresses
NODE_SUBNET=192.169.123
NODE_IP=$NODE_SUBNET.1
```


Wireless connection
-------------------------------------

This operation creates a `/etc/netctl/wlan0` profile file. It is used for communication to the node, not the internet.

```
echo 'Description=ethoscope_wifi network' > /etc/netctl/wlan0
echo 'Interface=wlan0' >> /etc/netctl/wlan0
echo 'Connection=wireless' >> /etc/netctl/wlan0
echo 'Security=wpa' >> /etc/netctl/wlan0
echo 'IP=dhcp' >> /etc/netctl/wlan0
echo 'TimeoutDHCP=60' >> /etc/netctl/wlan0
echo "ESSID=$NETWORK_SSID" >> /etc/netctl/wlan0
echo "Key=$NETWORK_PASSWORD" >> /etc/netctl/wlan0
```
Wired connection
---------------------

This writes another profile file: `/etc/netctl/eth0`.
It can be used in intranet, but also for internet (e.g. if you want to update software). 

```
echo 'Description=eth0 Network' > /etc/netctl/eth0
echo 'Interface=eth0' >> /etc/netctl/eth0
echo 'Connection=ethernet' >> /etc/netctl/eth0
echo 'IP=dhcp' >> /etc/netctl/eth0
```

NTP
---------------------------

The pi does not have a hardware clock, so time will be reset/stopped  when it turns off.
One way to have accurate time is to use Network Time Protocol.
Since the pi are likely to only have access to local intranet, we use the node and an ntp server.
Let us assume that there could be several nodes with IP addresses from 1 to 5.

```
echo "server $NODE_SUBNET".1 > /etc/ntp.conf
echo "server $NODE_SUBNET".2 >> /etc/ntp.conf
echo "server $NODE_SUBNET".3 >> /etc/ntp.conf
echo "server $NODE_SUBNET".4 >> /etc/ntp.conf
echo "server $NODE_SUBNET".5 >> /etc/ntp.conf
echo 'server 127.127.1.0' >> /etc/ntp.conf
echo 'fudge 127.127.1.0 stratum 10' >> /etc/ntp.conf
echo 'restrict default kod limited nomodify nopeer noquery notrap' >> /etc/ntp.conf
echo 'restrict 127.0.0.1' >> /etc/ntp.conf
echo 'restrict ::1' >> /etc/ntp.conf
echo 'driftfile /var/lib/ntp/ntp.drift' >> /etc/ntp.conf
```



Network daemons
----------------------------


```
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
```

```
#setting up wifi
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
```

At this stage you may want to reboot and check that you have both `eth0` and `wlan0` working (i.e. use `ip a`).
If you do,  **do not forget to redefine our environment variables!**

MySQL
---------------------------------
Ethoscope saves real time tracking data to a MySQL db.

```
mysql_install_db --user=mysql --basedir=/usr --datadir=/var/lib/mysql
systemctl start mysqld.service
systemctl enable mysqld.service
mysql -u root -e "CREATE USER \"$USER_NAME\"@'localhost' IDENTIFIED BY \"$PASSWORD\""
mysql -u root -e "CREATE USER \"$USER_NAME\"@'%' IDENTIFIED BY \"$PASSWORD\""
mysql -u root -e "GRANT ALL PRIVILEGES ON *.* TO \"$USER_NAME\"@'localhost' WITH GRANT OPTION";
mysql -u root -e "GRANT ALL PRIVILEGES ON *.* TO \"$USER_NAME\"@'%' WITH GRANT OPTION";
```

We can speedup mysql queries by adding, under the [mysqld] section `skip-name-resolve` in the mysql configuration file.

```
nano /etc/mysql/my.cnf
```

In addition, you may want to increase the memory allocation:

```
innodb_buffer_pool_size = 128M
innodb_additional_mem_pool_size = 64M
innodb_log_file_size = 32M
innodb_log_buffer_size = 50M
innodb_flush_log_at_trx_commit = 1
innodb_lock_wait_timeout = 50
```




Getting the ethoscope software
--------------------------------------

```
git clone git://$NODE_IP/$BARE_GIT_NAME $TARGET_GIT_INSTALL
cd $TARGET_GIT_INSTALL
# this allor to pull from other nodes
for i in $(seq 2 5); do git remote set-url origin --add git://$NODE_SUBNET.$i/$BARE_GIT_NAME; done
git remote set-url origin --add $UPSTREAM_GIT_REPO
git remote get-url --all   origin
cd $TARGET_GIT_INSTALL/src
```

**If you are not going to use the master branch, you should check out to your default branch. For instance:**
```
git checkout dev
```

The we install the package with `pip` (`[device]` means we install optional deps for the device):

```
pip2 install -e .[device]
```

We copy our own services to `systemd` service list:

```
cp $TARGET_GIT_INSTALL/scripts/ethoscope_device.service /etc/systemd/system/ethoscope_device.service
```

We move the updater webserver out of the ethoscope, so the updated does not update (/break) itself:

```
cp $TARGET_GIT_INSTALL/$UPDATER_LOCATION_IN_GIT $TARGET_UPDATER_DIR -r
cd $TARGET_UPDATER_DIR
cp ethoscope_update.service /etc/systemd/system/ethoscope_update.service
```

Now we can enable all:
```
systemctl daemon-reload
systemctl enable ethoscope_device.service
systemctl enable ethoscope_update.service
```


Boot config file
------------------------------------

We ensure boot config will allow us to work with the pi camera
	
```
echo 'start_file=start_x.elf' > /boot/config.txt
echo 'fixup_file=fixup_x.dat' >> /boot/config.txt
echo 'disable_camera_led=1' >> /boot/config.txt
echo 'gpu_mem=256' >>  /boot/config.txt
echo 'cma_lwm=' >>  /boot/config.txt
echo 'cma_hwm=' >>  /boot/config.txt
echo 'cma_offline_start=' >>  /boot/config.txt
echo 'Loading bcm2835 module'
echo "bcm2835-v4l2" > /etc/modules-load.d/picamera.conf
```

Failure tolerance
------------------------------------
It is possible that power, SD card or any other hardware inseplicably fails whilst tracking.
For this reason, we can set up the watchdog timer, so that the pi will restart itself in case of freezes.

```
echo "bcm2708_wdog" | sudo tee /etc/modules-load.d/bcm2708_wdog.conf
sudo systemctl enable watchdog
```

A small disk write test can be created:
```
mkdir /etc/watchdog.d/
echo '#!/bin/bash' > /etc/watchdog.d/write_test.sh && chmod 755 /etc/watchdog.d/write_test.sh
echo 'sleep 5 &&  touch /var/tmp/write_test' >> /etc/watchdog.d/write_test.sh && chmod 755 /etc/watchdog.d/write_test.sh
```

We can add a few things to the config file (`nano /etc/watchdog.conf`):

```
max-load-1 = 24
watchdog-device = /dev/watchdog
realtime = yes
priority = 1
```

A good documentation is provided [here](http://www.sat.dundee.ac.uk/psc/watchdog/watchdog-configure.html)


Last touches
--------------
There is an issue with some wireless dongles that go to idle if unused, but then become really hard to reach.
We can disable power management for these dongle:
```
echo 'options 8192cu rtw_power_mgnt=0' > /etc/modprobe.d/8192cu.conf
```

We can save some sdcard io by using a ramdisk for temporary storage:
```
echo 'tmpfs /tmp tmpfs defaults,noatime,mode=1777 0 0' >> /etc/fstab; cat /etc/fstab
```

Card identity
------------------------------

We want to change three file that give this card a unique identity:

* `machine-id` is a long chain of characters that should be unique for any machine in the world
* `machine-name` is a human friendly name for the machine (e.g. `ETHOSCOPE_001`)
* `hostname` is the name of the machine on the network (for the router) (e.g. e001)

```
cd /etc
nano machine-id machine-name hostname
```


Snapshot of the OS
----------------------------
At this point, it makes sense to back-up your work by making a snapshot of the OS:

Put the sd card in a computer.

Let us assume you have your root partition in `/mnt/root/` and boot in `/mnt/boot/`.
Your resulting snapshot will live be `/tmp/ethoscope_os_yyymmdd.tar.gz`.

```
cd /mnt/root/
cp -r ../boot/* ./boot/
sudo tar -zcvpf /tmp/ethoscope_os_yyyymmdd.tar.gz  *
rm ./boot/* -r
```
 

Burning your card
-----------------------------

After turning you pi off, you can also take the card and burn it to a reference image on a Linux PC.
To make a ref image, we replace `sdX` by the real drive name and do something like:


```
dd if=/dev/sdX | gzip > /home/quentin/Desktop/20160427_ethoscope.img.gz
```


This compressed the image on the fly, so it saves many many gigabytes.


