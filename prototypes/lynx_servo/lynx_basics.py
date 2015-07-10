__author__ = 'quentin'

import serial
from serial.tools import list_ports
import time
import logging

#
class NoValidPortError(serial.SerialException):
    pass
class WrongSleepDepPortError(serial.SerialException):
    pass

class SimpleLynxMotionInterface(object):
    _baud = 115200
    _min_angle_pulse = (0.,800.)
    _max_angle_pulse = (150.,2400.)


    def __init__(self, port=None):

        self._serial = None
#
        if port is None:
            self._port =  self._find_port()
        else:
            self._port = port
#
        self._serial = serial.Serial(self._port, self._baud, timeout=2)
        time.sleep(2)
#
        self._test_serial_connection()
#
    def _find_port(self):
        all_ports = list_ports.comports()
        logging.info("listing serial ports")
        for ap, _, _  in all_ports:
            logging.info("\t%s", str(ap))
        for ap, _, _  in all_ports:
            logging.info("trying port %s", str(ap))
            try:
                #here we use a recursive strategy to find the good port (ap).
                SimpleLynxMotionInterface(ap)
                return ap
            except (WrongSleepDepPortError, serial.SerialException):
                pass
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
#     def deprive(self, channel):
#         cmd = "M %i\n" % (channel)
#         self._serial.write(cmd)
#         logging.info("Sending command to SD: %s" % cmd)
#
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

    def move_to_angle(self,idx,angle=0,time=1000):
        pulse = self._angle_to_pulse(angle)
        instruction = "#%i P%i T%i\r" % (idx,pulse,time)
        o = self._serial.write(instruction)
        return o




class SleepDepriver(SimpleLynxMotionInterface):
    def deprive(self,idx, dt=500):
        self.move_to_angle(idx, self._min_angle_pulse[0],dt)
        time.sleep(dt/1000.0)
        self.move_to_angle(idx, self._max_angle_pulse[0],dt)
        time.sleep(dt/1000.0)

logging.getLogger().setLevel(logging.INFO)
sdep = SleepDepriver()
print sdep.deprive(16)


#
# import serial
# import time
# from serial.tools import list_ports
#
#
#     # self._port =  self._find_port()
#     #     else:
#     #         self._port = port
# # port = "/dev/ttyUSB1"
# # baud = 115200
# #baud = 9600
# # pulse=1500
# #pulse_back=2500
# serial = serial.Serial(port, baud, timeout=2)
#
#
# def send_instruction(serial,pulse, time=1000, servo=16):
#
#     instruction = "#%i P%i T%i\r" % (servo,pulse,time)
#     print instruction
#     serial.write(instruction)
#
#
#
#
# for p in range(800,2500, 2):
#     send_instruction(serial, p)
#     time.sleep(.01)
#
#
#
#
# t = 3000.0
# send_instruction(serial,800,time=1000)
# send_instruction(serial,800,time=100,servo=17)
# time.sleep(1.0)
# send_instruction(serial,2400,time=t)
# time.sleep(1.0)
# send_instruction(serial,1600,time=100,servo=17)
#
# # for i in range(32):
# #     serial.write(instruction)
# #     time.sleep(1)
#     #instruction = "#%i P%i \r" % (i +1,pulse_back)
#     #print instruction
#     #serial.write(instruction)
#     #time.sleep(1)
# serial.close()
#
#
#

ser.write("Q\r")
for i in range(100):
    print ser.read()