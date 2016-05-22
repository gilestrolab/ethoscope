__author__ = 'quentin'

import cv2
try:
    from cv2.cv import CV_CAP_PROP_FRAME_WIDTH as CAP_PROP_FRAME_WIDTH
    from cv2.cv import CV_CAP_PROP_FRAME_HEIGHT as CAP_PROP_FRAME_HEIGHT
    from cv2.cv import CV_CAP_PROP_FRAME_COUNT as CAP_PROP_FRAME_COUNT
    from cv2.cv import CV_CAP_PROP_POS_MSEC as CAP_PROP_POS_MSEC
    from cv2.cv import CV_CAP_PROP_FPS as CAP_PROP_FPS

except ImportError:
    from cv2 import CAP_PROP_FRAME_WIDTH, CAP_PROP_FRAME_HEIGHT, CAP_PROP_FRAME_COUNT, CAP_PROP_POS_MSEC, CAP_PROP_FPS


import time
import logging
import os
from ethoscope.utils.debug import EthoscopeException
import multiprocessing
import traceback

class BaseCamera(object):
    #TODO catch exception eg, if initialise with a wrong file

    capture = None
    _resolution = None
    _frame_idx = 0

    def __init__(self,drop_each=1, max_duration=None, *args, **kwargs):
        """
        The template class to generate and use video streams.


        :param drop_each: keep only ``1/drop_each``'th frame
        :param max_duration: stop the video stream if ``t > max_duration`` (in seconds).
        :param args: additional arguments
        :param kwargs: additional keyword arguments
        :return:
        """
        self._drop_each = drop_each
        self._max_duration = max_duration

    def __exit__(self):
        logging.info("Closing camera")
        self._close()

    def __iter__(self):
        """
        Iterate thought consecutive frames of this camera.

        :return: the time (in ms) and a frame (numpy array).
        :rtype: (int, :class:`~numpy.ndarray`)
        """

        # We ensure timestamps and frame index are set to 0

        self.restart()
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

        #print "path", path
        self._frame_idx = 0
        self._path = path
        self._use_wall_clock = use_wall_clock


        if not (isinstance(path, str) or isinstance(path, unicode)):
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
        return frame

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
    def __init__(self,device, target_fps=5, target_resolution=(960,720), *args, **kwargs):
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
        self.capture = cv2.VideoCapture(device)
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
        _, im = self.capture.read()

        # preallocate image buffer => faster
        if im is None:
            raise EthoscopeException("Error whist retrieving video frame. Got None instead. Camera not plugged?")

        self._frame = im


        #TODO better exception handling is needed here / what do we do if initial capture fails...
        assert(len(im.shape) >1)

        self._resolution = (im.shape[1], im.shape[0])
        if self._resolution != target_resolution:
            if w > 0 and h > 0:
                logging.warning('Target resolution "%s" could NOT be achieved. Effective resolution is "%s"' % (target_resolution, self._resolution ))
            else:
                logging.info('Maximal effective resolution is "%s"' % str(self._resolution))


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

        if self._frame_idx >0 :
            expected_time =  self._start_time + self._frame_idx / self._target_fps
            now = time.time()

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



        return self._frame




class OurPiCamera(BaseCamera):

    def __init__(self, target_fps=10, target_resolution=(960,720), *args, **kwargs):
        # lazy import should only use those on devices
        from picamera.array import PiRGBArray
        from picamera import PiCamera



        logging.info("Initialising camera")
        w,h = target_resolution
        self.capture = PiCamera()

        self.capture.resolution = target_resolution
        if not isinstance(target_fps, int):
            raise EthoscopeException("FPS must be an integer number")
        self.capture.framerate = target_fps

        self._raw_capture = PiRGBArray(self.capture, size=target_resolution)

        self._target_fps = float(target_fps)
        self._warm_up()

        self._cap_it = self._frame_iter()

        im = next(self._cap_it)

        if im is None:
            raise EthoscopeException("Error whist retrieving video frame. Got None instead. Camera not plugged?")

        self._frame = im

        if len(im.shape) < 2:
            raise EthoscopeException("The camera image is corrupted (less that 2 dimensions)")

        self._resolution = (im.shape[1], im.shape[0])
        if self._resolution != target_resolution:
            if w > 0 and h > 0:
                logging.warning('Target resolution "%s" could NOT be achieved. Effective resolution is "%s"' % (target_resolution, self._resolution ))
            else:
                logging.info('Maximal effective resolution is "%s"' % str(self._resolution))


        super(OurPiCamera, self).__init__(*args, **kwargs)

        self._start_time = time.time()
        logging.info("Camera initialised")

    def _warm_up(self):
        logging.info("%s is warming up" % (str(self)))
        time.sleep(1)

    def restart(self):
        self._frame_idx = 0
        self._start_time = time.time()

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
        self._raw_capture.truncate(0)
        self.capture.close()

        # self.capture.release()

    def _frame_iter(self):

        # capture frames from the camera

        for frame in self.capture.capture_continuous(self._raw_capture, format="bgr", use_video_port=True):
            # grab the raw NumPy array representing the image, then initialize the timestamp
            # and occupied/unoccupied text

        # clear the stream in preparation for the next frame
            self._raw_capture.truncate(0)
            yield frame.array




    def _next_image(self):

        if self._frame_idx >0 :
            expected_time =  self._start_time + self._frame_idx / self._target_fps
            now = time.time()

            to_sleep = expected_time - now

            # Warnings if the fps is so high that we cannot grab fast enough
            if to_sleep < 0:
                if self._frame_idx % 5000 == 0:
                    logging.warning("The target FPS (%f) could not be reached. Effective FPS is about %f" % (self._target_fps, self._frame_idx/(now - self._start_time)))
                #next(self._cap_it)

            # we simply drop frames until we go above expected time
            while now < expected_time:
                # next(self._cap_it)
                time.sleep(.01)
                now = time.time()


        self._frame = next(self._cap_it)

        return self._frame
