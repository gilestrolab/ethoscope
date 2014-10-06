__author__ = 'quentin'

import numpy as np
import multiprocessing
from subprocess import call

class BaseInteractor(object):
    _tracker = None
    _subprocess = multiprocessing.Process()

    _target = None

    def __call__(self):
        if self._tracker is None:
            raise ValueError("No tracker bound to this interactor. Use `bind_tracker()` methods")
        interact, args = self._run()
        if interact:
            self._interact_async(args)

    def bind_tracker(self, tracker):
        self._tracker = tracker

    def _run(self):
        raise NotImplementedError

    def _interact_async(self, args):

        # If the target is being run, we wait
        if self._subprocess.is_alive():
            return

        if self._target is None:
            raise NotImplementedError("_target must ba a defined function")

        print "biiiiiiiim", args, self._target
        self._subprocess = multiprocessing.Process(target=self._target, args = args)

        self._subprocess.start()




class DefaultInteractor(BaseInteractor):

    def _run(self):
        # does NOTHING
        pass




def beep(frequency):
    from scikits.audiolab import play
    length = 2
    rate = 10000.
    length = int(length * rate)
    factor = float(frequency) * (3.14 * 2) / rate
    s = np.sin(np.arange(length) * factor)
    s *= np.linspace(1,0.3,len(s))
    play(s, 10000)


class SystemPlaySoundOnStop(BaseInteractor):


    def __init__(self):
        self._t0 = None
        self._target = beep
        self._freq = 1000

    def _run(self):
        positions = self._tracker.positions
        time = self._tracker.times


        if len(positions ) <2 :
            return False, (self._freq,)

        if np.abs(positions[-1] - positions[-2]) < 5:
            now = time[-1]
            if self._t0 is None:
                self._t0 = now
            else:
                if(now - self._t0) > 30: # 5s of inactivity
                    return True, (self._freq,)

        else:
            self._t0 = None

        return False, (self._freq,)




