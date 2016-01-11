from os import path
from threading import Thread
import traceback
import logging

try:
    import picamera
except:
    logging.warning("Could not load picamera module")



class RecordVideo(Thread):

    def __init__(self, resolution=(1280,960), framerate=25, bitrate=200000, name="myvideo",  ETHOSCOPE_DIR = "/ethoscope_data/results"):
        super(RecordVideo, self).__init__()
        self.camera = picamera.PiCamera()
        self.camera.resolution = resolution
        self.camera.framerate = framerate
        self._bitrate=bitrate
        self.save_dir = path.join(ETHOSCOPE_DIR, name + '.h264')

    def run(self):
        try:
            self.camera.start_recording(self.save_dir,bitrate=self._bitrate)

        except Exception as e:
            logging.error("Error or starting video record:" + traceback.format_exc(e))

    def stop(self):
        try:
            self.camera.stop_recording()
            self.camera.close()
            return self.save_dir
        except Exception as e:
            logging.error("Error stopping video record:" + traceback.format_exc(e))
