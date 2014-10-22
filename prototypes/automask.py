__author__ = 'quentin'

import cv2
import numpy as np


def show(im):
    cv2.imshow("test", im)
    cv2.waitKey(-1)

IMAGE_FILE = "./automask.png"
im = cv2.imread(IMAGE_FILE,0)
im = im[32:-32,32: -32]
im = cv2.GaussianBlur(im,(15,15),2.5)

# show(im)

import pylab as pl





n=10

k = np.array([
    [0,0,0],
    [1,1,1],
    [0,0,0]
],dtype=np.uint8)

err =  cv2.dilate(im,k, iterations=n)
dil = cv2.erode(err,k, iterations=n)

dil =  cv2.erode(dil,k.T, iterations=n)



show(dil)
dil = cv2.subtract(dil, im)
show(dil)


vert = np.mean(dil ,0) -  np.median(dil ,0)
#
#
# pl.plot(np.convolve(vert,[1]*7))
#
# pl.show()
# ffr = np.fft.fft(vert)
#
# pl.plot(np.real(ffr), np.imag(ffr), "o")
#
#
# pl.show()
# affr = np.abs(ffr)
# peak = np.argmax(affr[1:])
# peak_val = affr[peak]
# affr[1:] = 0
# affr[peak_val] = peak_val
#
#
# pl.plot(np.fft.ifft(affr))
# pl.show()

pl.plot(np.abs(np.fft.rfft(vert))[1:])
pl.show()

