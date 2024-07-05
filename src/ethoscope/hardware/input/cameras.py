__author__ = 'quentin'

import time, datetime
import logging
import os
from ethoscope.utils.debug import EthoscopeException
import threading, queue
import traceback

import cv2
import numpy as np
try:
    from cv2.cv import CV_CAP_PROP_FRAME_WIDTH as CAP_PROP_FRAME_WIDTH
    from cv2.cv import CV_CAP_PROP_FRAME_HEIGHT as CAP_PROP_FRAME_HEIGHT
    from cv2.cv import CV_CAP_PROP_FRAME_COUNT as CAP_PROP_FRAME_COUNT
    from cv2.cv import CV_CAP_PROP_POS_MSEC as CAP_PROP_POS_MSEC
    from cv2.cv import CV_CAP_PROP_FPS as CAP_PROP_FPS

except ImportError:
    from cv2 import CAP_PROP_FRAME_WIDTH, CAP_PROP_FRAME_HEIGHT, CAP_PROP_FRAME_COUNT, CAP_PROP_POS_MSEC, CAP_PROP_FPS

try:
    import picamera
    USE_PICAMERA2 = False
except ImportError:
    try:
        import picamera2
        USE_PICAMERA2 = True
    except ImportError:
        USE_PICAMERA2 = None  # None or some other value to indicate both imports failed

class BaseCamera(object):
    capture = None
    resolution = None
    _frame_idx = 0

    def __init__(self, drop_each=1, max_duration=None, *args, **kwargs):
        """
        The template class to generate and use video streams.

        :param drop_each: keep only ``1/drop_each``'th frame
        :param max_duration: stop the video stream if ``t > max_duration`` (in seconds).
        :param args: additional arguments
        :param kwargs: additional keyword arguments
        """

        self._drop_each = drop_each
        self._max_duration = max_duration

    def __exit__(self):
        logging.info("Closing camera")
        self._close()
        
    def _close(self):
        pass

    def __iter__(self):
        """
        Iterate thought consecutive frames of this camera.

        :return: the time (in ms) and a frame (numpy array).
        :rtype: (int, :class:`~numpy.ndarray`)
        """
        at_least_one_frame = False
        while True:
            if self.is_last_frame() or not self.is_opened():
                if not at_least_one_frame:
                    raise EthoscopeException("Camera could not read the first frame")
                break
            t,out = self._next_time_image()
            if out is None:
                break
            t_ms = int(1000*t)
            at_least_one_frame = True

            if (self._frame_idx % self._drop_each) == 0:
                yield t_ms,out

            if self._max_duration is not None and t > self._max_duration:
                break

    @property
    def resolution(self):
        """

        :return: The resolution of the camera W x H.
        :rtype: (int, int)
        """
        return self._resolution

    @property
    def width(self):
        """
        :return: the width of the returned frames
        :rtype: int
        """
        return self._resolution[0]

    @property
    def height(self):
        """
        :return: the height of the returned frames
        :rtype: int
        """
        return self._resolution[1]

    def _next_time_image(self):
        time = self._time_stamp()
        im = self._next_image()
        self._frame_idx += 1
        return time, im

    def is_last_frame(self):
        raise NotImplementedError

    def _next_image(self):
        raise NotImplementedError

    def _time_stamp(self):
        raise NotImplementedError

    def is_opened(self):
        raise NotImplementedError

    def restart(self):
        """
        Restarts a camera (also resets time).
        :return:
        """
        raise NotImplementedError


