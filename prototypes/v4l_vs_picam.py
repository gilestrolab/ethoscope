__author__ = 'quentin'


import cv2
import numpy as np
import time
import time


capture = cv2.VideoCapture(0)
capture.set(cv2.cv.CV_CAP_PROP_FRAME_WIDTH,1280)
capture.set(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT, 960)

capture.set(cv2.cv.CV_CAP_PROP_FPS, 5)


# CV_CAP_PROP_POS_MSEC Current position of the video file in milliseconds.
# CV_CAP_PROP_POS_FRAMES 0-based index of the frame to be decoded/captured next.
# CV_CAP_PROP_POS_AVI_RATIO Relative position of the video file: 0 - start of the film, 1 - end of the film.
# CV_CAP_PROP_FRAME_WIDTH Width of the frames in the video stream.
# CV_CAP_PROP_FRAME_HEIGHT Height of the frames in the video stream.
# CV_CAP_PROP_FPS Frame rate.
# CV_CAP_PROP_FOURCC 4-character code of codec.
# CV_CAP_PROP_FRAME_COUNT Number of frames in the video file.
# CV_CAP_PROP_FORMAT Format of the Mat objects returned by retrieve() .
# CV_CAP_PROP_MODE Backend-specific value indicating the current capture mode.
# CV_CAP_PROP_BRIGHTNESS Brightness of the image (only for cameras).
# CV_CAP_PROP_CONTRAST Contrast of the image (only for cameras).
# CV_CAP_PROP_SATURATION Saturation of the image (only for cameras).
# CV_CAP_PROP_HUE Hue of the image (only for cameras).
# CV_CAP_PROP_GAIN Gain of the image (only for cameras).
# CV_CAP_PROP_EXPOSURE Exposure (only for cameras).
# CV_CAP_PROP_CONVERT_RGB Boolean flags indicating whether images should be converted to RGB.
# CV_CAP_PROP_WHITE_BALANCE_U The U value of the whitebalance setting (note: only supported by DC1394 v 2.x backend currently)
# CV_CAP_PROP_WHITE_BALANCE_V The V value of the whitebalance setting (note: only supported by DC1394 v 2.x backend currently)
# CV_CAP_PROP_RECTIFICATION Rectification flag for stereo cameras (note: only supported by DC1394 v 2.x backend currently)
# CV_CAP_PROP_ISO_SPEED The ISO speed of the camera (note: only supported by DC1394 v 2.x backend currently)
# CV_CAP_PROP_BUFFERSIZE


# CV_CAP_PROP_BRIGHTNESS Brightness of the image (only for cameras).
# CV_CAP_PROP_CONTRAST Contrast of the image (only for cameras).
# CV_CAP_PROP_SATURATION Saturation of the image (only for cameras).
# CV_CAP_PROP_HUE Hue of the image (only for cameras).
# CV_CAP_PROP_GAIN Gain of the image (only for cameras).

print(cv2.cv.CV_CAP_PROP_BRIGHTNESS, capture.get(cv2.cv.CV_CAP_PROP_BRIGHTNESS))
time.sleep(0.5)
#cv2.waitKey(2000)
_,im = capture.read()


NFRAMES = 1000
print("ok, frame shape=", im.shape)

t0 = time.time()
try:
    for _ in range(NFRAMES):

        capture.grab()
        capture.retrieve(im)

        cv2.imshow("frame", im)
        cv2.waitKey(1)



        #im = np.copy(im)
        assert(len(im.shape) == 3)
    t1= time.time()

    print((t1-t0) / float(NFRAMES))
finally:
    print("voila")
    capture.release()

