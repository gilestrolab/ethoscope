This document explains how to setup an "ethoscope" **from a pre-written SD card image**.
It assumes, at least, some familiarity with Unix/Linux.
If you feel like building the SD card yourself, have a look [here](ethoscope_scratch.md) instead.
You may need to make your own card if you decide to use a different SD card (e.g. if it is smaller in size).



Create your SD card
=======================

You can basically follow [these instructions](https://archlinuxarm.org/platforms/armv7/broadcom/raspberry-pi-2),
but replace the latest stable ArchLinux by [our custom OS snapshot](https://imperialcollegelondon.app.box.com/ethoscope).

So, to summarise, **as root** (not sudo) do:

Get the OS:

```
cd /tmp/
wget https://imperialcollegelondon.box.com/shared/static/molfbz54uf0l7zo4za5y5w6sz1rw2bod.gz
```

We make the partition table:

```
SD_CARD=/dev/sdi
echo "o
p
n
p
1

+100M
t
c
n
p
2


w"| fdisk $SD_CARD
```

Format partitions:
```
mkfs.vfat ${SD_CARD}1
mkdir boot
mount ${SD_CARD}1 boot
mkfs.ext4 ${SD_CARD}2
mkdir root
mount ${SD_CARD}2 root
```
Transfer OS to partitions:
```
bsdtar -xpf 20160427_ethoscope_root.tar.gz -C root
sync
mv root/boot/* boot
umount boot root
```
Then you want so change the ID of the machine in the card, so rewrite:
* `/etc/machine-id`. This is a hexadecimal unique name for the machine. You can put some random string *prefixed with a number*. For instance `001ae2f5cee1`...
* `/etc/machine-name`. This is the human friendly name of the machine. For instance ETHOSCOPE_001.
* `/etc/hostname`. This is the name of the machine on the network. For example you could put e001.



Burning your SD card
=======================

*This method is only advice if you have exactly the same sd card model as the one used to make the image.*

1. Download the latest zipped image [here](https://imperialcollegelondon.app.box.com/ethoscope).
2. Unzip the image (it should inflate to 32GB). `gzip -d  yyyymmdd_ethoscope.img.gz`
3. Burn the image to a 32GB SD card (we typically use the 32G Samsung EVO).
You can use the `dd` command to burn your card as described [here](https://wiki.archlinux.org/index.php/USB_flash_installation_media#Using_dd).
For instance `dd if=/home/quentin/Desktop/yyyymmdd_ethoscope.img of=/dev/sdX bs=64K`.
Be **very careful with dd. You want to write on the write drive!**
4. Change the id of the card as explained above. 

Testing
================

The simple way to test your machine is to *plug a screen* add boot your new SD card.

