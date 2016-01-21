import logging
import time
import serial
from serial.tools import list_ports



class WrongSerialPortError(serial.SerialException):
    pass

class NoValidPortError(serial.SerialException):
    pass


class SimpleLynxMotionConnection(object):

    _baud = 115200

    # digital servos
    #_min_angle_pulse = (0.,800.)
    #_max_angle_pulse = (150.,2400.)

    # blue old school servo
    _min_angle_pulse = (0.,500.)
    _max_angle_pulse = (180.,2500.)


    def __init__(self, port=None):
        """
        Class to connect and abstract the SSC-32U Lynx Motion servo controller.
        It assumes a BAUD of 115200, which can be configured on the board as described in the
        `user manual (page 34) <http://www.lynxmotion.com/images/data/lynxmotion_ssc-32u_usb_user_guide.pdf>`_.

        :param port: the serial port to use. Automatic detection if ``None``.
        :type port: str.
        """


        logging.info("Connecting to Lynx motion serial port...")

        self._serial = None
        if port is None:
            self._port =  self._find_port()
        else:
            self._port = port

        self._serial = serial.Serial(self._port, self._baud, timeout=2)
        time.sleep(2)
        self._test_serial_connection()


    def _find_port(self):
        all_port_tuples = list_ports.comports()
        logging.info("listing serial ports")

        all_ports = set()
        for ap, _, _  in all_port_tuples:
            all_ports |= {ap}
            logging.info("\t%s", str(ap))

        for ap in list(all_ports):
            logging.info("trying port %s", str(ap))

            try:
                #here we use a recursive strategy to find the good port (ap).
                SimpleLynxMotionConnection(ap)
                return ap
            except (WrongSerialPortError, serial.SerialException):
                warn_str = "Tried to use port %s. Failed." % ap
                logging.warning(warn_str)
                pass

        logging.error("No valid port detected!. Possibly, device not plugged/detected.")
        raise NoValidPortError()

    def __del__(self):
        if self._serial is not None:
            self._serial.close()
#
    def _test_serial_connection(self):
        return

        # try:
            # If we fail to ping the port, this is a wrong port

            #self._serial.write("L\n")
#             r = self._serial.readline()
#             if not r:
#                 raise WrongSleepDepPortError
#             self.deprive(0)
#
#         except (OSError, serial.SerialException):
#             raise WrongSleepDepPortError
# #
#
#

    def _angle_to_pulse(self,angle):
        min_a, min_p = self._min_angle_pulse
        max_a, max_p = self._max_angle_pulse

        if angle > max_a:
            raise Exception("Angle too wide: %i" % angle)
        if angle < min_a:
            raise Exception("Angle too narrow: %i" % angle)

        slope = (max_p - min_p)/(max_a-min_a)
        pulse = min_p + angle * slope
        return pulse

    def move_to_angle(self,idx,angle=0.,time=1000):
        """
        Move a given servo to an angle in a given time.

        :param idx: the number of the servo to be moved
        :type idx: int
        :param angle: the angle (between 0 and 180) to move to
        :type angle: int
        :param time: the time it takes to go from the original angle to the new one (in ms)
        :type time: int
        :return:
        """

        if idx < 1:
            raise Exception("idx must be greater or equal to one")
        pulse = self._angle_to_pulse(angle)
        instruction = "#%i P%i T%i\r" % (idx - 1,pulse,time)
        o = self._serial.write(instruction)
        return o