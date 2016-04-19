__author__ = 'quentin'


from ethoscope.interactors.interactors import BaseInteractor, HasInteractedVariable, SimpleScheduler
from ethoscope.hardware.interfaces.interfaces import  DefaultInterface
from ethoscope.hardware.interfaces.odour_delivery_device import OdourDelivererInterface
import sys


class HasChangedSideInteractor(BaseInteractor):
    _hardwareInterfaceClass = DefaultInterface

    def __init__(self, hardware_interface=None, middle_line=0.50):
        """
        class implementing an interactor that decides whether an animal has change side in its ROI.
        :param hardware_interface: a default hardware interface object
        :param middle_line: the x position defining the line to be crossed (from 0 to 1, relative to ROI)
        :type middle_line: float
        """
        self._middle_line = middle_line
        #self._last_active = 0
        super(HasChangedSideInteractor,self).__init__(hardware_interface)

    def _has_changed_side(self):
        positions = self._tracker.positions

        if len(positions ) <2 :
            return False


        if len(positions[-1]) != 1:
            raise Exception("This interactor can only work with a single animal per ROI")
        x0 = positions[-1][0]["x"]
        xm1 = positions[-2][0]["x"]

        if x0 > self._middle_line:
            current_region = 2
        else:
            current_region = 1

        if xm1 > self._middle_line:
            past_region = 2
        else:
            past_region = 1
        if current_region != past_region:
            # we return the current region as 1 or 2 if it has changed
            return current_region
        else:
            # no change => 0
            return 0

    def _decide(self):
        has_changed = self._has_changed_side()

        if  has_changed:
            return HasInteractedVariable(True), {}
        return HasInteractedVariable(False), {}

class DynamicOdourDeliverer(HasChangedSideInteractor):
    _description = {"overview": "An interactor to deliver an odour according to which side the animal of its ROI is in",
                    "arguments": [
                                    {"type": "datetime", "name": "start_datetime", "description": "When sleep deprivation is to be started","default":0},
                                    {"type": "datetime", "name": "end_datetime", "description": "When sleep deprivation is to be ended","default":sys.maxsize}
                                   ]}

    _hardwareInterfaceClass =  OdourDelivererInterface
    _roi_to_channel = {
            1:1,  2:2,  3:3,  4:4,  5:5,
            6:6, 7:7, 8:8, 9:9, 10:10
        }
    _side_to_pos = {1:1, 2:2 }
    def __init__(self,
                 hardware_interface,
                 start_datetime=0,
                 end_datetime=sys.maxsize,
                  ):
        """
        A interactor to control a sleep depriver module

        :param hardware_interface: the sleep depriver module hardware interface
        :type hardware_interface: :class:`~ethoscope.hardawre.interfaces.`
        :return:
        """

        self._inactivity_time_threshold_ms = min_inactive_time *1000 #so we use ms internally

        self._t0 = None
        self._scheduler = SimpleScheduler(start_datetime, end_datetime)
        super(DynamicOdourDeliverer, self).__init__(hardware_interface)



    def _decide(self):

        roi_id= self._tracker._roi.idx
        now =  self._tracker.last_time_point

        try:
            channel = self._roi_to_channel[roi_id]
        except KeyError:
            return HasInteractedVariable(False), {"channel":0}

        if self._scheduler.check_time_range() is False:
            return HasInteractedVariable(False), {"channel":channel}

        has_changed_side = self._has_changed_side()

        if has_changed_side == 0:
            return HasInteractedVariable(False), {"channel": channel}

        return HasInteractedVariable(True), {"channel":channel, "pos" : self._side_to_pos[has_changed_side]}

