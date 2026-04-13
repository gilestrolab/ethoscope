import logging
import time

import serial

from ethoscope.hardware.interfaces.interfaces import SimpleSerialInterface


class WrongSerialPortError(Exception):
    pass


class NoValidPortError(Exception):
    pass


class OptoMotor(SimpleSerialInterface):
    _baud = 115200
    _n_channels = 20

    def __init__(self, port=None, *args, **kwargs):
        """
        TODO

        :param port: the serial port to use. Automatic detection if ``None``.
        :type port: str.
        :param args: additional arguments
        :param kwargs: additional keyword arguments
        """

        logging.info("Connecting to GMSD serial port...")

        self._serial = None
        if port is None:
            self._port = self._find_port()
        else:
            self._port = port

        # Reason: ethoscopes without an attached Arduino/mAGO module must
        # still be able to start tracking when the default stimulator
        # (ComposedStimulator) binds this class. Without the guard, a
        # missing port propagates a SerialException up through
        # HardwareConnection → _set_tracking_from_scratch and crashes the
        # tracking start. See gilestrolab/ethoscope#216.
        try:
            self._serial = serial.Serial(self._port, self._baud, timeout=2)
            time.sleep(2)
            self._test_serial_connection()
        except (serial.SerialException, FileNotFoundError, OSError) as e:
            logging.warning(
                "Could not open OptoMotor serial port %r: %s. "
                "No module detected — stimulator commands will be dropped.",
                self._port,
                e,
            )
            self._serial = None
            return

        super().__init__(*args, **kwargs)

    def _ensure_serial(self):
        """Return True if a serial connection is available.

        Used by activate/pulse_train to silently drop commands when the
        device has no module attached, instead of raising AttributeError
        on every instruction.
        """
        return self._serial is not None

    def activate(self, channel, duration, intensity):
        """
        Activates a component on a given channel of the PWM controller

        :param channel: the chanel idx to be activated
        :type channel: int
        :param duration: the time (ms) the stimulus should last for
        :type duration: int
        :param intensity: duty cycle, between 0 and 1000.
        :type intensity: int
        :return:
        """

        if channel < 0:
            raise Exception("chanel must be greater or equal to zero")

        if not self._ensure_serial():
            return 0

        duration = int(duration)
        intensity = int(intensity)
        instruction = b"P %i %i %i\r\n" % (channel, duration, intensity)
        o = self._serial.write(instruction)
        return o

    def pulse_train(self, channel, on_ms, off_ms, cycles):
        """
        Sends a pulse train command to the LED on the given channel.

        Args:
            channel (int): The channel index.
            on_ms (int): ON duration per pulse in milliseconds.
            off_ms (int): OFF duration per pulse in milliseconds.
            cycles (int): Number of ON/OFF cycles.
        """
        if channel < 0:
            raise Exception("channel must be greater or equal to zero")

        if not self._ensure_serial():
            return 0

        on_ms = int(on_ms)
        off_ms = int(off_ms)
        cycles = int(cycles)
        instruction = b"W %i %i %i %i\r\n" % (channel, on_ms, off_ms, cycles)
        o = self._serial.write(instruction)
        return o

    def send(
        self,
        channel,
        duration=10000,
        intensity=1000,
        on_ms=None,
        off_ms=None,
        cycles=None,
    ):
        """
        Route to the appropriate command based on kwargs.

        If on_ms, off_ms, and cycles are provided, sends a pulse train (W command).
        Otherwise sends a simple activate pulse (P command).

        Args:
            channel (int): The channel index.
            duration (int): Duration for simple pulse in ms.
            intensity (int): Duty cycle for simple pulse (0-1000).
            on_ms (int, optional): ON duration per pulse for pulse train.
            off_ms (int, optional): OFF duration per pulse for pulse train.
            cycles (int, optional): Number of cycles for pulse train.
        """
        if on_ms is not None and off_ms is not None and cycles is not None:
            self.pulse_train(channel, on_ms, off_ms, cycles)
        else:
            self.activate(channel, duration, intensity)

    def _warm_up(self):
        """
        Send a warm-up command that will test all channels
        """
        for i in range(self._n_channels):
            self.send(i, duration=1000)
            time.sleep(1.000)  # s
