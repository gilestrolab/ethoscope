__author__ = 'quentin'


from pysolovideo.tracking.cameras import V4L2Camera
from pysolovideo.hardware_control.arduino_api import SleepDepriverInterface
from pysolovideo.tracking.roi_builders import SleepDepROIBuilder
from pysolovideo.tracking.interactors import SleepDepInteractor
from pysolovideo.tracking.monitor import Monitor
from pysolovideo.tracking.trackers import AdaptiveBGModel







cam = V4L2Camera(0, target_fps=3)
sdi = SleepDepriverInterface()
roi_builder = SleepDepROIBuilder()
rois = roi_builder(cam)
inters = [SleepDepInteractor(i, sdi) for i in range(len(rois))]
monit = Monitor(cam, AdaptiveBGModel, rois, interactors= inters,draw_results=True, draw_every_n=10)
monit.run()

#