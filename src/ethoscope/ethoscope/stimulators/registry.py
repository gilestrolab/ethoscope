"""
The stimulator classes an ethoscope can be asked to run, in one place.

The device offers these as its "interactor" options and resolves a start
request's interactor by name among them (control/tracking.py), and
MultiStimulator builds the stimulators of a sequence from the same list.
MultiStimulator used to keep a list of its own, which lacked ComposedStimulator,
the only class the node's "Add Stimulator" creates: every run with two or more
stimulators then delivered nothing.
"""

from ethoscope.stimulators.composed_stimulator import ComposedStimulator
from ethoscope.stimulators.multi_stimulator import MultiStimulator
from ethoscope.stimulators.odour_stimulators import (
    DynamicOdourSleepDepriver,
    MiddleCrossingOdourStimulator,
    MiddleCrossingOdourStimulatorFlushed,
)
from ethoscope.stimulators.optomotor_stimulators import OptoMidlineCrossStimulator
from ethoscope.stimulators.sleep_depriver_stimulators import (
    AGO,
    ExperimentalSleepDepStimulator,
    MiddleCrossingStimulator,
    OptomotorSleepDepriver,
    OptoSleepDepriver,
    SleepDepStimulator,
    mAGO,
)
from ethoscope.stimulators.sleep_restriction_stimulators import (
    SimpleTimeRestrictedStimulator,
    mAGOSleepRestriction,
)
from ethoscope.stimulators.stimulators import DefaultStimulator

# The first class is the default: what a start request without an interactor
# gets. It must be one that delivers nothing.
STIMULATOR_CLASSES = [
    DefaultStimulator,
    ComposedStimulator,
    SleepDepStimulator,
    OptomotorSleepDepriver,
    MiddleCrossingStimulator,
    ExperimentalSleepDepStimulator,
    DynamicOdourSleepDepriver,
    OptoMidlineCrossStimulator,
    OptoSleepDepriver,
    MiddleCrossingOdourStimulator,
    MiddleCrossingOdourStimulatorFlushed,
    mAGO,
    AGO,
    mAGOSleepRestriction,
    SimpleTimeRestrictedStimulator,
    MultiStimulator,
]

STIMULATOR_REGISTRY = {cls.__name__: cls for cls in STIMULATOR_CLASSES}
