This document explains how to setup an "ethoscope" **from a pre-written SD card image**.
It assumes, at least, some familiarity with Unix/Linux.
If you feel like building the SD card yourself, have a look [here](ethoscope_scratch.md) instead



Burning your SD card
=======================

1. Download the latest zipped image [here](https://imperialcollegelondon.app.box.com/ethoscope).
2. Unzip the image (it should inflate to 32GB).
3. Burn the image to a 32GB SD card (we typically use the 32G Samsung EVO).
You can use the `dd` command to burn your card as described [here](https://wiki.archlinux.org/index.php/USB_flash_installation_media#Using_dd)
4. Before you can use these card, there are exactly 3 files you need to change before you can use the card.
    * `/etc/machine-id`. This is a hexadecimal unique name for the machine. You can put some random string prefixed with a number. For instance `001ae2f5cee1`...
    * `/etc/machine-name`. This is the human friendly name of the machine. For instance ETHOSCOPE_001.
    * `/etc/hostname`. This is the name of the machine on the network. For example you could put e001.

Testing
================

The simple way to test your machine is to *plug a screen* add boot your new SD card.

