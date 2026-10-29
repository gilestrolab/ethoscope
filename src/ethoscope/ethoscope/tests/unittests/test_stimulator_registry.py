"""
The stimulator registry is the one list of stimulator classes.

The device offers the classes in it as the "interactor" options, resolves a
start request's interactor by name through it, and MultiStimulator builds the
stimulators of a sequence from it. MultiStimulator once kept a list of its own
that lacked ComposedStimulator, the only class the node's "Add Stimulator"
creates, so any run with two or more stimulators delivered nothing.
"""

from ethoscope.control.tracking import ControlThread
from ethoscope.stimulators.composed_stimulator import ComposedStimulator
from ethoscope.stimulators.registry import STIMULATOR_CLASSES, STIMULATOR_REGISTRY
from ethoscope.stimulators.stimulators import DefaultStimulator


def test_the_device_offers_exactly_the_registry():
    offered = ControlThread._option_dict["interactor"]["possible_classes"]
    assert offered == STIMULATOR_CLASSES


def test_default_stimulator_stays_the_default():
    # Reason: the first possible class is what a start request without an
    # interactor gets. It must deliver nothing.
    assert STIMULATOR_CLASSES[0] is DefaultStimulator


def test_registry_is_keyed_by_class_name():
    assert STIMULATOR_REGISTRY == {c.__name__: c for c in STIMULATOR_CLASSES}
    assert STIMULATOR_REGISTRY["ComposedStimulator"] is ComposedStimulator


def test_every_registered_class_resolves_from_a_start_request():
    for cls in STIMULATOR_CLASSES:
        Class, kwargs = ControlThread._parse_one_user_option(
            ControlThread,
            "interactor",
            {"interactor": {"name": cls.__name__, "arguments": {"a": 1}}},
        )
        assert Class is cls
        assert kwargs == {"a": 1}
