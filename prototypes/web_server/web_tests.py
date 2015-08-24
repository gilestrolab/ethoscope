__author__ = 'quentin'

import time
from ethoscope.web_utils.control_thread import ControlThread
# Build ROIs from greyscale image
from ethoscope.tracking.roi_builders import SleepMonitorWithTargetROIBuilder
from ethoscope.tracking.cameras import MovieVirtualCamera

# the robust self learning tracker
from ethoscope.tracking.trackers import AdaptiveBGModel

from ethoscope.tracking.interactors import SystemPlaySoundOnStop


import cv2
if __name__ == "__main__":


    cam = MovieVirtualCamera("/data/pysolo_video_samples/sleepMonitor_5days.avi")




    roi_builder = SleepMonitorWithTargetROIBuilder()

    rois = roi_builder(cam)
    interactors = [SystemPlaySoundOnStop(i*10 + 100) for i,r in enumerate(rois)]

    track = ControlThread(cam,
                    AdaptiveBGModel,
                    rois,
                    out_file="/tmp/test.csv", # save a csv out
                    max_duration=None, # when to stop (in seconds)
                    video_out=None, # when to stop (in seconds)
                    interactors = interactors,
                    draw_results=True, # draw position on image
                    draw_every_n=1) # only draw 1 every 10 frames to save time


    track.start()
    try:
        while True:
            time.sleep(2)
            cv2.imshow("lastFrame", track.last_frame)
    finally:
        track.stop()
        

