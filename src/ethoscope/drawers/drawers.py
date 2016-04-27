__author__ = 'quentin'

import cv2
try:
    from cv2.cv import CV_FOURCC
except ImportError:
    from cv2 import CV_FOURCC

from ethoscope.utils.description import DescribedObject
import os

class BaseDrawer(object):
    _out_fps = 2

    def __init__(self, video_out=None, draw_frames=True):
        """
        A template class to annotate and save the processed frames. It can also save the annotated frames in a video
        file and/or display them in a new window. The :meth:`~ethoscope.drawers.drawers.BaseDrawer._annotate_frame`
        abstract method defines how frames are annotated.

        :param video_out: The path to the output file (.avi)
        :type video_out: str
        :param draw_frames: Whether frames should be displayed on the screen (a new window will be created).
        :type draw_frames: bool
        """
        self._video_out = video_out
        self._draw_frames= draw_frames
        self._video_writer = None
        self._window_name = "ethoscope_" + str(os.getpid())
        if draw_frames:
            cv2.namedWindow(self._window_name, cv2.CV_WINDOW_AUTOSIZE)
        self._last_drawn_frame = None

    def _annotate_frame(self,img, positions, tracking_units):
        """
        Abstract method defining how frames should be annotated.
        The `img` array, which is passed by reference, is meant to be modified by this method.

        :param img: the frame that was just processed
        :type img: :class:`~numpy.ndarray`
        :param positions: a list of positions resulting from analysis of the frame
        :type positions: list(:class:`~ethoscope.core.data_point.DataPoint`)
        :param tracking_units: the tracking units corresponding to the positions
        :type tracking_units: list(:class:`~ethoscope.core.tracking_unit.TrackingUnit`)
        :return:
        """
        raise NotImplementedError

    @property
    def last_drawn_frame(self):
        return self._last_drawn_frame

    def draw(self,img, positions, tracking_units):
        """
        Draw results on a frame.

        :param img: the frame that was just processed
        :type img: :class:`~numpy.ndarray`
        :param positions: a list of positions resulting from analysis of the frame
        :type positions: list(:class:`~ethoscope.core.data_point.DataPoint`)
        :param tracking_units: the tracking units corresponding to the positions
        :type tracking_units: list(:class:`~ethoscope.core.tracking_unit.TrackingUnit`)
        :return:
        """

        self._last_drawn_frame = img.copy()

        self._annotate_frame(self._last_drawn_frame, positions,tracking_units)

        if self._draw_frames:
            cv2.imshow(self._window_name, self._last_drawn_frame )
            cv2.waitKey(1)

        if self._video_out is None:
            return

        if self._video_writer is None:
            self._video_writer = cv2.VideoWriter(self._video_out, CV_FOURCC(*'DIVX'),
                                                 self._out_fps, (img.shape[1], img.shape[0]))

        self._video_writer.write(self._last_drawn_frame)

    def __del__(self):
        if self._draw_frames:
            cv2.waitKey(1)
            cv2.destroyAllWindows()
            cv2.waitKey(1)
        if self._video_writer is not None:
            self._video_writer.release()


class NullDrawer(BaseDrawer):
    def __init__(self):
        """
        A drawer that does not do anything (no video writing, no annotation, no display on the screen).

        :return:
        """
        super(NullDrawer,self).__init__(video_out=None, draw_frames=False)
    def _annotate_frame(self,img, positions, tracking_units):
        pass


class DefaultDrawer(BaseDrawer):
    def __init__(self, video_out= None, draw_frames=False):
        """
        The default drawer. It draws ellipses on the detected objects and polygons around ROIs. When an "interaction"
        see :class:`~ethoscope.interactors.interactors.BaseInteractor`
        happens within a ROI, the ellipse is red, blue otherwise.

        :param video_out: The path to the output file (.avi)
        :type video_out: str
        :param draw_frames: Whether frames should be displayed on the screen (a new window will be created).
        :type draw_frames: bool
        """
        super(DefaultDrawer,self).__init__(video_out=video_out, draw_frames=draw_frames)

    def _annotate_frame(self,img, positions, tracking_units):

        if img is None:
            return


        for track_u in tracking_units:

            x,y = track_u.roi.offset
            y += track_u.roi.rectangle[3]/2

            cv2.putText(img, str(track_u.roi.idx), (x,y), cv2.FONT_HERSHEY_COMPLEX_SMALL, 1, (255,255,0))
            black_colour = (0, 0,0)
            roi_colour = (0, 255,0)
            cv2.drawContours(img,[track_u.roi.polygon],-1, black_colour, 3, cv2.CV_AA)
            cv2.drawContours(img,[track_u.roi.polygon],-1, roi_colour, 1, cv2.CV_AA)

            try:
                pos_list = positions[track_u.roi.idx]
            except KeyError:
                continue

            for pos in pos_list:
                colour = (0 ,0, 255)
                try:
                    if pos["has_interacted"]:
                        colour = (255, 0,0)
                except KeyError:
                    pass

                cv2.ellipse(img,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]),black_colour,3,cv2.CV_AA)
                cv2.ellipse(img,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]),colour,1,cv2.CV_AA)
