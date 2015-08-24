import picamera
from os import path
from threading import Thread
import logging

class RecordVideo(Thread):

    def __init__(self, resolution=(640,480), framerate=24, name="myvideo",  PSV_DIR = "/psv_data/results"):
        super(RecordVideo, self).__init__()
        self.camera = picamera.PiCamera()
        self.camera.resolution = resolution
        self.camera.framerate = framerate
        self.save_dir = path.join(PSV_DIR, name + '.h264')

    def run(self):
        try:
            self.camera.start_recording(self.save_dir)
        except Exception as e:
            logging.error("Error or starting video record:"+e)

    def stop(self):
        try:
            self.camera.stop_recording()
            self.camera.close()
            return self.save_dir
        except Exception as e:
            logging.error("Error stopping video record:"+e)
