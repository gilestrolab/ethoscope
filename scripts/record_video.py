__author__ = 'quentin'

"""
A simple script to record videos using psv
"""

from optparse import OptionParser

from pysolovideo.tracking.cameras import V4L2Camera
import cv2
import cv

VIDEO_FOURCC = cv.CV_FOURCC('D', 'I', 'V', 'X')


if __name__ == "__main__":

    parser = OptionParser()
    parser.add_option("-f", "--fps", dest="fps", help="fps", default=5, type="int")
    parser.add_option("-o", "--output", dest="out", help="the output file (eg out.avi)", type="str")
    parser.add_option("-W", "--width", dest="w", help="the target width of the video frames", type="int", default=-1)
    parser.add_option("-H", "--height", dest="h", help="the target height of the video frames", type="int", default=-1)
    parser.add_option("-d", "--duration",dest="duration", help="the total length in seconds", default=60, type="int")

    device = 0

    (options, args) = parser.parse_args()

    option_dict = vars(options)
    if not option_dict["out"]:
        raise ValueError("Please specify an output file")

    cam = V4L2Camera(device,target_fps=option_dict["fps"], target_resolution=(option_dict["w"],option_dict["h"]))
    video_writer = None
    for t,frame in cam:
        if video_writer is None:
            dims = (frame.shape[1],frame.shape[0])
            video_writer = cv2.VideoWriter(option_dict["out"], VIDEO_FOURCC, option_dict["fps"], dims)

        video_writer.write(frame)

        if t > option_dict["duration"]:
             break

