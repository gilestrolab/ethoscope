from ethoscope.hardware.input.cameras import *

from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.trackers.multi_fly_tracker import MultiFlyTracker
from ethoscope.drawers.drawers import BaseDrawer

from ethoscope.core.monitor import Monitor
from ethoscope.roi_builders.roi_builders import  DefaultROIBuilder

from ethoscope.utils.io import rawdatawriter

import numpy as np
import cv2

class HaarCutter(BaseDrawer):
    def __init__(self, size=(25,25), prefix="fly_crop", filepath="", interval=20, create_positives=True, create_negatives=True, negatives_per_frame=10, **kwargs):
        """
        This does not annotate frames. Instead, it cuts small images around the contour and saves them to file
        It is useful to generate a learning pool to train a haar cascade
        
        :size:      a tuple describing the size of the cropped area to be saved
        :prefix:    prefix to the filename
        :filepath:  where the files will be saved
        :interval:  how frequently should we save crops (default every 100 frames)
        :create_negatives: 
        :create_positives: 

        """
        self.size = size
        self.prefix = prefix
        self.filepath = filepath
        self.interval = interval
        
        self.create_positives = create_positives
        self.create_negatives = create_negatives
        self.negatives_per_frame = negatives_per_frame
        
        self._counter = 1
        self._crop_counter = [0,0]
        self._info_file = os.path.join(self.filepath, "description.info")
        
        try:
            os.makedirs(os.path.join(self.filepath, "img"))
            os.makedirs(os.path.join(self.filepath, "neg"))
        except OSError as e:
            pass
        
        #super(HaarCutter,self).__init__(*kargs, **kwargs)
        BaseDrawer.__init__(self, **kwargs)
        
    
    def _annotate_frame(self, img, positions, tracking_units):
        """
        """
        
        if self._crop_counter == [0,0]:
            self._avg_bg = np.zeros(img.shape[0:2])
        
        
        self._counter += 1
        if self._counter % self.interval != 0:
            return
        
        if img is None:
            return

        w, h = self.size[0], self.size[1]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        if self.create_negatives:
            ih, iw = img.shape[0:2]
            nw, nh = 4*w, 4*h
            
            for i in range(self.negatives_per_frame):
            
                nx = np.random.randint(0,iw)
                ny = np.random.randint(0,ih)
                
                negative_cropped = gray[ny-nh:ny, nx-nw:nx]
                filename_negative = os.path.join(self.filepath, "neg", "%s_negative_%03d.png" % (self.prefix, self._crop_counter[1]))

                if negative_cropped.shape[:2] == (nw, nh):
                    try:
                        
                        cv2.imwrite(filename_negative, negative_cropped)

                        with open(os.path.join(self.filepath, "negative.txt"), "a") as negative_info:
                            negative_info.write("neg/%s\n" % os.path.split(filename_negative)[1] )

                        self._crop_counter[1] += 1

                    except Exception as e:
                        print ("Error saving the negative file")

        if self.create_positives:

            for track_u in tracking_units:

                try:
                    pos_list = positions[track_u.roi.idx]
                    
                except KeyError:
                    continue

                for pos in pos_list:
                    
                    xc, yc = pos["x"], pos["y"]
                    x = int(xc - w/2)
                    y = int(yc - h/2)

                    filename_positive = os.path.join(self.filepath, "img", "%s_positive_%03d.png" % (self.prefix, self._crop_counter[0]))
                    positive_cropped = gray[y:y+h, x:x+w]

                    if positive_cropped.shape[:2] == (w, h):
                        try:
                            cv2.imwrite(filename_positive, positive_cropped)

                            with open(self._info_file, "a") as info:
                                info.write("img/%s\t1\t0\t0\t%s\t%s\n" % ( os.path.split(filename_positive)[1], w, h))
                                
                            self._crop_counter[0] += 1
        
                        except Exception as e:
                            print ("Error saving the positive file")
        
        print("Saved %s positives and %s negatives so far" % (self._crop_counter[0], self._crop_counter[1]))



# the input video - we work on an mp4 acquired with the Record function
positive_video = "/home/gg/Downloads/test_video.mp4"
negative_video = "/home/gg/Downloads/whole_2020-08-25_13-10-07_2020f8bceb334c1c84518f62359ddc76_emptyarena_1280x960@25_00000.mp4"



camera = MovieVirtualCamera(negative_video)

# we use the default drawer and we show the video as we track - this is useful to understand how things are going
# disabling the video will speed things up
#drawer = DefaultDrawer(draw_frames = True, video_out = output_video, video_out_fps=25)
drawer = HaarCutter(filepath="/home/gg/haar_training", draw_frames = False, create_positives=False, create_negatives=True, interval=10, negatives_per_frame=30)


# One Big ROI using the Default ROIBuilder
roi_builder = DefaultROIBuilder()
rois = roi_builder.build(camera)

# Starts the tracking monitor
monit = Monitor(camera, MultiFlyTracker, rois, stimulators=None )
monit.run(drawer=drawer, result_writer = None)
