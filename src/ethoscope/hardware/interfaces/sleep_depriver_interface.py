__author__ = 'quentin'
from ethoscope.hardware.interfaces.lynx_motion import SimpleLynxMotionInterface
import time


class SleepDepriverInterface(SimpleLynxMotionInterface):
    def send(self, channel, dt=350,margin=10):
        """
        Sleep deprive an animal by rotating its tube.

        :param channel: The channel to use (i.e. the number of the servo)
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
                
                
class SleepDepriverInterfaceContinousRotation(SimpleLynxMotionInterface):
    def send(self, channel, dt=800):
        """
        Sleep deprive an animal rotating its tube.
        Uses continous rotation motor like the FEETECH FS90R Micro Continuous Rotation Servo
        
        :param channel: The channel to use (i.e. the number of the servo)
        :type channel: int
        :param dt: The time the stimulus should last
        :type dt: int
        """
        
        speed = 100

        half_dt = int(float(dt)/2.0)
        self.move_with_speed(channel, speed, half_dt)
        self.move_with_speed(channel, -speed, half_dt)
        self.move_with_speed(channel, 0, 100) #stop signal


    def move_with_speed(self, channel, speed=0, duration=1000):
        """
        Move a specified continous rotation servo to a speed for a certain time.

        :param channel: the number of the servo to be moved
        :type channel: int
        :param speed: the speed, between -100 and 100. The sign indicates the rotation direction (CW or CCW)
        :type speed: int
        :param duration: the time (ms) the stimulus should last
        :type duration: int
        :return:
        """
        
        if channel < 1:
            raise Exception("idx must be greater or equal to one")
        pulse = self._speed_to_pulse(speed)
        instruction = "#%i P%i T%i\r" % (channel - 1,pulse,duration)
        o = self._serial.write(instruction)
        time.sleep(float(duration)/1000.0)
        return o        


    def _speed_to_pulse(self, speed):
        """
        Used for FEETECH FS90R Micro Continuous Rotation Servo
        See datasheet at: https://cdn-shop.adafruit.com/product-files/2442/FS90R-V2.0_specs.pdf
        :param speed: the speed to be converted to pulse, -100 to +100
        :type angle: int
        :return: the pulse width
        :rtype: int
        """
        min_speed, max_speed = (-100, 100)
        min_pulse, mid_pulse, max_pulse = (700, 1500, 2300)
        
        if speed < min_speed or speed > max_speed:
            raise Exception("Speed value not valid: must be between %i and %i" % (min_speed, max_speed))
        
        pulse = (speed / 100.0) * (max_pulse - mid_pulse) + mid_pulse
        return int(pulse)

    def send(self, *args, **kwargs):
        self.move_with_speed(*args, **kwargs)

    def _warm_up(self):
        """
        Used to move all servos in a consecutive fashion
        Useful to check servo status and connections
        """
        for i in range(1, self._n_channels+1):
            self.move_with_speed(i, 50, 250)
            self.move_with_speed(i, 0, 250)