class MovieVirtualCamera(BaseCamera):
    _description = {"overview":  "Class to acquire frames from a video file.",
                    "arguments": [
                                    {"type": "filepath", "name": "path", "description": "Will be looking for videos in /ethoscope_data/upload/video/","default":""},
                                   ]}
                                   

    def __init__(self, path, use_wall_clock = False, *args, **kwargs ):
        """
        Class to acquire frames from a video file.

        :param path: the path of the video file
        :type path: str
        :param use_wall_clock: whether to use the real time from the machine (True) or from the video file (False).\
            The former can be useful for prototyping.
        :type use_wall_clock: bool
        :param args: additional arguments.
        :param kwargs: additional keyword arguments.
        """

        self.canbepickled = False #cv2.videocapture object cannot be serialized, hence cannot be picked
        self.isPiCamera = True


        #print "path", path
        self._frame_idx = 0
        self._path = path
        self._use_wall_clock = use_wall_clock


        if not (isinstance(path, str) or isinstance(path, str)):
            raise EthoscopeException("path to video must be a string")
        if not os.path.exists(path):
            raise EthoscopeException("'%s' does not exist. No such file" % path)

        self.capture = cv2.VideoCapture(path) 
        w = self.capture.get(CAP_PROP_FRAME_WIDTH)
        h = self.capture.get(CAP_PROP_FRAME_HEIGHT)
        self._total_n_frames =self.capture.get(CAP_PROP_FRAME_COUNT)
        if self._total_n_frames == 0.:
            self._has_end_of_file = False
        else:
            self._has_end_of_file = True

        self._resolution = (int(w),int(h))

        super(MovieVirtualCamera, self).__init__(*args, **kwargs)

        # emulates v4l2 (real time camera) from video file
        if self._use_wall_clock:
            self._start_time = time.time()
        else:
            self._start_time = 0

    @property
    def start_time(self):
        return self._start_time

    @property
    def path(self):
        return self._path

    def is_opened(self):
        return True

    def restart(self):
        self.__init__(self._path, use_wall_clock=self._use_wall_clock, drop_each=self._drop_each, max_duration = self._max_duration)


    def _next_image(self):
        _, frame = self.capture.read()
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    def _time_stamp(self):
        if self._use_wall_clock:
            now = time.time()
            return now - self._start_time
        time_s = self.capture.get(CAP_PROP_POS_MSEC) / 1e3
        return time_s

    def is_last_frame(self):
        if self._has_end_of_file and self._frame_idx >= self._total_n_frames:
            return True
        return False

    def _close(self):
        self.capture.release()


class V4L2Camera(BaseCamera):
    _description = {"overview": "Class to acquire frames from the V4L2 default interface (e.g. a webcam).",
                    "arguments": [
                    {"type": "number", "min": 0, "max": 4, "step": 1, "name": "device", "description": "The device to be open", "default":0},
                    ]}
    
    def __init__(self, device=0, target_fps=5, target_resolution=(960,720), *args, **kwargs):
        """
        class to acquire stream from a video for linux compatible device (v4l2).

        :param device: The index of the device, or its path.
        :type device: int or str
        :param target_fps: the desired number of frames par second (FPS)
        :type target_fps: int
        :param target_fps: the desired resolution (W x H)
        :param target_resolution: (int,int)
        :param args: additional arguments
        :param kwargs: additional keyword arguments
        """
        
        self.canbepickled = False
        self.isPiCamera = False

        self.capture = cv2.VideoCapture(device)
        
        #gst_str = ("v4l2src device=/dev/video{} ! video/x-raw,width=(int){},height=(int){},framerate=(fraction){}/1 ! videoconvert ! video/x-raw,format=BGR ! queue ! appsink drop=1").format(device, target_resolution[0], target_resolution[1], target_fps)
        #self.capture = cv2.VideoCapture(gst_str, cv2.CAP_GSTREAMER)
        
        self._warm_up()

        w, h = target_resolution
        if w <0 or h <0:
            self.capture.set(CAP_PROP_FRAME_WIDTH, 99999)
            self.capture.set(CAP_PROP_FRAME_HEIGHT, 99999)
        else:
            self.capture.set(CAP_PROP_FRAME_WIDTH, w)
            self.capture.set(CAP_PROP_FRAME_HEIGHT, h)

        if not isinstance(target_fps, int):
            raise EthoscopeException("FPS must be an integer number")

        if target_fps < 2:
            raise EthoscopeException("FPS must be at least 2")
        self.capture.set(CAP_PROP_FPS, target_fps)
    
        self._target_fps = float(target_fps)
        self.fps = float(target_fps)
        
        time.sleep(1)
        _, first_frame = self.capture.read()

        # preallocate image buffer => faster
        if first_frame is None:
            raise EthoscopeException("Error whist retrieving video frame. Got None instead. Camera not plugged?")

        assert(len(first_frame.shape) >1)

        self._resolution = (first_frame.shape[1], first_frame.shape[0])
        if self._resolution != target_resolution:
            if w > 0 and h > 0:
                logging.warning('Target resolution "%s" could NOT be achieved. Effective resolution is "%s"' % (target_resolution, self._resolution ))
            else:
                logging.info('Maximal effective resolution is "%s"' % str(self._resolution))

        self._frame = first_frame

        super(V4L2Camera, self).__init__(*args, **kwargs)
        self._start_time = time.time()

    def _warm_up(self):
        logging.info("%s is warming up" % (str(self)))
        time.sleep(2)

    def restart(self):
        self._frame_idx = 0
        self._start_time = time.time()

    def is_opened(self):
        return self.capture.isOpened()

    def is_last_frame(self):
        return False

    def _time_stamp(self):
        now = time.time()
        # relative time stamp
        return now - self._start_time
    
    @property
    def start_time(self):
        return self._start_time

    def _close(self):
        self.capture.release()
        
    def _next_image(self):
        '''
        Image iterator. Tries to calculate the actual FPS and approach the desired FPS target
        '''
        if self._frame_idx > 0 :
            expected_time =  self._start_time + self._frame_idx / self._target_fps
            now = time.time()
            self.fps = self._frame_idx/(now - self._start_time)

            to_sleep = expected_time - now

            # Warnings if the fps is so high that we cannot grab fast enough
            if to_sleep < 0:
                if self._frame_idx % 5000 == 0:
                    logging.warning("The target FPS (%f) could not be reached. Effective FPS is about %f" % (self._target_fps, self._frame_idx/(now - self._start_time)))
                self.capture.grab()

            # we simply drop frames until we go above expected time
            while now < expected_time:
                self.capture.grab()
                now = time.time()

        else:
            self.capture.grab()
        
        self.capture.retrieve(self._frame)
        
        if len(self._frame.shape) == 3:
            return cv2.cvtColor(self._frame, cv2.COLOR_BGR2GRAY)
        
        return self._frame

