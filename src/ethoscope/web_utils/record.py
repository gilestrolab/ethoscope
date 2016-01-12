from os import path
from threading import Thread
import traceback
import logging
import time
from ethoscope.web_utils.control_thread import ControlThread, ExperimentalInformations
from ethoscope.utils.description import DescribedObject
import os
import tempfile
import shutil

try:
    import picamera
except:
    logging.warning("Could not load picamera module")



class RecordingThread(Thread):
    def __init__(self, w,h, last_img_path, name="myvideo",  ETHOSCOPE_DIR = "/ethoscope_data/results"):

        #TODO parse data here
        resolution=(w,h)
        framerate=25
        bitrate=200000
        # self._is_recording = False
        super(RecordingThread, self).__init__()
        self.camera = picamera.PiCamera()
        self.camera.resolution = resolution
        self.camera.framerate = framerate
        self._bitrate=bitrate
        self._is_recording = False
        self._last_img_path = last_img_path
        self.save_dir = path.join(ETHOSCOPE_DIR, name + '.h264')

    def run(self):
        self._is_recording = True
        try:
            self.camera.start_recording(self.save_dir,bitrate=self._bitrate)
            while self._is_recording:
                self.camera.wait_recording(2)
                self.camera.capture(self._last_img_path, use_video_port=True)


        except Exception as e:
            logging.error("Error or starting video record:" + traceback.format_exc(e))
        finally:
            self.camera.wait_recording(1)
            self.camera.stop_recording()
            self.camera.close()


    def stop(self):
        self._is_recording = False
        return self.save_dir





class FakeRecordingThread(Thread):
    def __init__(self, w,h,last_img_path, name="myvideo",  ETHOSCOPE_DIR = "/ethoscope_data/results"):

        #TODO parse data here
        resolution=(w,h)
        framerate=25
        bitrate=200000
        self._last_img_path = last_img_path
        # self._is_recording = False
        super(FakeRecordingThread, self).__init__()

        self._bitrate=bitrate
        self._is_recording = False
        self.save_dir = path.join(ETHOSCOPE_DIR, name + '.h264')

    def run(self):
        self._is_recording = True
        try:

            while self._is_recording:
                time.sleep(2)
                print "capturing, and saving at "+ self._last_img_path
        except Exception as e:
            logging.error("Error or starting video record:" + traceback.format_exc(e))
        finally:
            print "stop recording"

    def stop(self):
        print "stop recording Thread"
        self._is_recording = False
        return self.save_dir



class VideoRecorder(DescribedObject):
    _description  = {   "overview": "A video simple recorder",
                            "arguments": [
                                {"type": "number", "name":"width", "description": "The width of the frame","default":1280, "min":480, "max":1980,"step":1},
                                {"type": "number", "name":"height", "description": "The height of the frame","default":960, "min":360, "max":1080,"step":1}
                               ]}

    def __init__(self, img_path,width=1280, height=960):

        self._recording_thread = RecordingThread(h=height, w=width, last_img_path=img_path)

    def run(self):
        self._recording_thread.run()

    def stop(self):
        print "stop video recorder"
        self._recording_thread.stop()



class ControlThreadVideoRecording(ControlThread):

    _evanescent = False
    _option_dict = {

        "recorder":{
                "possible_classes":[VideoRecorder],
            },
        "experimental_info":{
                        "possible_classes":[ExperimentalInformations],
                }
     }
    for k in _option_dict:
        _option_dict[k]["class"] =_option_dict[k]["possible_classes"][0]
        _option_dict[k]["kwargs"] ={}


    _tmp_last_img_file = "last_img.jpg"
    _dbg_img_file = "dbg_img.png"
    _log_file = "ethoscope.log"

    def __init__(self, machine_id, name, version, ethoscope_dir, data=None, *args, **kwargs):

        # for FPS computation
        self._last_info_t_stamp = 0
        self._last_info_frame_idx = 0
        self._recorder = None

        try:
            os.makedirs(ethoscope_dir)
        except OSError:
            pass

        self._tmp_dir = tempfile.mkdtemp(prefix="ethoscope_")

        #todo add 'data' -> how monitor was started to metadata
        self._info = {  "status": "stopped",
                        "time": time.time(),
                        "error": None,
                        "log_file": os.path.join(ethoscope_dir, self._log_file),
                        "dbg_img": os.path.join(ethoscope_dir, self._dbg_img_file),
                        "last_drawn_img": os.path.join(self._tmp_dir, self._tmp_last_img_file),
                        "id": machine_id,
                        "name": name,
                        "version": version,
                        "user_options": self._get_user_options(),
                        "experimental_info": {}
                        }

        self._parse_user_options(data)
        super(ControlThread, self).__init__()

    def _update_info(self):
        if self._recorder is None:
            return
        # self._recorder.capture(self._info["last_drawn_img"])
        self._last_info_t_stamp = time.time()




    def _parse_one_user_option(self,field, data):

        try:
            subdata = data[field]
        except KeyError:
            logging.warning("No field %s, using default" % field)
            return None, {}

        Class = eval(subdata["name"])
        kwargs = subdata["arguments"]

        return Class, kwargs


    def _parse_user_options(self,data):

        if data is None:
            return
        #FIXME DEBUG
        logging.warning("Starting control thread with data:")
        logging.warning(str(data))

        for key in self._option_dict.iterkeys():

            Class, kwargs = self._parse_one_user_option(key, data)
            # when no field is present in the JSON config, we get the default class

            if Class is None:

                self._option_dict[key]["class"] = self._option_dict[key]["possible_classes"][0]
                self._option_dict[key]["kwargs"] = {}
                continue

            self._option_dict[key]["class"] = Class
            self._option_dict[key]["kwargs"] = kwargs

    def run(self):

        try:
            self._info["status"] = "initialising"
            logging.info("Starting Monitor thread")

            self._info["error"] = None


            self._last_info_t_stamp = 0
            self._last_info_frame_idx = 0

            ExpInfoClass = self._option_dict["experimental_info"]["class"]
            exp_info_kwargs = self._option_dict["experimental_info"]["kwargs"]
            self._info["experimental_info"] = ExpInfoClass(**exp_info_kwargs).info_dic
            self._info["time"] = time.time()


            logging.info("Start recording")

            RecorderClass = self._option_dict["recorder"]["class"]
            recorder_kwargs = self._option_dict["recorder"]["kwargs"]
            self._recorder = RecorderClass(img_path=self._info["last_drawn_img"],**recorder_kwargs)
            self._info["status"] = "recording"
            self._recorder.run()


        except Exception as e:
            self.stop(traceback.format_exc(e))

        #for testing purposes
        if self._evanescent:
            import os
            self.stop()
            os._exit(0)


    def stop(self, error=None):
        self._info["status"] = "stopping"
        self._info["time"] = time.time()
        self._info["experimental_info"] = {}

        logging.info("Stopping monitor")
        if self._recorder is not None:
            print "control thread stoping recorder"
            self._recorder.stop()
            self._recorder = None

        self._info["status"] = "stopped"
        self._info["time"] = time.time()
        self._info["error"] = error


        if error is not None:
            logging.error("Recorder closed with an error:")
            logging.error(error)
        else:
            logging.info("Recorder closed all right")

    def __del__(self):
        self.stop()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def set_evanescent(self, value=True):
        self._evanescent = value

