__author__ = 'quentin'

import serial
import time
import logging
import multiprocessing

from ethoscope.hardware.interfaces.interfaces import BaseInterface
from ethoscope.hardware.interfaces.lynx_motion import SimpleLynxMotionConnection



class SleepDepriverConnection(SimpleLynxMotionConnection):
    def __init__(self,*args, **kwargs):
        """
        Class to connect to the sleep depriver module.

        :param args: additional arguments to be passed to the base class
        :param kwargs: additional keyword arguments to be passed to the base class
        """
        super(SleepDepriverConnection,self).__init__(*args,**kwargs)
        self.warm_up()

    def warm_up(self):
        """
        Warm up the module. That is move each tube three times in order to check setup and that no servo has failed.
        """
        for j in range(3):
            for i in range(1,11):
                self.deprive(i)

    def deprive(self,channel, dt=350,margin=10):
        """
        Sleep deprive an animal by rotating its tube.

        :param channel: The chanel to use (i.e. the number of the servo)
        :typechannel: int
        :param dt: The time it takes to go from 0 to 180 degrees (in ms)
        :type dt: int
        :param margin: the number of degree to pad rotation. eg 5 -> rotation from 5 -> 175
        :type dt: int
        """
        
        
        half_dt = int(float(dt/2.0))
        self.move_to_angle(channel, self._max_angle_pulse[0]-margin,half_dt)
        time.sleep(dt/2000.0)
        self.move_to_angle(channel, self._min_angle_pulse[0]+margin,dt)
        time.sleep(dt/1000.0)
        self.move_to_angle(channel, self._max_angle_pulse[0]-margin,dt)
        time.sleep(dt/1000.0)
        self.move_to_angle(channel, 0,half_dt)
        time.sleep(dt/2000.0)

class SleepDepriverSubProcess(multiprocessing.Process):
    _DepriverConnectionClass = SleepDepriverConnection

    def __init__(self,queue,  *args, **kwargs):
        """
        Class to run delegate sleep deprivation connection (:class:`~ethoscope.hardware.interfaces.sleep_depriver_interface.SleepDepriverConnection`).
        To a parallel process. This way, the execution of the sleep depriver connection instructions are non-blocking.

        :param queue: A multiprocessing queue to pass instructions.
        :type queue: :class:`~multiprocessing.JoinableQueue`
        :param args: additional arguments
        :param kwargs: additional keyword arguments
        :return:
        """
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
        """
        Class implementing the interface to the sleep depriver module, which rotate tubes to sleep deprive animals.

        :param port: the serial port on which the device is plugged. If ``None`` automatic port detection is attempted.
        :type port: str or None
        """
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
