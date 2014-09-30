__author__ = 'quentin'


from pysolovideo.tracking.cameras import MovieVirtualCamera



cam = MovieVirtualCamera("/home/quentin/Desktop/drosoAdult_short.avi")

import cv2
for t,frame in cam:
    cv2.imshow("Test", frame)
    cv2.waitKey(1)



