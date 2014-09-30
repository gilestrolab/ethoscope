__author__ = 'quentin'


from pysolovideo.tracking.monitor import Monitor
from pysolovideo.tracking.cameras import MovieVirtualCamera
from pysolovideo.tracking.trackers import DummyTracker

cam = MovieVirtualCamera("/home/quentin/Desktop/drosoAdult_short.avi")

monit = Monitor(cam, DummyTracker)
monit.run()

