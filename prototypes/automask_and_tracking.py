__author__ = 'quentin'


from pysolovideo.tracking.roi_builders import SleepDepROIBuilder
from pysolovideo.tracking.cameras import MovieVirtualCamera
from pysolovideo.tracking.monitor import Monitor

from pysolovideo.tracking.trackers import AdaptiveBGModel2
from pysolovideo.tracking.interactors import SystemPlaySoundOnStop
from pysolovideo.tracking.interactors import SleepDepInteractor
from pysolovideo.hardware_control.arduino_api import SleepDepriverInterface





# cam = MovieVirtualCamera("/stk/pysolo_video_samples/long_realistic_recording_with_more_motion_in_dark.avi")
# cam = MovieVirtualCamera("/stk/pysolo_video_samples/long_realistic_recording_with_motion.avi")
cam = MovieVirtualCamera("/stk/pysolo_video_samples/long_realistic_recording.avi")
# sdi = SleepDepriverInterface()
roi_builder = SleepDepROIBuilder()
rois = roi_builder(cam)

inters = [SystemPlaySoundOnStop(500 + i * 30) for i in range(len(rois))]
# inters = [SleepDepInteractor(i, sdi) for i in range(len(rois))]





monit = Monitor(cam, AdaptiveBGModel2, rois, interactors= inters)
monit.run()

#