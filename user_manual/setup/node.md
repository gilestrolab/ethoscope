This document explains how to setup a "node".
It assumes, at leat, some familiarity with Unix/Linux.

What is the "node"
======================

The node is a regular computer with an wireless connection does quite a few things:

* Runs a webserver in order to detect, start, stop,... devices (http://node)
* Runs a webserver to update server (http://node:8888)
* Runs a backup tool, that fetches data from all detected devices every 5min
* Runs an NTP server (so it used as the central clock of the platform)

The node simply orchestrate the platform, ** it does not analyse any data** tracking is performed, in real time, by each device.
Hence, if some devices are running and the node (or the network) shuts down, tracking will not be interrupted, and the data will be backed up on the node as soon as it is running again.

The hardware specification for the node can therefore be pretty standard, I would go with:

* CPU, anything made after 2014 should work (e.g. intel i3)
* RAM 4GB or more
* A descent hard-drive as you will back-up GB of data on it
* A wireless adaptor, ideally a PCI card, which should be more robust
* Also, check that the hardware can run Linux.

Installing a node
=======================

The OS
--------------

Once we have put our hands on some hardware, we need to install an operating system.
In our lab, we prefer Arch Linux based distributions such as [antergos](https://antergos.com/try-it).
They provide [installation instructions](https://antergos.com/wiki/install/create-a-working-live-usb/).
Once you boot on the USB stick, the installation wizard will take you through. I would go for a standard installation, with gnome as desktop manager.
As a user name, I would chose **node**.

Installing extra packages
----------------------------------

The first thing we will do after installation is install packages we need.

```sh
# update all packages
pacman -Syu --noconfirm

# tools for developers
pacman -S base-devel git gcc-fortran rsync wget fping --noconfirm --needed

# utilities
pacman -S ntp bash-completion --noconfirm --needed

#so we can set up a dns
pacman -S dnsmasq --noconfirm --needed

# pre-installing dependencies will save compiling time on python packages
pacman -S python2-pip python2-numpy python2-bottle python2-pyserial mysql-python python2-netifaces python2-cherrypy python2-futures --noconfirm --needed

# mariadb
pacman -S mariadb --noconfirm --needed

# setup Wifi dongle
pacman -S wpa_supplicant --noconfirm --needed
pacman -S libev --noconfirm --needed
```

Creating a git bare repo
---------------------------------
Here we setup a local git repo that should mirror https://github.com/gilestrolab/ethoscope.
This way, we can update devices using the node as a repo.

```sh
# a few variables
UPSTREAM_GIT_REPO=https://github.com/gilestrolab/ethoscope.git
LOCAL_BARE_PATH=/srv/git/ethoscope.git

mkdir -p /srv/git
git clone --bare $UPSTREAM_GIT_REPO $LOCAL_BARE_PATH
```

The node software
--------------------------------
After that we can clone ethoscope software and install the node part

```sh
# variables
TARGET_UPDATER_DIR=/opt/ethoscope_updater
TARGET_GIT_INSTALL=/opt/ethoscope-git

#Create a local working copy from the bare repo on node
echo 'Installing ethoscope package'
git clone $LOCAL_BARE_PATH $TARGET_GIT_INSTALL

cd $TARGET_GIT_INSTALL

# IMPORTANT this is if you want to work on the "dev" branch otherwise, you are using "master"
git checkout dev

cd $TARGET_GIT_INSTALL/node_src
# we install with pip
pip2 install -e .
```


Network
-----------------

The idea is to set up the network so that we can use, at the same time, a connection to the internet and the intranet (in house router).

First, we create a DNS mask.

```sh
# see how to setup router
NODE_IP=192.169.123.1

#configuring dns server:
echo "interface=$WL_INTERFACE" >/etc/dnsmasq.conf
echo "dhcp-option = 6,$NODE_IP" >> /etc/dnsmasq.conf
echo "no-hosts" >> /etc/dnsmasq.conf
echo "addn-hosts=/etc/host.dnsmasq" >> /etc/dnsmasq.conf
# so that http://node can be our homepage
echo "$NODE_IP    node" >> /etc/hosts.dnsmasq
```

In order to connect to the wireless interface, the simplest is to go in the network configuration interface.
Just click on the network icon on the top-right of the screen, select `ETHOSCOPE_WIFI`. The default password is `ETHOSCOPE_1234` (see [network instruction](network.md)).

System daemons
-----------------------------

We need to enable some utilities though `systemd`:

```sh

# Enable networktime protocol
systemctl start ntpd.service
systemctl enable ntpd.service

# Setting up ssh server
systemctl enable sshd.service
systemctl start sshd.service

# to host the bare git repo
systemctl start git-daemon.socket
systemctl enable git-daemon.socket

```

Our own daemons
--------------------

Now, we want to enable our own daemon/tools

```
# this is where our custo services are
cd $TARGET_GIT_INSTALL/scripts

cp ./ethoscope_node.service /etc/systemd/system/ethoscope_node.service
cp ./ethoscope_backup.service /etc/systemd/system/ethoscope_backup.service

systemctl daemon-reload

systemctl enable ethoscope_node.service
systemctl enable ethoscope_backup.service
```

In addition to the node services, we ant to run the update daemon.
It is important that the update server is copied out of the git repository. This way, the update does *not* update itself.

```sh
UPDATER_LOCATION_IN_GIT=scripts/ethoscope_updater
cp $TARGET_GIT_INSTALL/$UPDATER_LOCATION_IN_GIT $TARGET_UPDATER_DIR -r
cd $TARGET_UPDATER_DIR
cp ethoscope_update_node.service /etc/systemd/system/ethoscope_update_node.service

systemctl daemon-reload
systemctl enable ethoscope_update_node.service
```


What is next
-----------------------
In order to check things:

* reboot the computer
* open firefox
* test the local server at http://0.0.0.0
* test the local server at http://192.169.123.1 (will fail until your network is configured)
* test the update server http://192.169.123.1:8888
* test the dns mask http://node



 