class PiFrameGrabber(threading.Thread):

    def __init__(self, target_fps, target_resolution, queue, stop_queue, video_prefix=None, quality=20, *args, **kwargs):
        """
        Class to grab frames from pi camera. Designed to be used within :class:`~ethoscope.hardware.camreras.camreras.OurPiCameraAsync`
        This allows to get frames asynchronously as acquisition is a bottleneck.

        :param target_fps: desired fps
        :type target_fps: int
        :param target_resolution: the desired resolution (w, h)
        :type target_resolution: (int, int)
        :param queue: a queue that stores frame and makes them available to the parent process
        :type queue: :class:`~threading.JoinableQueue`
        :param stop_queue: a queue that can stop the async acquisition
        :type stop_queue: :class:`~threading.JoinableQueue`
        :param args: additional arguments
        :param kwargs: additional keyword arguments
        """

        self._acquisition_speed = 0
        self._queue = queue
        self._stop_queue = stop_queue
        self._target_fps = target_fps
        self._target_resolution = target_resolution
        
        # This stuff should not be here in principle but the video recording
        # must be done from the camera class or else it will be to slow
        self._record_video = video_prefix is not None
        self._video_prefix = video_prefix
        self._VIDEO_CHUNCK_DURATION = 300
        self._PREVIEW_REFRESH_TIME = 5
        self._file_index = 0

        # Specifies the quality that the encoder should attempt to maintain. 
        # For the 'h264' format, use values between 10 and 40 where 10 is extremely high quality, and 40 is extremely low 
        # (20-25 is usually a reasonable range for H.264 encoding)
        self.video_quality = quality

        super(PiFrameGrabber, self).__init__()

    def _save_camera_info(self, camera_info, save_path='/etc/picamera-version'):
        """
        PINoIR v1 with picamera
        {'IFD0.Model': 'RP_ov5647', 'IFD0.Make': 'RaspberryPi'}
        
        PINoIR v2 with picamera
        {'IFD0.Model': 'RP_imx219', 'IFD0.Make': 'RaspberryPi'}

        v2 with picamera2
        {'Model': 'imx219', 'Location': 2, 'Rotation': 180, 'Id': '/base/soc/i2c0mux/i2c@1/imx219@10', 'Num': 0}
        
        We save this information on the filesystem so that it can be retrieved by the system if the system needs to know
        which camera we are using - this is not ideal but accessing IFD0 from another instance creates weird issues
        """

        #double the dictionary key for compatibility between picamera and picamera2
        if "Model" in camera_info:
            camera_info["IFD0.Model"] = camera_info["Model"]

        logging.info(f"Detected camera {camera_info}")
        with open(save_path, 'w') as outfile:
            print(camera_info, file=outfile)

    def _get_video_chunk_filename(self, fps=None, ext='h264'):
        
        fps = fps or 0
        self._file_index += 1
        w,h = self._target_resolution
        video_info= "%ix%i@%ifps-%iq" %(w, h, fps, self.video_quality)
        chunk_file_name = '%s_%s_%05d.%s' % (self._video_prefix, video_info, self._file_index, ext)
        return chunk_file_name

    def run (self):
        """
        Initialise pi camera, get frames, convert them fo greyscale, and make them available in a queue.
        Run stops if the _stop_queue is not empty.
        """

        #try:
        # lazy import should only use those on devices
        
        # Warning: the following causes a major issue with Python 3.8.1
        # https://www.bountysource.com/issues/86094172-python-3-8-1-typeerror-vc_dispmanx_element_add-argtypes-item-9-in-_argtypes_-passes-a-union-by-value-which-is-unsupported
        # this should now be fixed in Python 3.8.2 (6/5/2020)
        
        import picamera
        import picamera.array

        # try:
        with picamera.PiCamera(
                        #sensor_mode = 1, #https://picamera.readthedocs.io/en/release-1.13/fov.html#sensor-modes
                        resolution = self._target_resolution,
                        framerate = self._target_fps
        ) as capture:

            self._save_camera_info (capture.exif_tags)
            w, h = capture.resolution[0], capture.resolution[1]

            if self._record_video:

                self._video_time = time.time()

                frame = np.empty((h, w, 3), dtype=np.uint8)
                capture.start_recording( self._get_video_chunk_filename(fps=capture.framerate) , format = 'h264', quality = self.video_quality)

                while self._stop_queue.empty():        
                    capture.capture(frame, format = 'bgr', use_video_port=True)

                    self._queue.put(frame)

                    capture.wait_recording(self._PREVIEW_REFRESH_TIME) 

                    if time.time() - self._video_time >= self._VIDEO_CHUNCK_DURATION:
                        capture.split_recording( self._get_video_chunk_filename( fps=capture.framerate ) )
                        self._video_time = time.time()
                
                capture.stop_recording()



            else: #regular acquisition: all frames go in the queue

                #stream = picamera.array.PiRGBArray(capture, size=self._target_resolution)
                # Capturing in YUV then taking the first dimension is the fastest way to directly get grayscale images
                # https://github.com/raspberrypi/picamera2/issues/698
                
                video_stream = picamera.array.PiYUVArray(capture, size=self._target_resolution)

                time.sleep(0.2) # sleep 200ms to allow the camera to warm up

                # video port True gives 19 FPS; False gives 4
                for frame in capture.capture_continuous(video_stream, format='yuv', use_video_port=True):

                    if not self._stop_queue.empty():
                        logging.info("The stop queue is not empty. This signals it is time to stop acquiring frames")
                        self._stop_queue.get()
                        self._stop_queue.task_done()
                        break

                    video_stream.seek(0)
                    self._queue.put(frame.array[:, :, 0]) #gets the first channel (Y) to extract greyscale


        # except:
        #     logging.warning("Some problem acquiring frames from the camera")
                    
        # finally:

        #     self._queue.task_done() # this tell the parent the thread can be closed
        #     logging.warning("Camera Frame grabber stopped acquisition cleanly")


