__author__ = 'quentin'

import cv2
import numpy as np
from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder
from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder
import itertools


class HD12TubesRoiBuilder(TargetGridROIBuilder):
    _description = {"overview": "The default sleep monitor arena with ten rows of two tubes.",
                    "arguments": []}


    def __init__(self):
        """
        Class to build ROIs for a twelve columns, one row for the HD tracking arena
        (https://github.com/gilestrolab/ethoscope_hardware/tree/master/arenas/arena_mini_12_tubes)
        """


        super(HD12TubesRoiBuilder, self).__init__( n_rows=1,
                                                   n_cols=12,
                                                   top_margin= 1.5,
                                                   bottom_margin= 1.5,
                                                   left_margin=0.05,
                                                   right_margin=0.05,
                                                   horizontal_fill=.7,
                                                   vertical_fill=1.4
                                                   )


def draw_rois(im, all_rois):
    for roi in all_rois:
        x,y = roi.offset
        y += roi.rectangle[3]/2
        x += roi.rectangle[2]/2
        cv2.putText(im, str(roi.idx), (x,y), cv2.FONT_HERSHEY_COMPLEX_SMALL, 1, (255,255,0))
        black_colour,roi_colour = (0, 0,0), (0, 255,0)
        cv2.drawContours(im,[roi.polygon],-1, black_colour, 3, cv2.CV_AA)
        cv2.drawContours(im,[roi.polygon],-1, roi_colour, 1, cv2.CV_AA)



test_rb = HD12TubesRoiBuilder()
im = cv2.imread("sample.png")
rois = test_rb.build(im)

draw_rois(im,rois)
cv2.imshow("trest",im)
cv2.waitKey(-1)


