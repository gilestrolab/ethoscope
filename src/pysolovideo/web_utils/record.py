import picamera
from os import path
from threading import Thread

class RecordVideo(Thread):

    def __init__(self, resolution=(640,480), framerate=24, name="/myvideo",  PSV_DIR = "/psv_data/results"):
        super(RecordVideo, self).__init__()
        self.camera = picamera.PiCamera()
        self.camera.resolution = resolution
        self.camera.framerate = framerate
        self.save_dir = path.join(PSV_DIR, name)


    def run(self):
        try:
            self.camera.start_recording(self.save_dir + '.h264')
        except Exception as e:
            print (e)

    def stop(self):
        self.camera.stop_recording()

