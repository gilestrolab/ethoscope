_author__ = 'quentin'
from ethoscope.hardware.interfaces.lynx_motion import SimpleLynxMotionInterface
from ethoscope.hardware.interfaces.sleep_depriver_interface import SleepDepriverInterface
import time

class OdourDelivererInterface(SimpleLynxMotionInterface):
    _positions_to_angles = {1: -20,
                            2: 20,
                            3: 0}
    _extra_move = 0.25
    _dt = 750

    def __init__(self,*args, **kwargs):
        self._current_pos = [3] * 10
        super(OdourDelivererInterface,self).__init__(*args,**kwargs)

    def _warm_up(self):
        for i in range(1, 1 + self._n_channels):
            for k in range(1, 4):
                self.send(i, k)

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
        #we first move a bit further:
        if pos !=3:
            self.move_to_angle(channel, angle + angle * self._extra_move,  self._dt)
        else:
            current_angle = self._positions_to_angles[self._current_pos[channel-1]]
            pos_to_go = 0 - current_angle * self._extra_move
            self.move_to_angle(channel, pos_to_go, self._dt)
        self.move_to_angle(channel, angle, self._dt)
        self._current_pos[channel-1] = pos

class OdourDepriverInterface(OdourDelivererInterface):

    def send(self, channel, stimulus_duration=5.0):
        self._move_to_pos(channel, 1)
        time.sleep(stimulus_duration)
        self._move_to_pos(channel, 2)

    def _warm_up(self):
        for i in range(1, 1 + self._n_channels):
            self.send(i)