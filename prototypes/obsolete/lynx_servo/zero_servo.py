from ethoscope.hardware.interfaces.odour_delivery_device import OdourDelivererInterface
import time
class ZeroEr(OdourDelivererInterface):
    def _warm_up(self):
        for i in range(self._n_channels):
            self._move_to_pos(i+1,1)
            time.sleep(.5)
            self._move_to_pos(i + 1, 2)
            time.sleep(.5)
            self._move_to_pos(i + 1, 3)
            time.sleep(.3)


a = ZeroEr(port="/dev/ttyUSB0")


