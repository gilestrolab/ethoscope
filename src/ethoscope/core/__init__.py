"""
This module is the core of the `ethoscope`.
It defines the building bricks at the basis of the package.

Overview:

* :class:`~ethoscope.core.monitor.Monitor` is the most important class. It glues together all the other elements of the package in order to perform (video tracking, interacting , data writing and drawing).
* :class:`~ethoscope.core.tracking_unit.TrackingUnit` are internally used by monitor. They forces to conceptually treat each ROI independently.
* :class:`~ethoscope.core.roi.ROI` formalise and facilitates the use of Region Of Interests.
* :mod:`~ethoscope.core.variables` are custom types of variables that result from tracking and interacting.
* :class:`~ethoscope.core.data_point.DataPoint` stores efficiently Variables.

"""


__author__ = 'quentin'


from . import monitor
from . import tracking_unit
from . import variables
from . import roi
