"""
HardwareConnection.interrogate(): what the attached module says it is.

ComposedStimulator picks its ROI-to-channel map from the module's reported
capabilities. It called interrogate() on the HardwareConnection, which had no
such method, so the call always failed and the default map was always used:
a 20-LED module (MODULE 4) never had its 20-LED map applied.
"""

import threading
import time

import pytest

from ethoscope.hardware.interfaces.interfaces import HardwareConnection
from ethoscope.stimulators.composed_stimulator import ComposedStimulator

MODULE_4_REPLY = {
    "version": "FW-1.5;HW-11",
    "module": {"name": "LED Optogenetic Module", "type": 4},
    "capabilities": {"motors": 0, "valves": 0, "leds": 20},
}


class FakeModule:
    """Stands in for OptoMotor: records what it is sent and answers ``T``."""

    send_duration = 0.0

    def __init__(self):
        self.sent = []
        self.interrogations = 0
        self.sending = threading.Event()
        self.interrogated_while_sending = False

    def interrogate(self):
        self.interrogations += 1
        self.interrogated_while_sending = self.sending.is_set()
        return dict(MODULE_4_REPLY)

    def send(self, **kwargs):
        self.sending.set()
        time.sleep(self.send_duration)
        self.sent.append(kwargs)
        self.sending.clear()


class SlowFakeModule(FakeModule):
    send_duration = 0.3


class SilentModule(FakeModule):
    """A module that does not answer ``T`` (no port, old firmware, bad reply)."""

    def interrogate(self):
        self.interrogations += 1
        raise SyntaxError("unexpected EOF while parsing")


class NoInterrogation:
    """An interface with no notion of interrogation at all."""

    def send(self, **kwargs):
        pass


@pytest.fixture
def connect():
    connections = []

    def _connect(interface_class):
        hc = HardwareConnection(interface_class)
        connections.append(hc)
        return hc

    yield _connect
    for hc in connections:
        hc.stop()
        hc.join(timeout=2)


def _wait_for(condition, timeout=2.0):
    deadline = time.time() + timeout
    while not condition():
        if time.time() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.01)


def test_returns_the_module_reply(connect):
    hc = connect(FakeModule)
    assert hc.interrogate() == MODULE_4_REPLY


def test_the_module_is_asked_once(connect):
    # One stimulator is built per ROI, and every one of them asks.
    hc = connect(FakeModule)
    for _ in range(20):
        hc.interrogate()
    assert hc._interface.interrogations == 1


def test_a_module_that_does_not_answer_gives_an_empty_reply(connect):
    hc = connect(SilentModule)
    assert hc.interrogate() == {}
    # Asked once: every ROI of a run then gets the same (default) map.
    assert hc.interrogate() == {}
    assert hc._interface.interrogations == 1


def test_an_interface_without_interrogation_gives_an_empty_reply(connect):
    hc = connect(NoInterrogation)
    assert hc.interrogate() == {}


def test_instructions_are_still_delivered(connect):
    hc = connect(FakeModule)
    hc.interrogate()
    hc.send_instruction({"channel": 1, "duration": 1000})
    _wait_for(lambda: hc._interface.sent == [{"channel": 1, "duration": 1000}])


def test_never_interrogates_while_a_command_is_being_sent(connect):
    # Reason: send() and interrogate() write to the same serial port. A command
    # written between T and its reply would corrupt the reply.
    hc = connect(SlowFakeModule)
    hc.send_instruction({"channel": 1, "duration": 1000})
    _wait_for(hc._interface.sending.is_set)
    hc.interrogate()
    assert not hc._interface.interrogated_while_sending
    assert hc._interface.sent == [{"channel": 1, "duration": 1000}]


def test_composed_stimulator_reads_the_module_through_the_connection(connect):
    # The symptom: on a 20-LED module the LED map stayed the 10-LED default.
    hc = connect(FakeModule)
    stim = ComposedStimulator(hc, action_type="led_pulse")
    assert stim._roi_to_channel == {n: n - 1 for n in range(1, 21)}