class PiFrameGrabber2(PiFrameGrabber):
    """
    Same as PiFrameGrabber but uses picamera2
    """

    def run (self):
        """
        Initialise pi camera, get frames, convert them fo greyscale, and make them available in a queue.
        Run stops if the _stop_queue is not empty.
        """

        from picamera2 import Picamera2, MappedArray

        Picamera2.set_logging(Picamera2.ERROR)

        with Picamera2() as capture:
           
            # The appropriate size of the image acquisition is tricky and depends on the actual hardware. 
            # With IMX219 640x480 will not return the full FoV. 960x720 does.
            # See https://picamera.readthedocs.io/en/release-1.13/fov.html for a full description


            w, h = self._target_resolution

            config = capture.create_video_configuration(
                            main = { 'size' : (w, h), 'format': 'YUV420' },
                            buffer_count = 2, #Still image capture normally configures only a single buffer, as this is all you need. But if you're doing some form of burst capture, increasing the buffer count may enable the application to receive images more quickly.
                            controls = { 'FrameRate': self._target_fps },
                            )
            capture.configure(config)

            self._save_camera_info (capture.global_camera_info()[0])

            if self._record_video:

                from picamera2.encoders import H264Encoder
                encoder = H264Encoder(bitrate=10000000)

                self._video_time = time.time()
                self._refresh_interval = time.time()

                capture.start()
                capture.start_encoder(encoder, self._get_video_chunk_filename(self._target_fps))

                while self._stop_queue.empty():

                    if time.time() - self._refresh_interval >= self._PREVIEW_REFRESH_TIME:
                        request = capture.capture_request()
                        with MappedArray(request, "main") as frame:
                            self._queue.put(frame.array[:h, :])
                        request.release()
                        self._refresh_interval = time.time()

                    if time.time() - self._video_time >= self._VIDEO_CHUNCK_DURATION:
                        logging.info("Splitting video recording into a new H264 chunk.")
                        capture.stop_encoder()
                        capture.start_encoder(encoder, self._get_video_chunk_filename(self._target_fps))
                        self._video_time = time.time()

                self._stop_queue.get()
                self._stop_queue.task_done()
                capture.stop_encoder()
                capture.stop()


            else:

                capture.start()

                while self._stop_queue.empty():

                    frame = capture.capture_array("main")

                    # As for picamera, we take arrays in YUV420 format and then get only the Y channel. The slicing, however, is different.
                    # from the picamera2 manual, pg 37 https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf
                    # YUv420 is a slightly special case because the first height rows give the Y channel, the next height/4 rows contain the U
                    # channel and the final height/4 rows contain the V channel. For the other formats, where there is an "alpha" value it will
                    # take the fixed value 255

                    self._queue.put(frame[:h, :])

                logging.info("The stop queue is not empty. This signals it is time to stop acquiring frames")
                self._stop_queue.get()
                self._stop_queue.task_done()
                capture.stop()


