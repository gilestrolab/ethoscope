from ethoscope.core.monitor import Monitor
import cv2
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel, ObjectModel
from ethoscope.utils.io import SQLiteResultWriter
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.drawers.drawers import DefaultDrawer
import numpy as np
from math import log10

from ethoscope.roi_builders.img_roi_builder import ImgMaskROIBuilder



class LarveaModel(ObjectModel):
    def __init__(self):

        self._features_header = [
            "fg_model_area",
            "fg_model_height",
            #"fg_model_aspect_ratio",
            "fg_model_mean_grey"
        ]


        self._is_ready = True
        self._roi_img_buff = None
        self._mask_img_buff = None
        self._img_buff_shape = np.array([0,0])

        self._last_updated_time = 0
        # If the model is not updated for this duration, it is reset. Patches #39
        self._max_unupdated_duration = 1 *  60 * 1000.0 #ms

    @property
    def is_ready(self):
        return self._is_ready
    @property
    def features_header(self):
        return self._features_header


    def update(self, img, contour,time):
        pass

    def distance(self, features,time):
        ar, h, col = features
        if not(20 < h < 75):
            return 10**10
        return 0


    def compute_features(self, img, contour):
        x,y,w,h = cv2.boundingRect(contour)

        if self._roi_img_buff is None or np.any(self._roi_img_buff.shape < img.shape[0:2]) :
            # dynamically reallocate buffer if needed
            self._img_buff_shape[1] =  max(self._img_buff_shape[1],w)
            self._img_buff_shape[0] =  max(self._img_buff_shape[0], h)

            self._roi_img_buff = np.zeros(self._img_buff_shape, np.uint8)
            self._mask_img_buff = np.zeros_like(self._roi_img_buff)

        sub_mask = self._mask_img_buff[0 : h, 0 : w]

        sub_grey = self._roi_img_buff[ 0 : h, 0: w]

        cv2.cvtColor(img[y : y + h, x : x + w, :],cv2.COLOR_BGR2GRAY,sub_grey)
        sub_mask.fill(0)

        cv2.drawContours(sub_mask,[contour],-1, 255,-1,offset=(-x,-y))
        mean_col = cv2.mean(sub_grey, sub_mask)[0]


        (_,_) ,(width,height), angle  = cv2.minAreaRect(contour)
        width, height= max(width,height), min(width,height)
        ar = ((height+1) / (width+1))

        features = np.array([log10(cv2.contourArea(contour) + 1.0),
                            height + 1,
                            #sqrt(ar),
                            #instantaneous_speed +1.0,
                            mean_col +1
                            # 1.0
                             ])

        return features


class LarveaTracker(AdaptiveBGModel):
    fg_model = LarveaModel()
    _runavg = None
    def _pre_process_input_minimal(self, img, mask, t, darker_fg=False):
        out = super(LarveaTracker, self)._pre_process_input_minimal(img, mask, t, darker_fg)
        cv2.medianBlur(out, 5, out)
        #cv2.threshold(out, 230, 255, cv2.THRESH_TOZERO, dst=out)

        if self._runavg is None:
            self._runavg = out.astype(np.float32)


        #tmp = out.astype(np.float32)
        cv2.accumulateWeighted(out,self._runavg, 0.3)
        out = self._runavg.astype(np.uint8)
        #cv2.imshow("test",self._runavg)
        cv2.imshow("dbg", out)
        return out





# change these three variables according to how you name your input/output files
INPUT_VIDEO = "/data/ethoscope_ref_videos/agar_conc_test/2pc_agarovernight_resized.mp4"
OUTPUT_VIDEO = "/tmp/2pc_agarovernight_resized_processed.avi"
OUTPUT_DB = "/tmp/2pc_agarovernight_resized.db"
MASK = "/data/ethoscope_ref_videos/agar_conc_test/2pc_agarovernight_resized.png"



# We use a video input file as if it was a "camera"
cam = MovieVirtualCamera(INPUT_VIDEO, drop_each=1)

# here, we generate ROIs automatically from the targets in the images
roi_builder = ImgMaskROIBuilder(MASK)
rois = roi_builder.build(cam)
# Then, we go back to the first frame of the video
cam.restart()

# we use a drawer to show inferred position for each animal, display frames and save them as a video
drawer = DefaultDrawer(OUTPUT_VIDEO, draw_frames = True)
# We build our monitor
monitor = Monitor(cam, LarveaTracker, rois)

# Now everything ius ready, we run the monitor with a result writer and a drawer
with SQLiteResultWriter(OUTPUT_DB, rois) as rw:
 monitor.run(rw,drawer)
