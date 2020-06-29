from os import path
from threading import Thread
import traceback
import logging
import time

try:
    import picamera
except:
    logging.warning("Could not load picamera module")



class RecordVideo(Thread):

    def __init__(self, data=None, name="myvideo",  ETHOSCOPE_DIR = "/ethoscope_data/results"):

        #TODO parse data here
        resolution=(1280,960)
        framerate=25
        bitrate=200000
        # self._is_recording = False
        super(RecordVideo, self).__init__()
        self.camera = picamera.PiCamera()
        self.camera.resolution = resolution
        self.camera.framerate = framerate
        self._bitrate=bitrate
        self.save_dir = path.join(ETHOSCOPE_DIR, name + '.h264')

    def run(self):
        self._is_recording = True
        try:
            self.camera.start_recording(self.save_dir,bitrate=self._bitrate)

            while not self.camera.closed:
                time.sleep(2)
                print("capturing here")

        except Exception as e:
            logging.error("Error or starting video record:" + traceback.format_exc())
        finally:
            self._is_recording = False

    def stop(self):
        try:

            self.camera.stop_recording()
            self.camera.close()
            return self.save_dir
        except Exception as e:
            logging.error("Error stopping video record:" + traceback.format_exc())


