__author__ = 'quentin'

import numpy as np
import multiprocessing
from subprocess import call
import pandas as pd
from pysolovideo.hardware_control.arduino_api import SleepDepriverInterface

class BaseInteractorSync(object):
    _tracker = None


    def __call__(self):
        if self._tracker is None:
            raise ValueError("No tracker bound to this interactor. Use `bind_tracker()` methods")

        interact, result  = self._run()
        if interact:
            print result

            self._interact(**result)

        result["interact"] = interact

        return pd.DataFrame(result, index=[None])


    def bind_tracker(self, tracker):
        self._tracker = tracker


    def _run(self):
        raise NotImplementedError

    def _interact(self, kwargs):
        raise NotImplementedError

class SleepDepInteractor(BaseInteractorSync):
    def __init__(self, channel, sd_interface ):
        self._sleep_dep_interface = sd_interface
        self._t0 = None
        self._channel = channel

        self._distance_threshold = 1e-3
        self._inactivity_time_threshold = 20 # s

    def _interact(self, **kwargs):
        self._sleep_dep_interface.deprive(**kwargs)

    def _run(self):
        positions = self._tracker.positions
        time = self._tracker.times

        if len(positions ) <2 :
            return False, {"channel":self._channel}
        tail_m = positions.tail(1)
        xy_m = complex(tail_m.x + 1j * tail_m.y)

        tail_mm = positions.tail(2).head(1)

        xy_mm =complex(tail_mm.x + 1j * tail_mm.y)

        if np.abs(xy_m - xy_mm) < self._distance_threshold:

            now = time[-1]
            if self._t0 is None:
                self._t0 = now

            else:
                if(now - self._t0) > self._inactivity_time_threshold:

                    self._t0 = None
                    return True, {"channel":self._channel}

        else:
            self._t0 = None

        return False, {"channel":self._channel}



###Prototyping below ###########################
class BaseInteractor(object):
    _tracker = None
    # this is not v elegant
    _subprocess = multiprocessing.Process()

    _target = None

    def __call__(self):
        if self._tracker is None:
            raise ValueError("No tracker bound to this interactor. Use `bind_tracker()` methods")

        interact, result  = self._run()
        if interact:
            self._interact_async(result)

        result["interact"] = interact

        return pd.DataFrame(result, index=[None])


    def bind_tracker(self, tracker):
        self._tracker = tracker


    def _run(self):
        raise NotImplementedError

    def _interact_async(self, kwargs):

        # If the target is being run, we wait
        if self._subprocess.is_alive():
            return

        if self._target is None:
            raise NotImplementedError("_target must ba a defined function")

        self._subprocess = multiprocessing.Process(target=self._target, kwargs = kwargs)

        self._subprocess.start()

class DefaultInteractor(BaseInteractor):

    def _run(self):
        # does NOTHING
        pass

def beep(freq):
    from scikits.audiolab import play
    length = 0.5
    rate = 10000.
    length = int(length * rate)
    factor = float(freq) * (3.14 * 2) / rate
    s = np.sin(np.arange(length) * factor)
    s *= np.linspace(1,0.3,len(s))
    play(s, 10000)

class SystemPlaySoundOnStop(BaseInteractor):

    def __init__(self, freq):
        self._t0 = None
        self._target = beep
        self._freq = freq
        self._distance_threshold = 1e-3
        self._inactivity_time_threshold = 10 # s
    def _run(self):
        positions = self._tracker.positions
        time = self._tracker.times

        if len(positions ) <2 :
            return False, {"freq":self._freq}

        tail_m = positions.tail(1)
        xy_m = complex(tail_m.x + 1j * tail_m.y)

        tail_mm = positions.tail(2).head(1)

        xy_mm =complex(tail_mm.x + 1j * tail_mm.y)

        if np.abs(xy_m - xy_mm) < self._distance_threshold:

            now = time[-1]
            if self._t0 is None:
                self._t0 = now

            else:
                if(now - self._t0) > self._inactivity_time_threshold:

                    self._t0 = None
                    return True, {"freq":self._freq}

        else:
            self._t0 = None

        return False, {"freq":self._freq}




