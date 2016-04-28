__author__ = 'quentin'


from ethoscope.interactors.interactors import BaseInteractor, HasInteractedVariable
from ethoscope.utils.scheduler import Scheduler

from ethoscope.hardware.interfaces.interfaces import  DefaultInterface
from ethoscope.hardware.interfaces.odour_delivery_device import OdourDelivererInterface
import sys
import logging

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

        w = float(self._tracker._roi.get_feature_dict()["w"])
        if len(positions[-1]) != 1:
            raise Exception("This interactor can only work with a single animal per ROI")
        x0 = positions[-1][0]["x"] / w
        xm1 = positions[-2][0]["x"] / w


        if x0 > self._middle_line:
            current_region = 2
        else:
            current_region = 1

        if xm1 > self._middle_line:
            past_region = 2
        else:
            past_region = 1

        if self._tracker._roi == 1:
            logging.warning(str((x0, xm1, current_region, past_region)))

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
                                {"type": "date_range", "name": "date_range",
                                 "description": "A date  and time range in which the device will perform (see http://tinyurl.com/jv7k826)",
                                 "default": ""}
                                   ]}

    _hardwareInterfaceClass =  OdourDelivererInterface
    _roi_to_channel = {
            1:1,  2:2,  3:3,  4:4,  5:5,
            6:6, 7:7, 8:8, 9:9, 10:10
        }
    _side_to_pos = {1:1, 2:2 }
    def __init__(self,
                 hardware_interface,
                 date_range=""
                  ):
        """
        A interactor to control a sleep depriver module

        :param hardware_interface: the sleep depriver module hardware interface
        :type hardware_interface: :class:`~ethoscope.hardawre.interfaces.`
        :return:
        """

        self._t0 = None
        self._scheduler = Scheduler(date_range)
        super(DynamicOdourDeliverer, self).__init__(hardware_interface)



    def _decide(self):
        roi_id= self._tracker._roi.idx
        try:
            channel = self._roi_to_channel[roi_id]
        except KeyError:
            return HasInteractedVariable(False), {"channel":0, "pos": None}

        if self._scheduler.check_time_range() is False:
            return HasInteractedVariable(False), {"channel":channel, "pos": None}

        has_changed_side = self._has_changed_side()

        if has_changed_side == 0:
            return HasInteractedVariable(False), {"channel": channel, "pos": None}

        return HasInteractedVariable(True), {"channel":channel, "pos" : self._side_to_pos[has_changed_side]}
