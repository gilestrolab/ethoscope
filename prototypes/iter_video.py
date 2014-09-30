__author__ = 'quentin'


from pysolovideo.tracking.cameras import MovieVirtualCamera
import cv2


cam = MovieVirtualCamera("/home/quentin/Desktop/drosoAdult_short.avi")


for t,frame in cam:
    cv2.imshow("Test", frame)
    cv2.waitKey(1)

cam.restart()

for t,frame in cam:
    cv2.imshow("Test", frame)
    cv2.waitKey(1)


