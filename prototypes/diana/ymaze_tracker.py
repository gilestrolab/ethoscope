__author__ = 'diana'


from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.trackers.trackers import *
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder
from ethoscope.core.monitor import Monitor
from ethoscope.core.data_point import DataPoint
from ethoscope.utils.io import SQLiteResultWriter
from ethoscope.drawers.drawers import DefaultDrawer
from ethoscope.core.roi import ROI

from math import log10, sqrt, pi
import cv2
import numpy as np
import optparse
import logging
from ethoscope.utils.debug import EthoscopeException
from ethoscope.core.roi import ROI
import math

class YmazeDrawer(DefaultDrawer):
    def __init__(self, video_out= None, draw_frames=False, targets=None, holes=None):
        """
        A template class to annotate and save the processed frames. It can also save the annotated frames in a video
        file and/or display them in a new window. The :meth:`~ethoscope.drawers.drawers.BaseDrawer._annotate_frame`
        abstract method defines how frames are annotated.

        :param video_out: The path to the output file (.avi)
        :type video_out: str
        :param draw_frames: Whether frames should be displayed on the screen (a new window will be created).
        :type draw_frames: bool
        """
        super(YmazeDrawer,self).__init__(video_out=video_out, draw_frames=draw_frames)
        self._targets = targets



    def _annotate_frame(self,img, positions, tracking_units):

        if img is None:
            return

        if self._targets is not None:
            targets = self._targets

            if len(targets) != 3:
                logging.error("Found a different number of targets")
            cv2.circle(img, (int(targets[0][0]),int(targets[0][1])),10, (0,0,255), 1, cv2.CV_AA)
            cv2.circle(img, (int(targets[1][0]),int(targets[1][1])),10, (0,0,255), 1, cv2.CV_AA)
            cv2.circle(img, (int(targets[2][0]),int(targets[2][1])),10, (0,0,255), 1, cv2.CV_AA)

        #img = cv2.drawKeypoints(img, keypoints, np.array([]), (0 ,0, 255), cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)
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
                cv2.line(img, (pos["x"],pos["y"]),(pos["x"] + int(pos["w"]/2 * math.cos(math.radians(pos["phi"]))),pos["y"] + int(pos["w"]/2 * math.sin(math.radians(pos["phi"])))), colour, 1, cv2.CV_AA);


class YMazeTracker(BaseTracker):
    def __init__(self, roi, data=None):
        self._accum = None
        self._alpha = 0.001
        super(YMazeTracker, self).__init__(roi, data)

    def _filter_contours(self, contours, min_area =50, max_area=200):
        out = []
        for c in contours:
            if c.shape[0] < 6:
                continue
            area = cv2.contourArea(c)
            if not min_area < area < max_area:
                continue

            out.append(c)
        return out

    def _find_position(self, img, mask,t):
        grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return self._track(img, grey, mask, t)

    def _track(self, img,  grey, mask, t):
        if self._accum is None:
            self._accum = grey.astype(np.float64)
            self._old_pos = 0.0 +0.0j

        frame_float64 = grey.astype(np.float64)
        cv2.accumulateWeighted(frame_float64, self._accum, self._alpha)
        bg = self._accum.astype(np.uint8)

        #cv2.imshow('bg', bg)
        #cv2.waitKey(30)

        diff = cv2.absdiff(bg, grey)
        #
        #cv2.imshow('this', img)
        #cv2.waitKey(30)
        cv2.medianBlur(grey, 7, grey)
        _, bin_im = cv2.threshold(diff, 100, 255, cv2.THRESH_BINARY)

        #cv2.imshow('bin', bin_im)
        #cv2.waitKey(30)

        contours,hierarchy = cv2.findContours(bin_im,
                                              cv2.RETR_EXTERNAL,
                                              cv2.CHAIN_APPROX_SIMPLE)

        contours= self._filter_contours(contours)

        if len(contours) != 1:
            raise NoPositionError
        hull = contours[0]

        (_,_) ,(w,h), angle = cv2.minAreaRect(hull)

        M = cv2.moments(hull)
        x = int(M['m10']/M['m00'])
        y = int(M['m01']/M['m00'])
        if w < h:
            angle -= 90
            w,h = h,w
        angle = angle % 180

        h_im = min(grey.shape)
        w_im = max(grey.shape)


        max_h = 2*h_im
        if w>max_h or h>max_h:
            raise NoPositionError


        pos = x +1.0j*y
        pos /= w_im

        xy_dist = round(log10(1./float(w_im) + abs(pos - self._old_pos))*1000)

        self._old_pos = pos

        x_var = XPosVariable(int(round(x)))
        y_var = YPosVariable(int(round(y)))
        w_var = WidthVariable(int(round(w)))
        h_var = HeightVariable(int(round(h)))
        phi_var = PhiVariable(int(round(angle)))
        distance = XYDistance(int(xy_dist))
        out = DataPoint([x_var, y_var, w_var, h_var, phi_var, distance])

        return [out]




