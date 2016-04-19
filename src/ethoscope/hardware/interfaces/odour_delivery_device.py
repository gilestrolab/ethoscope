__author__ = 'quentin'

import time
import logging
import multiprocessing

from ethoscope.hardware.interfaces.interfaces import BaseInterface
from ethoscope.hardware.interfaces.lynx_motion import SimpleLynxMotionConnection



class OdourDelivererConnection(SimpleLynxMotionConnection):
    def __init__(self,*args, **kwargs):
        """
        Class to connect to the odour deliverer module.

        :param args: additional arguments to be passed to the base class
        :param kwargs: additional keyword arguments to be passed to the base class
        """
        super(OdourDelivererConnection,self).__init__(*args,**kwargs)
        self._positions_to_angles = { 1: -20,
                                      2: 20,
                                      3: 0}
        self._extra_move = 0.25
        self._dt = 750.0
        self._current_pos = [3] * 10
        self.warm_up()

    def warm_up(self):
        """
        Warm up the module. That is move each tube three times in order to check setup and that no servo has failed.
        """

        #for i in range(1,11):
        for i in range(1, 2):
            for k in range(1,4):
                self.move_to_pos(i, k)

            time.sleep(3 * self._dt / 1000.0)
            print ('i', i)

    def move_to_pos(self,channel, pos):
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
            current_angle = self._positions_to_angles[self._current_pos[channel]]
            pos_to_go = 0 - current_angle * self._extra_move
            self.move_to_angle(channel, pos_to_go, self._dt)


        # then we bounce back to the final position:
        time.sleep(self._dt/1000)
        self.move_to_angle(channel, angle, self._dt)
        self._current_pos[channel] = pos
        time.sleep(self._dt / 1000.0)

#
#
class OdourDelivererSubProcess(multiprocessing.Process):
    _ConnectionClass = OdourDelivererConnection

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
        super(OdourDelivererSubProcess,self).__init__()

    def run(self):
        do_run=True
        try:
            device = self._ConnectionClass(*self._sleep_dep_args, **self._sleep_dep_kwargs)

            while do_run:
                try:
                    instruction_kwargs = self._queue.get()
                    if (instruction_kwargs == 'DONE'):
                        do_run=False
                        continue
                    device.move_to_pos(**instruction_kwargs)
                except Exception as e:
                    do_run=False
                    logging.error("Unexpected error whilst depriving. Instruction was: %s" % str(instruction_kwargs))
                    logging.error(e)

                finally:
                    if self._queue.empty():
                        #we sleep iff we have an empty queue. this way, we don't over use a cpu
                        time.sleep(.1)

        except KeyboardInterrupt as e:
            logging.warning("Odour deliverer async process interrupted with KeyboardInterrupt")
            raise e

        except Exception as e:
            logging.error("Odour deliverer async process stopped with an exception")
            raise e

        finally:
            logging.info("Closing async odour deliverer")
            while not self._queue.empty():
                self._queue.get()
            self._queue.close()


class OdourDelivererInterface(BaseInterface):
#
    _SubProcessClass = OdourDelivererSubProcess
    def __init__(self,port="/dev/ttyUSB0"):
        """
        Class implementing the interface to the sleep depriver module, which rotate tubes to sleep deprive animals.

        :param port: the serial port on which the device is plugged. If ``None`` automatic port detection is attempted.
        :type port: str or None
        """
        self._queue = multiprocessing.JoinableQueue()
        self._sleep_dep_interface = self._SubProcessClass(queue = self._queue, port=port) # fixme, auto port detection
        self._sleep_dep_interface.start()
        super(OdourDelivererInterface, self).__init__()

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
#