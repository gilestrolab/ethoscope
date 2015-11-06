"""

Ethoscope is a platform developed at `Gilestro lab <http://lab.gilest.ro/>`_.
It provide an integrated set of tools to acquire behavioural data on small animals and build feed back modules to interact with them in real time.
By design, it is extremely modular (both on the hardware and software side).
This project uses, as much as possible, open hardware and software.


Hardware
========

Devices
--------
Devices are enhanced Raspeberry Pi micro-computers with a camera and a wireless dongle.
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



Local tracking example
=======================
A very simple example of how to use the API to perform local tracking.
If you want to run this code yourself, you can download the `test video <http://gilestrolab.github.io/ethoscope/data/test_video.mp4>`_.

>>> # We import all the bricks from ethoscope package
>>> from ethoscope.core.monitor import Monitor
>>> from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
>>> from ethoscope.utils.io import SQLiteResultWriter
>>> from ethoscope.hardware.input.cameras import MovieVirtualCamera
>>> from ethoscope.drawers.drawers import DefaultDrawer
>>>
>>> # You can also load other types of ROI builder. This one is for 20 tubes (two columns of ten rows)
>>> from ethoscope.roi_builders.target_roi_builder import SleepMonitorWithTargetROIBuilder
>>>
>>> # change these three variables according to how you name your input/output files
>>> INPUT_VIDEO = "test_video.mp4"
>>> OUTPUT_VIDEO = "/tmp/my_output.avi"
>>> OUTPUT_DB = "/tmp/results.db"
>>>
>>> # We use a video input file as if it was a "camera"
>>> cam = MovieVirtualCamera(INPUT_VIDEO)
>>>
>>> # here, we generate ROIs automatically from the targets in the images
>>> roi_builder = SleepMonitorWithTargetROIBuilder()
>>> rois = roi_builder.build(cam)
>>> # Then, we go back to the first frame of the video
>>> cam.restart()
>>>
>>> # we use a drawer to show inferred position for each animal, display frames and save them as a video
>>> drawer = DefaultDrawer(OUTPUT_VIDEO, draw_frames = True)
>>> # We build our monitor
>>> monitor = Monitor(cam, AdaptiveBGModel, rois)
>>>
>>> # Now everything ius ready, we run the monitor with a result writer and a drawer
>>> with SQLiteResultWriter(OUTPUT_DB, rois) as rw:
>>>     monitor.run(rw,drawer)


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