class YmazeROIBuilder(TargetGridROIBuilder):
    _description = {"overview": "The default Y maze ROI builder",
                    "arguments": []}



    def __init__(self):
        super(YmazeROIBuilder, self).__init__(n_rows=1,
                                                               n_cols=1,
                                                               top_margin=0,
                                                               bottom_margin=0,
                                                               left_margin = 0.3,
                                                               right_margin = 0.36,
                                                               horizontal_fill =  1.1,
                                                               vertical_fill= 1.15
                                            )


    def _find_target_coordinates(self, img):
        params = cv2.SimpleBlobDetector_Params()
        # Change thresholds
        params.minThreshold = 0;
        params.maxThreshold = 50;

        # Filter by Area.
        params.filterByArea = True
        params.minArea = 400

        # Filter by Circularity
        params.filterByCircularity = True
        params.minCircularity = 0.32


        # Filter by Convexity
        params.filterByConvexity = True
        params.minConvexity = 0.3
        #
        # # Filter by Inertia
        # params.filterByInertia = True
        # params.minInertiaRatio = 0.01

        detector = cv2.SimpleBlobDetector(params)

        #cv2.imshow('here', img)
        #cv2.waitKey(0)

        keypoints = detector.detect(img)

        if np.size(keypoints) !=3:
            logging.error('Just %s targets found instead of three', np.size(keypoints))


        return keypoints

    def _sort(self, keypoints):
        #-----------A
        #-----------
        #C----------B
        # initialize the three targets that we want to found
        sorted_a = cv2.KeyPoint()
        sorted_b = cv2.KeyPoint()
        sorted_c = cv2.KeyPoint()


        # find the minimum x and the minimum y coordinate between the three targets
        minx = min(keypoint.pt[0] for keypoint in keypoints)
        miny = min(keypoint.pt[1] for keypoint in keypoints)

        # sort the targets; c is the target that has minimum x and a is the target that has minimum y

        for keypoint in keypoints:
            if keypoint.pt[0] == minx:
                sorted_c = keypoint
            if keypoint.pt[1] == miny:
                sorted_a = keypoint

        # b is the remaining point
        sorted_b = np.setdiff1d(keypoints, [sorted_a, sorted_c])[0]

        return np.array([sorted_a.pt, sorted_b.pt, sorted_c.pt], dtype=np.float32)

    def _rois_from_img(self,img):
        self._targets = self._find_target_coordinates(img)
        sorted_src_pts = self._sort(self._targets)

        dst_points = np.array([(0,-1),
                               (0,0),
                               (-1,0)], dtype=np.float32)
        wrap_mat = cv2.getAffineTransform(dst_points, sorted_src_pts)

        rectangles = self._make_grid(self._n_cols, self._n_rows,
                                     self._top_margin, self._bottom_margin,
                                     self._left_margin,self._right_margin,
                                     self._horizontal_fill, self._vertical_fill)


        shift = np.dot(wrap_mat, [1,1,0]) - sorted_src_pts[1] # point 1 is the ref, at 0,0
        rois = []
        for i,r in enumerate(rectangles):
            r = np.append(r, np.zeros((4,1)), axis=1)
            mapped_rectangle = np.dot(wrap_mat, r.T).T
            mapped_rectangle -= shift
            ct = mapped_rectangle.reshape((1,4,2)).astype(np.int32)
            cv2.drawContours(img,[ct], -1, (255,0,0),1,cv2.CV_AA)
            rois.append(ROI(ct, idx=i+1))

            #cv2.imshow("dbg",img)
            #cv2.waitKey(0)
        return rois, sorted_src_pts


    def build(self, input):
        """
        Uses an input (image or camera) to build ROIs.
        When a camera is used, several frames are acquired and averaged to build a reference image.

        :param input: Either a camera object, or an image.
        :type input: :class:`~ethoscope.hardware.input.camera.BaseCamera` or :class:`~numpy.ndarray`
        :return: list(:class:`~ethoscope.core.roi.ROI`)
        """

        accum = []
        if isinstance(input, np.ndarray):
            accum = np.copy(input)

        else:
            for i, (_, frame) in enumerate(input):
                accum.append(frame)
                if i  >= 5:
                    break

            accum = np.median(np.array(accum),0).astype(np.uint8)

        try:
            # Detect blobs.
            rois, sorted_targets = self._rois_from_img(accum)

        except Exception as e:
            if not isinstance(input, np.ndarray):
                del input
            raise e

        rois_w_no_value = [r for r in rois if r.value is None]

        if len(rois_w_no_value) > 0:
            rois = self._spatial_sorting(rois)
        else:
            rois = self._value_sorting(rois)

        return rois, sorted_targets



