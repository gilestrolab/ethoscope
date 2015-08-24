from ethoscope.tracking.roi_builders import TargetGridROIBuilderBase
import cv2

class EightByEight(TargetGridROIBuilderBase):
    _vertical_spacing =  0.1/16.
    _horizontal_spacing =  .1/100.
    _n_rows = 8
    _n_cols = 8

class SixteenByThree(TargetGridROIBuilderBase):
    _vertical_spacing =  0.1/16.
    _horizontal_spacing =  .1/100.
    _n_rows = 16
    _n_cols = 3

def draw_rois(im, all_rois):
    for roi in all_rois:
        x,y = roi.offset
        y += roi.rectangle[3]/2
        x += roi.rectangle[2]/2
        cv2.putText(im, str(roi.idx), (x,y), cv2.FONT_HERSHEY_COMPLEX_SMALL, 1, (255,255,0))
        black_colour,roi_colour = (0, 0,0), (0, 255,0)
        cv2.drawContours(im,[roi.polygon],-1, black_colour, 3, cv2.CV_AA)
        cv2.drawContours(im,[roi.polygon],-1, roi_colour, 1, cv2.CV_AA)


im = cv2.imread("./new_targets.png")

roi_builder = EightByEight()
all_rois = roi_builder(im)
draw_rois(im, all_rois)
cv2.imwrite("/tmp/8x8.png",im)

im = cv2.imread("./new_targets.png")
roi_builder = SixteenByThree()
all_rois = roi_builder(im)
draw_rois(im, all_rois)
cv2.imwrite("/tmp/16x3.png",im)
