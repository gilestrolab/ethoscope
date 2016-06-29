__author__ = 'quentin'
from ethoscope.hardware.interfaces.lynx_motion import SimpleLynxMotionInterface


class SleepDepriverInterface(SimpleLynxMotionInterface):
    def send(self,channel, dt=350,margin=10):
        """
        Sleep deprive an animal by rotating its tube.

        :param channel: The chanel to use (i.e. the number of the servo)
        :type channel: int
        :param dt: The time it takes to go from 0 to 180 degrees (in ms)
        :type dt: int
        :param margin: the number of degree to pad rotation. eg 5 -> rotation from 5 -> 175
        :type dt: int
        """

        half_dt = int(float(dt)/2.0)
        self.move_to_angle(channel, self._max_angle_pulse[0]-margin,half_dt)
        self.move_to_angle(channel, self._min_angle_pulse[0]+margin,dt)
        self.move_to_angle(channel, self._max_angle_pulse[0]-margin,dt)
        self.move_to_angle(channel, 0,half_dt)


    def _warm_up(self):
        for r in range(0,3):
            for i in range(1, 1 + self._n_channels):
                self.send(i)