__author__ = 'quentin'

import cv2
try:
    from cv2.cv import CV_FOURCC as VideoWriter_fourcc
    from cv2.cv import CV_AA as LINE_AA
except ImportError:
    from cv2 import VideoWriter_fourcc
    from cv2 import LINE_AA

import os

class BaseDrawer(object):
    def __init__(self, video_out=None, draw_frames=True, video_out_fourcc="DIVX", video_out_fps=25):
        """
        A template class to annotate and save the processed frames. It can also save the annotated frames in a video
        file and/or display them in a new window. The :meth:`~ethoscope.drawers.drawers.BaseDrawer._annotate_frame`
        abstract method defines how frames are annotated.

        :param video_out: The path to the output file (.avi)
        :type video_out: str
        :param draw_frames: Whether frames should be displayed on the screen (a new window will be created).
        :type draw_frames: bool
        :param video_out_fourcc: When setting ``video_out``, this defines the codec used to save the output video (see `fourcc <http://www.fourcc.org/codecs.php>`_)
        :type video_out_fourcc: str
        :param video_out_fps: When setting ``video_out``, this defines the output fps. typically, the same as the input fps.
        :type video_out_fps: float
        """
        self._video_out = video_out
        self._draw_frames= draw_frames
        self._video_writer = None
        self._window_name = "ethoscope_" + str(os.getpid())
        self._video_out_fourcc = video_out_fourcc
        self._video_out_fps = video_out_fps
        if draw_frames:
            cv2.namedWindow(self._window_name, cv2.WINDOW_AUTOSIZE)
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
        :param positions: a list of positions resulting from analysis of the frame by a tracker
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
            self._video_writer = cv2.VideoWriter(self._video_out, VideoWriter_fourcc(*self._video_out_fourcc),
                                                 self._video_out_fps, (img.shape[1], img.shape[0]))

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
        A drawer that does nothing (no video writing, no annotation, no display on the screen).

        :return:
        """
        super(NullDrawer,self).__init__( draw_frames=False)
    def _annotate_frame(self,img, positions, tracking_units):
        pass



class DefaultDrawer(BaseDrawer):
    def __init__(self, video_out= None, draw_frames=False):
        """
        The default drawer. It draws ellipses on the detected objects and polygons around ROIs. When an "interaction"
        see :class:`~ethoscope.stimulators.stimulators.BaseInteractor` happens within a ROI,
        the ellipse is red, blue otherwise.

        :param video_out: The path to the output file (.avi)
        :type video_out: str
        :param draw_frames: Whether frames should be displayed on the screen (a new window will be created).
        :type draw_frames: bool
        """
        self._colormap = {0: (255, 0, 0),1: (255, 255, 0), 2: (0, 255, 0), 3: (0, 255, 255), 4: (0, 0, 255),
                          5: (255, 0, 255), 6: (128, 0, 255), 7: (255, 128, 0), 8: (128, 0, 0), 9: (128, 128, 0),
                          10: (0, 128, 0), 11: (0, 128, 128), 12: (0, 0, 128), 13: (128, 0, 128), 14: (128, 0, 128),
                          15: (0, 64, 0), 16: (0, 64, 64), 17: (0, 0, 64), 18: (64, 0, 64), 19: (64, 0, 64),
                          20: (0, 192, 0), 21: (0, 192, 192), 22: (0, 0, 192), 23: (192, 0, 192), 24: (192, 0, 192),
                          25: (255, 153, 153), 26: (255, 204, 153), 27: (255, 255, 153), 28: (204, 255, 153),
                          29: (153, 255, 153), 30: (153, 255, 204), 31: (153, 255, 255), 32: (153, 204, 255),
                          33: (153, 153, 255), 34: (204, 153, 255), 35: (255, 102, 102), 36: (255, 178, 102),
                          37: (255, 255, 102), 38: (178, 255, 102), 39: (102, 255, 102), 40: (102, 255, 178),
                          41: (102, 255, 255), 42: (102, 178, 255), 43: (102, 102, 255), 44: (178, 102, 255),
                          45: (255, 204, 204), 46: (255, 229, 204), 47: (255, 255, 204), 48: (229, 255, 204),
                          49: (204, 255, 204), 50: (204, 255, 229),
        }
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
            cv2.drawContours(img,[track_u.roi.polygon],-1, black_colour, 3, LINE_AA)
            cv2.drawContours(img,[track_u.roi.polygon],-1, roi_colour, 1, LINE_AA)

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


                if (pos["fly_id"] is not None and self._colormap[pos["fly_id"]]):
                    cv2.ellipse(img,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]), self._colormap[pos["fly_id"]],  3, LINE_AA)
                    cv2.ellipse(img,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]), black_colour, 1, LINE_AA)

                else:
                    cv2.ellipse(img,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]), colour,  3, LINE_AA)
                    cv2.ellipse(img,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]), black_colour, 1, LINE_AA)

