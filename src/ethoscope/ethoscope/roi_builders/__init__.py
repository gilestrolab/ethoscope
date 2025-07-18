"""
This module define modular *ROI builders*. These objects take an image (or camera stream) and use them to construct a list of :class:`~ethoscope.core.roi.ROI`s.
This is generally performed by a combination of parameters and automatic detection algorithms.
In order to add a new ROI builder, one would make a new module (python file) in which a class deriving from :class:`~ethoscope.roi_builders.roi_builders.BaseROIBuilder` is defined.
This will typically be done when new arenas (hardware components) is defined.

"""

__author__ = 'quentin'

from . import roi_builders