class PiFrameGrabber(multiprocessing.Process):
    """
    Class to grab frames from pi camera. Designed to be used within :class:`~ethoscope.hardware.camreras.camreras.OurPiCameraAsync`
    """

    def __init__(self, target_fps, target_resolution, queue,stop_queue):
        self._queue = queue
        self._stop_queue = stop_queue
        self._target_fps = target_fps
        self._target_resolution = target_resolution
        super(PiFrameGrabber, self).__init__()


    def run(self):
        # lazy import should only use those on devices
        from picamera.array import PiRGBArray
        from picamera import PiCamera

        try:
            from picamera.array import PiRGBArray
            from picamera import PiCamera

            with  PiCamera() as capture:
                logging.warning(capture)
                capture.resolution = self._target_resolution

                capture.framerate = self._target_fps
                raw_capture = PiRGBArray(capture, size=self._target_resolution)
                    
                for frame in capture.capture_continuous(raw_capture, format="bgr", use_video_port=True):
                    if not self._stop_queue.empty():
                        logging.warning("The stop queue is not empty. Stop acquiring frames")

                        self._stop_queue.get()
                        self._stop_queue.task_done()
                        logging.warning("Stop Task Done")
                        break
                    raw_capture.truncate(0)
                    # out = np.copy(frame.array)
                    out = cv2.cvtColor(frame.array,cv2.COLOR_BGR2GRAY)
                    #fixme here we could actually pass a JPG compressed file object (http://docs.scipy.org/doc/scipy-0.16.0/reference/generated/scipy.misc.imsave.html)
                    # This way, we would manage to get faster FPS
                    self._queue.put(out)
        finally:
            logging.warning("Closing frame grabber process")
            self._stop_queue.close()
            self._queue.close()
            logging.warning("Camera Frame grabber stopped acquisition cleanly")


class OurPiCameraAsync(BaseCamera):

    def __init__(self, target_fps=20, target_resolution=(1280, 960), *args, **kwargs):

        """
        Class to acquire frames from the raspberry pi camera asynchronously.
        At the moment, frames are greyscale images.

        :param target_fps: the desired number of frames par second (FPS)
        :type target_fps: int
        :param target_fps: the desired resolution (W x H)
        :param target_resolution: (int,int)
        :param args: additional arguments
        :param kwargs: additional keyword arguments
        """

        logging.info("Initialising camera")
        w,h = target_resolution

        if not isinstance(target_fps, int):
            raise EthoscopeException("FPS must be an integer number")


        self._queue = multiprocessing.Queue(maxsize=1)
        self._stop_queue = multiprocessing.JoinableQueue(maxsize=1)
        self._p = PiFrameGrabber(target_fps,target_resolution,self._queue,self._stop_queue )
        self._p.daemon = True
        self._p.start()


        try:
            im = self._queue.get(timeout=10)
        except Exception as e:
            logging.error("Could not get any frame from the camera")

            self._stop_queue.cancel_join_thread()
            self._queue.cancel_join_thread()

            logging.warning("Stopping stop queue")
            self._stop_queue.close()

            logging.warning("Stopping queue")
            self._queue.close()

            logging.warning("Joining process")

            # we kill the frame grabber if it does not reply within 10s
            self._p.join(10)
            logging.warning("Process joined")
            raise e

        self._frame = cv2.cvtColor(im,cv2.COLOR_GRAY2BGR)


        if len(im.shape) < 2:
            raise EthoscopeException("The camera image is corrupted (less that 2 dimensions)")

        self._resolution = (im.shape[1], im.shape[0])
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

        self._stop_queue.put(None)

        while not self._queue.empty():
             self._queue.get()

        logging.info("Joining stop queue")

        self._stop_queue.cancel_join_thread()
        self._queue.cancel_join_thread()

        logging.info("Stopping stop queue")
        self._stop_queue.close()

        logging.info("Stopping queue")
        self._queue.close()

        logging.info("Joining process")
        self._p.join()
        logging.info("All joined ok")

    def _next_image(self):
        try:
            g = self._queue.get(timeout=30)
            cv2.cvtColor(g,cv2.COLOR_GRAY2BGR,self._frame)
            return self._frame

        except Exception as e:
            raise EthoscopeException("Could not get frame from camera\n%s", traceback.format_exc(e))
