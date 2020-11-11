from os import path
import traceback
import logging
import time
from ethoscope.web_utils.control_thread import ControlThread, ExperimentalInformation
from ethoscope.utils.description import DescribedObject
import os
import tempfile
import shutil
import threading, queue
import glob
import datetime

#streaming socket
import socket, struct, io

STREAMING_PORT = 8887

 
class cameraCaptureThread(threading.Thread):
    '''
    This opens a PiCamera process for recording or streaming video
    For recording, files are saved in chunks of time duration
    In principle, the two activities couldbe done simultaneously ( see https://picamera.readthedocs.io/en/release-1.12/recipes2.html#capturing-images-whilst-recording )
    but for now they are handled independently
    '''
        
    _VIDEO_CHUNCK_DURATION = 30 * 10
    def __init__(self, video_prefix, video_root_dir, img_path, width, height, fps, bitrate, stream=False):
        self._img_path = img_path
        self._resolution = (width, height)
        self._fps = fps
        self._bitrate = bitrate
        self._video_prefix = video_prefix
        self._video_root_dir = video_root_dir
        self._stream = stream
        
        self.video_file_index = 0
        self.stop_camera_activity = False

        super(cameraCaptureThread, self).__init__()

    @property
    def _get_video_chunk_filename(self):
        '''
        
        '''
        self.video_file_index += 1
        w,h = self._resolution
        video_info= "%ix%i@%i" %(w, h, self._fps)
        
        return '%s_%s_%05d.h264' % (self._video_prefix, video_info, self.video_file_index)

    def run(self):
        '''
        '''
        logging.info("Starting initialisation of the Camera for the activity")

        import picamera

        #camera=picamera.PiCamera(resolution=self._resolution, framerate=self._fps)
        with picamera.PiCamera() as camera:
            camera.resolution = self._resolution
            camera.framerate = self._fps

            #disable auto white balance to address the following issue: https://github.com/raspberrypi/firmware/issues/1167
            #however setting this to off would have to be coupled with custom gains
            #some suggestion on how to set the gains can be found here: https://picamera.readthedocs.io/en/release-1.12/recipes1.html
            #and here: https://github.com/waveform80/picamera/issues/182
            #camera.awb_mode = 'off'
            #camera.awb_gains = (1.8, 1.5)
            camera.awb_mode = 'auto'

            logging.info("PiCamera initialised with resolution %s and fps %s." % (self._resolution, self._fps))
            
            self.start_time = time.time()
            
            if self._stream:

                self.stream = io.BytesIO()

                self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.server_socket.bind(('', STREAMING_PORT))
                self.server_socket.listen(1)
                
                logging.info("Socket stream initiliased")

            else:
                
                camera.start_recording(self._get_video_chunk_filename, bitrate=self._bitrate)
                logging.info("Video recording started.")

    
            while not self.stop_camera_activity:
            
                if not self._stream:
                    camera.wait_recording(2)
                    camera.capture(self._img_path, use_video_port=True, quality=50)
                    
                    if time.time() - self.start_time >= self._VIDEO_CHUNCK_DURATION:
                        camera.split_recording( self._get_video_chunk_filename )
                        self.start_time = time.time()
                            

                if self._stream:
                    
                    #try:
                    while not self.stop_camera_activity:
                        client_conn, client_address = self.server_socket.accept() # blocking call
                        logging.info("Waiting for a connection to start streaming")
                        self.connection = client_conn.makefile('wb')
                        
                        
                        # send jpeg format video stream
                        for _ in camera.capture_continuous(self.stream, 'jpeg', use_video_port = True):
                            try:
                                self.connection.write(struct.pack('<L', self.stream.tell()))
                                self.connection.flush()
                                self.stream.seek(0)
                                self.connection.write(self.stream.read())
                                self.stream.seek(0)
                                self.stream.truncate()
                               
                            
                            except:
                                break

                        #self.connection.write(struct.pack('<L', 0))

                    
                    #except:
                    #    logging.error("Connection reset during streaming")
                    #    pass
                        
                   
                        
                        
            #out of the while loop
            logging.info("Closing camera activity")

            if not self._stream:
                camera.wait_recording(1)
                camera.stop_recording()
            
            if self._stream:

                self.connection.close()
                self.server_socket.close()

                logging.info("Streaming server stopped")

            #camera.close()
            logging.info("Camera closed.")

class GeneralVideoRecorder(DescribedObject):
    _description  = {  "overview": "A video simple recorder",
                            "arguments": [
                                {"type": "number", "name":"width", "description": "The width of the frame","default":1280, "min":480, "max":1980,"step":1},
                                {"type": "number", "name":"height", "description": "The height of the frame","default":960, "min":360, "max":1080,"step":1},
                                {"type": "number", "name":"fps", "description": "The target number of frames per seconds","default":25, "min":1, "max":25,"step":1},
                                {"type": "number", "name":"bitrate", "description": "The target bitrate","default":200000, "min":0, "max":10000000,"step":1000}
                               ]}

    def __init__(self, video_prefix, video_dir, img_path,width=1280, height=960,fps=25,bitrate=200000,stream=False):

        self._stream = stream
        
        #This used to be a process but it's best handled as a thread. See also commit https://github.com/gilestrolab/ethoscope/commit/c2e8a7f656611cc10379c8e93ff4205220c8807a
        self._p = cameraCaptureThread(video_prefix, video_dir, img_path, width, height,fps, bitrate, stream)


    def run(self):
        '''
        '''
        self._p.start()

        #while self._p.is_alive():
        #    time.sleep(.25)
            
    def stop(self):
        '''
        '''
        self._p.stop_camera_activity = True
        if self._stream: 
            try:
                self._p.connection.close()
            except:
                pass
        self._p.join(10)

