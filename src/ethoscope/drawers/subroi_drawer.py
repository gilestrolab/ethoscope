__author__ = 'diana'

import cv2
import time

try:
    from cv2.cv import CV_AA as LINE_AA
except ImportError:
    from cv2 import LINE_AA

from ethoscope.drawers.drawers import BaseDrawer
import numpy as np

class SubRoiDrawer(BaseDrawer):

    def __init__(self, video_out= None, draw_frames=False, video_out_fps = 25):
        """
        The SubRoi drawer. It draws the sub-rois mask, with transparency, on top of the video. It draws ellipses on the detected objects and polygons around ROIs. When an "interaction"
        see :class:`~ethoscope.stimulators.stimulators.BaseInteractor` happens within a ROI,
        the ellipse is red, blue otherwise.

        :param video_out: The path to the output file (.avi)
        :type video_out: str
        :param draw_frames: Whether frames should be displayed on the screen (a new window will be created).
        :type draw_frames: bool
        """
        super(SubRoiDrawer,self).__init__(video_out=video_out, draw_frames=draw_frames, video_out_fps = video_out_fps)

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


            if (np.array_equal(track_u.roi._sub_rois, track_u.roi._mask)):
                continue
            else:
                opacity = 0.4
                x, y, w, h = track_u.roi._rectangle
                overlay = img.copy()
                color_regions = cv2.cvtColor(track_u.roi._sub_rois, cv2.COLOR_GRAY2BGR)
                overlay[y:y+h, x: x+w] = color_regions
                cv2.addWeighted(overlay, opacity, img, 1 - opacity, 0, img)

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

                cv2.ellipse(img,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]),black_colour,3, LINE_AA)
                cv2.ellipse(img,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]),colour,1, LINE_AA)

