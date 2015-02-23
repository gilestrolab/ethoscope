Setup of dev version
==========================

This is a document to explain the actual set-up of our development version for
sleep monitors and sleep deprivers network. 

Hardware
----------

We have a this hardware parts:

1. Node = Rpi with Node software on it. This is connected to two different
networks through Ethernet and wifi.
2. Device = Rpi with arena and Pi Noir camera. This is connected to one network
by wifi means.
3. Router = it creates the wifi subnetwork
4. SSD = Node is connected to this drive and storage the data from devices there.
5. PSU = Usb power supply for Node, device/s and router.

Software
----------

The packages `psv` and `psvnode` are installed in devices and node, respectively.
Packages are installed using `$ pip2 install -e .`

Connecting to Node
-----------------------

To connect to Node you can use one of the two networks to which it is attached,
is recommended to use the wifi.

Node has a fixed IP inside the wifi network, this fixed IP is a configured 
reserved IP address in the router. 
wifi reserved address = `192.169.123.1`

To connect to Node with ssh: `ssh root@192.169.123.1` or `ssh node@192.169.123.1`

If you prefer to use the Ethernet you need to know the assigned address by the
external provider. 

Connecting to a Device
------------------------

The devices are only connected to the wifi subnetwork so this is the only way to
access to them. 
The IP address is assigned dynamically and can be discovered through node server
software. 
Other way is to check the attached devices inside the router software
Once you have the ip: ssh root@192.169.123."ip" or ssh psv@192.169.123."ip"

Connecting to router
------------------------

The default and fixed IP of the router is `192.169.123.254`, you can access to it
with a browser in port `:80`.
User name and pass are both `admin`.

Updates in the software
------------------------

In order to update the devices and node in this version you need to have internet
access in the node through the ethernet cable. 

The node has installed a bare repository that is a mirror from the one in github.
This bare repo is the one that use the own node and devices to update itself.
It is installed inside `/var/pySolo-Video.git`.

The node has another local repository (not bare) which contains the actual data, 
it is synchronised with the bare repository in `/var/` (not with Github). This is found 
in `/home/node/pySolo-Video`

The devices has another copy of the repository in the node inside `/var/`. This local
repo is inside `/home/psv/pySolo-Video`

**Steps to update repos and devices:**

1. Connect to Node and as root `# cd /var/pySolo-Video.git` 
2. update the bare repo with `# git fetch -q --all -p`
3. Go to local repository in node `# cd /home/psv/pySolo-Video` and `git pull`
4. Connect to device `cd /home/psv/pySolo-Video` and `git pull`.
5. Repeat 4 for every device that needs to be updated.
6. Update is Done.





