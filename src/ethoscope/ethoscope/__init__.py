"""
Ethoscope is a platform developed at `Gilestro lab <http://lab.gilest.ro/>`_.
It provide an integrated set of tools to acquire behavioural data on small animals and build feed back modules to interact with them in real time.
A description of the whole system is available on its `website <http://gilestrolab.github.io/ethoscope/>`_
The documentation herein describes the ethoscope python package, which is the core of the device software.
It is intended for programmers who want to contribute to development, and assumes familiarity with ``python`` programming language.

The first purpose of the package is to provide biologists with a modular API to acquire videos, track animals in real time, feed back to
deliver stimuli upon specific triggers, annotate video frames with tracking information and save data in a consistent format (database).
In addition, is implements a webserver that can run a a daemon and performs actions upon POST requests.

Installation
============

Probably you want to work on a virtual environment.
Then you want to install OpenCV (which is an external library -- i.e. not ip pip).
Afterwards, you can clone the repository (the branch ``dev`` being the development version) and run:

```
cd src
pip install -e .[dev]
```


Core API
======================
This diagram represents the core of the API in UML:

.. image:: /img/uml_diagram.svg

The classes prefixed with ``Base`` are abstract, and several derived classes are already implemented for most of them, but more can be done
in the prospect of achieving modularity.


Local tracking example
=======================

Since the API is modular, it can be used to simply perform of line tracking from a video file.
Here is a very simple example.
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


from . import core
from . import hardware
from . import stimulators
from . import roi_builders
from . import trackers
from . import utils
from . import web_utils



