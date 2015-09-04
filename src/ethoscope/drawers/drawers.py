__author__ = 'quentin'

import cv2
from ethoscope.utils.description import DescribedObject
import os

class BaseDrawer(object):
    _out_fps = 2

    def __init__(self, video_out=None, draw_frames=True):
        self._video_out = video_out
        self._draw_frames= draw_frames
        self._video_writer = None
        self._window_name = "ethoscope_" + str(os.getpid())
        if draw_frames:
            cv2.namedWindow(self._window_name, cv2.CV_WINDOW_AUTOSIZE)


    def _annotate_frame(self,img, positions, tracking_units):
        raise NotImplementedError

    @property
    def last_drawn_frame(self):
        return self._last_drawn_frame

    def draw(self,img, positions, tracking_units):
        if not self._draw_frames and self._video_out is None:
            return

        self._last_drawn_frame = img.copy()
        self._annotate_frame(self._last_drawn_frame, positions,tracking_units)

        if self._draw_frames:
            cv2.imshow(self._window_name, self._last_drawn_frame )
            cv2.waitKey(1)

        if self._video_out is None:
            return

        if self._video_writer is None:
            self._video_writer = cv2.VideoWriter(self._video_out, cv2.cv.CV_FOURCC(*'DIVX'),
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
        super(NullDrawer,self).__init__(video_out=None, draw_frames=False)
    def _annotate_frame(self,img, positions, tracking_units):
        return


class DefaultDrawer(BaseDrawer):
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
                pos = positions[track_u.roi.idx]
                if pos is None:
                    continue
            except KeyError:
                continue

            colour = (0 ,0, 255)
            try:
                if pos["has_interacted"]:
                    colour = (255, 0,0)
            except KeyError:
                pass

            cv2.ellipse(img,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]),black_colour,3,cv2.CV_AA)
            cv2.ellipse(img,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]),colour,1,cv2.CV_AA)
