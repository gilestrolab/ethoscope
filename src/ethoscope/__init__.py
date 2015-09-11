"""

Ethoscope is a platform developed at `Gilestro lab <http://lab.gilest.ro/>`_.
It provide an integrated set of tools to acquire behavioural data on small animals and build feed back modules to interact with them in real time.
By design, it is extremely modular (both on the hardware and software side).
This project uses, as much as possible, open hardware and software.


Hardware
========

Devices
--------
Devices are enhanced raspeberry pi micro-computers with a camera and a wireless dongle.
Animals lay on individual regions of an experimental arena (typically 3d printed).
Each device is a *standalone* video tracker that will preform video acquisition, real-time tracking, and data saving.

This next figure shows the inside of a device (A), and an example of frame acquired with one of such devices(B).
The left and right part of the frame shown in B represent the same arena acquired in light or dark conditions, respectively.

.. image:: /img/device.jpg

Hardware is available on our `hardware repository <https://github.com/PolygonalTree/ethoscope_hardware>`_.


Node
-------

The *Node* is a regular computer (preferably) connected to the internet.
Its purpose is to send instruction to devices. Form instance, it can requests devices to start, stop, update...
It also synchronise regularly data (MySQL) from all devices on individual local files (SQLite).
It runs a front-end bottle server allowing users to send instructions (start tracking, record video, update ...) to each devices.
The user interface can be used directly on the node or connected to with any web browsing device connected on the network (e.g. a phone).



Communication between node and devices
======================================
The video tracking platform contains *multiple devices* and a *single node*.
Communication between node and devices is done through a private local wireless network.
Local network is also used by devices to synchronise their clocks with the node's.
Optionally, experimental data saved on the node can be mirrored on a remote drive.

This is an overview of the task performed by device and node as well as how they connect to each other.

.. image:: /img/platform.png



Software
========

IMAGE HERE



*Post hock* data analysis
==========================

A large amount of data can be generated thanks to ethoscope.
In order to render the analysis (visualisation, summaries, statistics ...)  straightforward and flexible,
we developed an ``R`` package named `rethomics <https://github.com/gilestrolab/rethomics>`_.

"""


import core
import hardware
import interactors
import roi_builders
import trackers
import utils
import web_utils



