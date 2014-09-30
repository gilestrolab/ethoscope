__author__ = 'quentin'


class Monitor(object):

    def __init__(self, camera, roi_builder):
        self._camera = camera

        self._roi_trackers = roi_builder.build(camera)

        # after calibration, we try to restart camera
        self._camera.restart()

    def run(self):
         for t, frame in self._camera:
             for rt in self._roi_trackers:
                 rt.track(frame)