if __name__ == "__main__":

    parser = optparse.OptionParser()
    parser.add_option("-o", "--output", dest="out", help="the output file (eg out.csv   )", type="str",default=None)
    parser.add_option("-i", "--input", dest="input", help="the output video file", type="str")
    #
    parser.add_option("-r", "--result-video", dest="result_video", help="the path to an optional annotated video file."
                                                                "This is useful to show the result on a video.",
                                                                type="str", default=None)

    parser.add_option("-d", "--draw-every",dest="draw_every", help="how_often to draw frames", default=0, type="int")

    parser.add_option("-m", "--mask", dest="mask", help="the mask file with 3 targets", type="str")

    (options, args) = parser.parse_args()

    option_dict = vars(options)

    logging.basicConfig(level=logging.INFO)


    logging.info("Starting Monitor thread")

    cam = MovieVirtualCamera(option_dict ["input"], use_wall_clock=False)

    #my_image = cv2.imread(option_dict['mask'])
    #print option_dict['mask']

    # accum = []
    # for i, (_, frame) in enumerate(cam):
    #     accum.append(frame)
    #     if i  >= 5:
    #         break

    #accum = np.median(np.array(accum),0).astype(np.uint8)
    # cv2.imshow('window', my_image)

    roi_builder = YmazeROIBuilder()
    rois, sorted_targets = roi_builder.build(cam)

    logging.info("Initialising monitor")

    cam.restart()

    metadata = {
                             "machine_id": "None",
                             "machine_name": "None",
                             "date_time": cam.start_time, #the camera start time is the reference 0
                             "frame_width":cam.width,
                             "frame_height":cam.height,
                             "start_target_x":sorted_targets[2][0],
                             "start_target_y":sorted_targets[2][1],
                             "version": "whatever"
                              }
    draw_frames = False
    if option_dict["draw_every"] > 0:
        draw_frames = True

    drawer = YmazeDrawer(video_out='/home/diana/Desktop/example_video3.avi', draw_frames=True, targets=sorted_targets)

    #monit = Monitor(cam, YMazeTracker, rois)
    monit = Monitor(cam, AdaptiveBGModel, rois)


    with SQLiteResultWriter(option_dict["out"], rois, metadata) as rw:
        monit.run(rw, drawer)

    logging.info("Stopping Monitor")