class HDVideoRecorder(GeneralVideoRecorder):
    _description  = { "overview": "A preset 1920 x 1080, 25fps, bitrate = 5e5 video recorder. "
                                  "At this resolution, the field of view is only partial, "
                                  "so we effectively zoom in the middle of arenas","arguments": []}
    def __init__(self, video_prefix, video_dir, img_path):
        super(HDVideoRecorder, self).__init__(video_prefix, video_dir, img_path,
                                        width=1920, height=1080,fps=25,bitrate=1000000)


class StandardVideoRecorder(GeneralVideoRecorder):
    _description  = { "overview": "A preset 1280 x 960, 25fps, bitrate = 2e5 video recorder.", "arguments": []}
    def __init__(self, video_prefix, video_dir, img_path):
        super(StandardVideoRecorder, self).__init__(video_prefix, video_dir, img_path,
                                        width=1280, height=960,fps=25,bitrate=500000)

class Streamer(GeneralVideoRecorder):
    #hiding the description field will not pass this class information to the node UI
    _hidden_description  = { "overview": "A preset 640 x 480, 25fps, bitrate = 2e5 streamer. Active on port 8008.", "arguments": []}
    def __init__(self, video_prefix, video_dir, img_path):
        super(Streamer, self).__init__(video_prefix, video_dir, img_path,
                                        width=640, height=480,fps=20,bitrate=500000,stream=True)

class ControlThreadVideoRecording(ControlThread):

    _evanescent = False
    _option_dict = {

        "recorder":{
                "possible_classes":[StandardVideoRecorder, HDVideoRecorder, GeneralVideoRecorder, Streamer],
            },
        "experimental_info":{
                        "possible_classes":[ExperimentalInformation],
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
        
        # Metadata
        self._recorder = None
        self._machine_id = machine_id
        self._device_name = name
        self._video_root_dir = ethoscope_dir
        self._tmp_dir = tempfile.mkdtemp(prefix="ethoscope_")


        #todo add 'data' -> how monitor was started to metadata
        self._info = {"status": "stopped",
                        "time": time.time(),
                        "error": None,
                        "log_file": os.path.join(ethoscope_dir, self._log_file),
                        "dbg_img": os.path.join(ethoscope_dir, self._dbg_img_file),
                        "last_drawn_img": os.path.join(self._tmp_dir, self._tmp_last_img_file),
                        "id": machine_id,
                        "name": name,
                        "version": version,
                        "experimental_info": {}
                        }

        self._parse_user_options(data)
        super(ControlThread, self).__init__()

    def _update_info(self):
        if self._recorder is None:
            return
        self._last_info_t_stamp = time.time()


    def _parse_one_user_option(self, field, data):

        try:
            subdata = data[field]
        except KeyError:
            logging.warning("No field %s, using default" % field)
            return None, {}

        Class = eval(subdata["name"])
        kwargs = subdata["arguments"]

        return Class, kwargs


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

            date_time = datetime.datetime.fromtimestamp(self._info["time"])
            formated_time = date_time.strftime('%Y-%m-%d_%H-%M-%S')

            try:
                code = self._info["experimental_info"]["code"]
            except KeyError:
                code = "NA"
                logging.warning("No code field in experimental info")

            file_prefix = "%s_%s_%s" % (formated_time, self._machine_id, code)

            import os
            self._output_video_full_prefix = os.path.join(self._video_root_dir,
                                           self._machine_id,
                                          self._device_name,
                                          formated_time,
                                          file_prefix
                                          )

            try:
                os.makedirs(os.path.dirname(self._output_video_full_prefix))
            except OSError:
                pass

            logging.info("Start recording")
        

            RecorderClass = self._option_dict["recorder"]["class"]
            recorder_kwargs = self._option_dict["recorder"]["kwargs"]

            self._recorder = RecorderClass(video_prefix = self._output_video_full_prefix,
                                       video_dir = self._video_root_dir,
                                       img_path=self._info["last_drawn_img"],**recorder_kwargs)


            if self._recorder.__class__.__name__ == "Streamer":
                self._info["status"] = "streaming"
            else:
                self._info["status"] = "recording"
                
            self._recorder.run()
            logging.warning("recording RUN finished")


        except Exception as e:
            self.stop(traceback.format_exc())

        #for testing purposes
        if self._evanescent:
            import os
            self.stop()
            os._exit(0)


    def stop(self, error=None):

        self._info["status"] = "stopping"
        self._info["time"] = time.time()
        self._info["experimental_info"] = {}

        if self._recorder is not None:
            logging.info("Control thread asking recorder to stop")
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
