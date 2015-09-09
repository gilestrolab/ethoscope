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
Animals lay on individual regions of an experimental arena (typically 3d printed):

IMAGE HERE


Hardware is available on our `hardware repository <https://github.com/PolygonalTree/ethoscope_hardware>`_.


Node
-------

The *Node* is a regular computer (preferably) connected to the internet.
It runs a front-end bottle server allowing users to send instructions (start tracking, record video, update ...) to each devices.
It also synchronise regularly data from all devices on individual local files.



Communication between node and devices
======================================

IMAGE HERE



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



