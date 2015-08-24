from ethoscope.tracking.roi_builders import TubeMonitorWithTargetROIBuilder
import cv2


def draw_rois(im, all_rois):
    for roi in all_rois:
        x,y = roi.offset
        y += roi.rectangle[3]/2
        x += roi.rectangle[2]/2
        cv2.putText(im, str(roi.idx), (x,y), cv2.FONT_HERSHEY_COMPLEX_SMALL, 1, (255,255,0))
        black_colour,roi_colour = (0, 0,0), (0, 255,0)
        cv2.drawContours(im,[roi.polygon],-1, black_colour, 3, cv2.CV_AA)
        cv2.drawContours(im,[roi.polygon],-1, roi_colour, 1, cv2.CV_AA)


smrb = TubeMonitorWithTargetROIBuilder()
im = cv2.imread("./tube_monitor_exple.png")
all_rois = smrb(im)
draw_rois(im, all_rois)

cv2.imshow("d",im)
cv2.waitKey(-1)