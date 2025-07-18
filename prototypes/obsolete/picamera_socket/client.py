__author__ = 'quentin'


import cv2


video = cv2.VideoCapture("http://129.31.135.35:8080/")
while True:
    ret,a = video.read()
    if a is not None:
        print(ret, a.shape)
    else:
        print("None")
    # cv2.imshow("test",a)
    # cv2.waitKey(1)

