__author__ = 'quentin'


from ethoscope.tracking.monitor import Monitor
from ethoscope.tracking.cameras import MovieVirtualCamera
from ethoscope.tracking.trackers import AdaptiveMOGTracker
from ethoscope.tracking.interactors import SystemPlaySoundOnStop

# cam = MovieVirtualCamera("/home/quentin/Desktop/drosoAdult_short.avi")
cam = MovieVirtualCamera("/stk/pysolo_video_samples/singleDamTube2_150min_night.avi")

inter = SystemPlaySoundOnStop(1000)
monit = Monitor(cam, AdaptiveMOGTracker, interactors=[inter])
monit.run()

