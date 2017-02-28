This document explains how to setup a wireless router for the Ethoscope platform.

Router
==============
The idea is to connect many devices and a unique note to a single wireless network.
In order to do that, we can work with a router

Configuration
================
Here, we will give a default configuration that matches the rest of the instalation instruction. 
If you know what you are doing, you can of course change these. This can be helpfull if say you wanted to have sevreal networks in the same room.

Wireless configuration 
-------------------------------
* The **name of the network** is `ETHOSCOPE_WIFI`
* The **password** is `ETHOSCOPE_1234`

DHCP
--------

* **start ip** is `192.169.123.6`
* **end ip** is `192.169.123.250`
* **default gateway** is `192.169.123.254`
A **very important thing** is to reserve the ip `192.169.123.1` to the node.
in order to do that, you will need the MAC ip of the **wireless interface** of the node.
**DO NOT PUT THE MAC IP OF THE ETHERNET INTERFACE**


In order to get it, you can use `ip link` on the node. You will get something like:

```sh
$ ip link
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT group default 
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
2: enp3s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP mode DEFAULT group default qlen 1000
    link/ether 10:bf:48:ba:d3:84 brd ff:ff:ff:ff:ff:ff
3: wlp5s1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP mode DORMANT group default qlen 1000
    link/ether 00:26:5a:e6:47:f1 brd ff:ff:ff:ff:ff:ff
```
In this exanple, my wireless interface is `wlp5s1` (all wifi interfaces start with `wl`), then my MAC address is `00:26:5a:e6:47:f1`

As long as you know what you are doing, you can also use a second ethernet card, instead of a a wireless connection to connect to the intranet. This will make scaning and backups faster.

