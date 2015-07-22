import picamera
from threading import Thread

class RecordVideo(Thread):

    def __init__(self, resolution=(640,480), framerate=24, name="myvideo",  PSV_DIR = "/psv_data/results"):
        self.camera = picamera.PiCamera()
        self.camera.resolution = resolution
        self.camera.framerate = framerate
        self.name = name
        self.psv_dir = PSV_DIR
        super(ControlThread, self).__init__()

    def start(self):
        try:
            self.camera.start_recording(self.psv_dir + self.name + '.h264')
        except Exception as e:
            print (e)

    def stop(self):
        self.camera.stop_recording()