class OurPiCameraAsync(BaseCamera):
    _description = {"overview": "Default class to acquire frames from the raspberry pi camera asynchronously.",
                    "arguments": []}
                                   

    def __init__(self, target_fps=20, target_resolution=(1280, 960), video_prefix=None, *args, **kwargs):
        """
        Class to acquire frames from the raspberry pi camera asynchronously.
        At the moment, frames are only greyscale images.

        :param target_fps: the desired number of frames par second (FPS)
        :type target_fps: int
        :param target_fps: the desired resolution (W x H)
        :param target_resolution: (int,int)
        :param args: additional arguments
        :param kwargs: additional keyword arguments
        """
        self.canbepickled = True #cv2.videocapture object cannot be serialized, hence cannot be picked
        self.isPiCamera = True
        self._frame_grabber_class = PiFrameGrabber2 if USE_PICAMERA2 else PiFrameGrabber

        w,h = target_resolution
        if not isinstance(target_fps, int):
            raise EthoscopeException("FPS must be an integer number")

        self._args = args
        self._kwargs = kwargs

        self._queue = queue.Queue(maxsize=1)
        self._stop_queue = queue.Queue(maxsize=1)

        self._p = self._frame_grabber_class(target_fps, target_resolution, self._queue, self._stop_queue, video_prefix=video_prefix, *args, **kwargs)

        self._p.daemon = True
        self._p.start()
        
        try:
            self._frame = first_frame = self._queue.get(timeout=10)
            
        except Exception as e:
            logging.error("Could not get any frame from the camera after the initialisation!")
            # we force kill the frame grabber if it does not reply within 5s
            self._p.join(5)
            logging.warning("Framegrabber thread joined")

            raise e
            
        if len(first_frame.shape) < 2:
            raise EthoscopeException("The camera image is corrupted (less that 2 dimensions)")
        
        self._resolution = (first_frame.shape[1], first_frame.shape[0])
        if self._resolution != target_resolution:
            if w > 0 and h > 0:
                logging.warning('Target resolution "%s" could NOT be achieved. Effective resolution is "%s"' % (target_resolution, self._resolution ))
            else:
                logging.info('Maximal effective resolution is "%s"' % str(self._resolution))
        
        super(OurPiCameraAsync, self).__init__(*args, **kwargs)
        self._start_time = time.time()
        logging.info("Camera initialised")

    def restart(self):
        self._frame_idx = 0
        self._start_time = time.time()

    def __getstate__(self):
        return {"args": self._args,
                "kwargs": self._kwargs,
                "frame_idx": self._frame_idx,
                "start_time": self._start_time}

    def __setstate__(self, state):
        self.__init__(*state["args"], **state["kwargs"])
        self._frame_idx = int(state["frame_idx"])
        self._start_time = int(state["start_time"])

    def is_opened(self):
        return True
        # return self.capture.isOpened()

    def is_last_frame(self):
        return False

    def _time_stamp(self):
        now = time.time()
        # relative time stamp
        return now - self._start_time

    @property
    def start_time(self):
        return self._start_time

    def _close(self):

        logging.info("Requesting grabbing process to stop!")
        
        #Insert a stop signal in the stopping queue
        self._stop_queue.put(None)
        
        #empty the frames' queue
        while not self._queue.empty():
             self._queue.get()

        self._p.join()
        logging.info("Frame grabbing thread is joined")

    def _next_image(self):
        self.fps = self._frame_idx/(time.time() - self._start_time)

        try:
            return self._queue.get(timeout=30)

        except Exception as e:
            raise EthoscopeException("Could not get frame from camera\n%s", traceback.format_exc())




if __name__ == '__main__':

    #I should add some code to test the camera here
    pass