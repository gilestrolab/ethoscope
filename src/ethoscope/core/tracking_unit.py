__author__ = 'quentin'
from ethoscope.core.variables import BaseRelativeVariable
from ethoscope.core.data_point import DataPoint
from ethoscope.stimulators.stimulators import DefaultStimulator


class TrackingUnit(object):
    def __init__(self, tracking_class, roi, stimulator=None, *args, **kwargs):
        r"""
        Class instantiating a tracker(:class:`~ethoscope.trackers.trackers.BaseTracker`),
        and linking it with an individual ROI(:class:`~ethoscope.rois.roi_builders.ROI`) and
        stimulator(:class:`~ethoscope.stimulators.stimulators.BaseStimulator`).
        Typically, several `TrackingUnit` objects are built internally by a Monitor(:class:`~ethoscope.core.monitor.Monitor`).

        :param tracker_class: The algorithm that will be used for tracking. It must inherit from :class:`~ethoscope.trackers.trackers.BaseTracker`
        :type tracker_class: class
        :param roi: A region of interest.
        :type roi: :class:`~ethoscope.core.roi.ROI`.
        :param stimulator: an object used to physically interact with the detected animal.
        :type stimulator: :class:`~ethoscope.stimulators.stimulators.BaseStimulator`.
        :param args: additional arguments passed to the tracking algorithm.
        :param kwargs: additional keyword arguments passed to the tracking algorithm.
        """

        self._tracker = tracking_class(roi,*args, **kwargs)
        self._roi = roi

        if stimulator is not None:
            self._stimulator= stimulator
        else:
            self._stimulator = DefaultStimulator(None)

        self._stimulator.bind_tracker(self._tracker)


    @property
    def stimulator(self):
        """
        :return: A reference to the stimulator used by this `TrackingUnit`
        :rtype: :class:`~ethoscope.stimulators.stimulators.BaseStimulator`
        """
        return self._stimulator

    @property
    def roi(self):
        """
        :return: A reference to the roi used by this `TrackingUnit`
        :rtype: :class:`~ethoscope.core.roi.ROI`
        """
        return self._roi

    def get_last_positions(self,absolute=False):
        """
        The last position of the animal monitored by this `TrackingUnit`

        :param absolute: Whether the position should be relative to the top left corner of the raw frame (`true`), or to the top left of the used ROI (`false`).
        :return: A container with the last variable recorded for this roi.
        :rtype:  :class:`~ethoscope.core.data_point.DataPoint`
        """

        if len(self._tracker.positions) < 1:
            return []
        last_positions = self._tracker.positions[-1]
        if not absolute:
            return last_positions
        out =[]
        for last_pos in last_positions:
            tmp_out = []
            for k,i in list(last_pos.items()):
                if isinstance(i, BaseRelativeVariable):
                    tmp_out.append(i.to_absolute(self.roi))
                else:
                    tmp_out.append(i)
            tmp_out = DataPoint(tmp_out)
            out.append(tmp_out)


        return out



    def track(self, t, img):
        """
        Uses the whole frame acquired, along with its time stamp to infer position of the animal.
        Also runs the stimulator object.

        :param t: the time stamp associated to the provided frame (in ms).
        :type t: int
        :param img: the entire frame to analyse
        :type img: :class:`~numpy.ndarray`
        :return: The resulting data point
        :rtype:  :class:`~ethoscope.core.data_point.DataPoint`
        """
        data_rows = self._tracker.track(t,img)

        interact, result = self._stimulator.apply()
        if len(data_rows) == 0:
            return []

        # TODO data_row should have some result
        for dr in data_rows:
            dr.append(interact)

        return data_rows
