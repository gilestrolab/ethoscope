__author__ = 'quentin'


from pysolovideo.tracking.monitor import Monitor
from pysolovideo.tracking.cameras import MovieVirtualCamera
from pysolovideo.tracking.trackers import AdaptiveMOGTracker
from pysolovideo.tracking.interactors import SystemPlaySoundOnStop

# cam = MovieVirtualCamera("/home/quentin/Desktop/drosoAdult_short.avi")
cam = MovieVirtualCamera("/stk/pysolo_video_samples/singleDamTube2_150min_night.avi")

inter = SystemPlaySoundOnStop()
monit = Monitor(cam, AdaptiveMOGTracker, interactors=[inter])
monit.run()

