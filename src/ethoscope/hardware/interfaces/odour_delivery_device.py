_author__ = 'quentin'
from ethoscope.hardware.interfaces.lynx_motion import SimpleLynxMotionInterface
from ethoscope.hardware.interfaces.sleep_depriver_interface import SleepDepriverInterface
import time

class OdourDelivererInterface(SimpleLynxMotionInterface):
    _positions_to_angles = {1: -25,
                            2: 20,
                            3: 0}
    _dt = 250

    def __init__(self,*args, **kwargs):
        self._current_pos = [3] * 10
        super(OdourDelivererInterface,self).__init__(*args,**kwargs)

    def _warm_up(self):
        for i in range(1, 1 + self._n_channels):
            for k in range(3):
                self.send(i, k + 1)

    def send(self,channel, pos):
        return self._move_to_pos(channel, pos)

    def _move_to_pos(self,channel, pos):
        """
        TUrns the valve to one of three position {1,2,3}

        :param channel: The channel to use (i.e. the number of the servo)
        :typechannel: int
        :param pos: The position to stay in
        :type pos: int
        """

        angle = self._positions_to_angles[pos]
        self.move_to_angle(channel, angle, self._dt)

class OdourDepriverInterface(OdourDelivererInterface):

    def send(self, channel, stimulus_duration=5.0):
        self._move_to_pos(channel, 1)
        time.sleep(stimulus_duration)
        self._move_to_pos(channel, 2)

    def _warm_up(self):
        for i in range(self._n_channels):
            self.send(i + 1)


class OdourDelivererFlushedInterface(OdourDelivererInterface):

    def send(self, channel, stimulus_duration=5.0, flush_duration=30.0):
        self._move_to_pos(channel, 1)
        time.sleep(stimulus_duration)
        self._move_to_pos(channel, 2)
        time.sleep(flush_duration)
        self._move_to_pos(channel, 3)

    def _warm_up(self):
        for i in range(self._n_channels):
            self.send(i + 1, 1,3)
