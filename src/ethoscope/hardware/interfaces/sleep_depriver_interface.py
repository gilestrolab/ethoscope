__author__ = 'quentin'

import serial
from serial.tools import list_ports
import time
import logging
import multiprocessing

from ethoscope.hardware.interfaces.interfaces import BaseInterface

class NoValidPortError(serial.SerialException):
    pass
class WrongSleepDepPortError(serial.SerialException):
    pass

class SimpleLynxMotionConnection(object):
    _baud = 115200
    _min_angle_pulse = (0.,800.)
    _max_angle_pulse = (150.,2400.)


    def __init__(self, port=None):
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
            except (WrongSleepDepPortError, serial.SerialException):
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
        if idx < 1:
            raise Exception("idx must be greater or equal to one")
        pulse = self._angle_to_pulse(angle)
        instruction = "#%i P%i T%i\r" % (idx - 1,pulse,time)
        o = self._serial.write(instruction)
        return o

class SleepDepriverConnection(SimpleLynxMotionConnection):
    def __init__(self,*args, **kwargs):
        self.warm_up()
        super(SleepDepriverConnection,self).__init__(*args,**kwargs)

    def warm_up(self):
        for j in range(3):
            for i in range(1,11):
                self.deprive(i)

    def deprive(self,channel, dt=500):
        self.move_to_angle(channel, self._min_angle_pulse[0],dt)
        time.sleep(dt/1000.0)
        self.move_to_angle(channel, self._max_angle_pulse[0],dt)
        time.sleep(dt/1000.0)

class SleepDepriverSubProcess(multiprocessing.Process):
    _DepriverConnectionClass = SleepDepriverConnection

    def __init__(self,queue, fake=False, *args, **kwargs):
        self._queue = queue
        self._sleep_dep_args = args
        self._sleep_dep_kwargs = kwargs
        super(SleepDepriverSubProcess,self).__init__()

    def run(self):
        do_run=True
        try:
            sleep_dep = self._DepriverConnectionClass(*self._sleep_dep_args, **self._sleep_dep_kwargs)

            while do_run:
                try:
                    instruction_kwargs = self._queue.get()
                    if (instruction_kwargs == 'DONE'):
                        do_run=False
                        continue
                    sleep_dep.deprive(**instruction_kwargs)
                except Exception as e:
                    do_run=False
                    logging.error("Unexpected error whist depriving. Instruction was: %s" % str(instruction_kwargs))
                    logging.error(e)

                finally:
                    if self._queue.empty():
                        #we sleep iff we have an empty queue. this way, we don't over use a cpu
                        time.sleep(.1)

        except KeyboardInterrupt as e:
            logging.warning("Sleep depriver async process interrupted with KeyboardInterrupt")
            raise e

        except Exception as e:
            logging.error("Sleep depriver  async process stopped with an exception")
            raise e

        finally:
            logging.info("Closing async sleep depriver")
            while not self._queue.empty():
                self._queue.get()
            self._queue.close()


class SleepDepriverInterface(BaseInterface):
    _SubProcessClass = SleepDepriverSubProcess
    def __init__(self,port="/dev/ttyUSB0"):
        self._queue = multiprocessing.JoinableQueue()
        self._sleep_dep_interface = self._SubProcessClass(queue = self._queue, port=port) # fixme, auto port detection
        self._sleep_dep_interface.start()
        super(SleepDepriverInterface, self).__init__()

    def interact(self, **kwargs):
        self._queue.put(kwargs)

    def _warm_up(self):
        # TODO
        pass

    def __del__(self):
        logging.info("Closing sleep depriver interface")
        self._queue.put("DONE")
        logging.info("Freeing queue")
        self._queue.cancel_join_thread()
        logging.info("Joining thread")
        self._sleep_dep_interface.join()
        logging.info("Joined OK")
