__author__ = 'quentin'



from pysolovideo.tracking.roi_builders import SleepDepROIBuilder
from pysolovideo.tracking.cameras import MovieVirtualCamera
from pysolovideo.tracking.monitor import Monitor
from pysolovideo.tracking.trackers import AdaptiveBGModel
from pysolovideo.tracking.interactors import SleepDepInteractor
from pysolovideo.hardware_control.arduino_api import SleepDepriverInterface

import cv2




cam = MovieVirtualCamera("/stk/pysolo_video_samples/23cm.avi")


#
rb = SleepDepROIBuilder()
# #


#
#
# sdi = SleepDepriverInterface()
#
# inters = [SleepDepInteractor(i, sdi) for i in range(13)]
#
#
#
#
monit = Monitor(cam, AdaptiveBGModel, interactors= None, roi_builder=rb)
monit.run()
#
#
# def show(im):
#     cv2.imshow("test", im)
#     cv2.waitKey(-1)
#
#
#
# def best_image_rotation(im):
#     hsv_im = cv2.cvtColor(im,cv2.COLOR_BGR2HSV)
#     s_im = hsv_im[:,:,1]
#     v_im = 255 - hsv_im[:,:,2]
#     s_im = cv2.medianBlur(s_im,7)
#     v_im = cv2.medianBlur(v_im,7)
#
#     med = cv2.medianBlur(s_im,51)
#     cv2.subtract(s_im,med,s_im)
#     med = cv2.medianBlur(v_im,51)
#     cv2.subtract(v_im,med,v_im)
#
#
#     cv2.threshold(s_im,-1,255,cv2.THRESH_OTSU | cv2.THRESH_BINARY,s_im)
#     cv2.threshold(v_im,-1,255,cv2.THRESH_OTSU | cv2.THRESH_BINARY,v_im)
#
#     caps = cv2.bitwise_and(v_im,s_im)
#     dst = cv2.distanceTransform(caps, cv2.cv.CV_DIST_L2, cv2.cv.CV_DIST_MASK_PRECISE)
#
#     # todo rotate and minimise entropy of dst
#     vert = np.mean(dst ,1)
#     #    pl.plot(vert / np.sum(vert))
#     # pl.show()
#     rot_mat = None
#     return rot_mat, caps
# ####################################################################
#
#
# def make_rois(caps, rot_mat):
#     #todo watershed/ morph snakes
#
#     caps = cv2.erode(caps,None, iterations=5)
#     caps = cv2.dilate(caps,None, iterations=5)
#
#
#     contours, h = cv2.findContours(caps,cv2.RETR_EXTERNAL,cv2.cv.CV_CHAIN_APPROX_SIMPLE)
#
#     centres, wh = [],[]
#     for c in contours:
#         moms = cv2.moments(c)
#         xy = moms["m10"]/moms["m00"] + 1j * moms["m01"]/moms["m00"]
#         centres.append(xy)
#         x0,y0,w,h =  cv2.boundingRect(c)
#         #print w -h) / float(max(w,h))
#         if min(h,w) / float(max(w,h)) < 0.5:
#             continue
#         if w > im.shape[0] / 10. or h > im.shape[0] / 10.:
#             continue
#
#         wh.append(w + 1j * h)
#
#
#     average_wh = np.mean(wh)
#     # pl.plot(np.real(centres),np.imag(centres),"o");pl.show()
#
#     criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
#
#     # Set flags (Just to avoid line break in the code)
#     flags = cv2.KMEANS_RANDOM_CENTERS
#
#     compactness,labels,centroids = cv2.kmeans(np.imag(centres).astype(np.float32),2,criteria,attempts=3,flags=flags)
#     centroids = centroids.flatten()
#
#     top_lab = np.argmin(centroids)
#
#     top_pos = np.min(centroids)
#     bottom_pos = np.max(centroids)
#
#     aw, ah = np.real(average_wh), np.imag(average_wh)
#
#     polygons = []
#     for x,l in zip(np.real(centres),  labels):
#
#         a = (x - aw/2.5, top_pos + ah)
#         b = (x + aw/2.5, top_pos + ah)
#         d = (x - aw/2.5, bottom_pos  - ah)
#         c = (x + aw/2.5, bottom_pos - ah)
#
#         pol = np.array([a,b,c,d])
#         #todo here: remap according to the invert rotation matrix ;)
#
#         pol = pol.reshape(pol.shape[0],1,pol.shape[1]).astype(np.int)
#         polygons.append(pol)
#         # print pol.shape
#     #
#     # cv2.drawContours(im, polygons, -1, (0,0,255), 1,cv2.CV_AA)
#     # show(im)
#
#
# IMAGE_FILE = "./23cm_upright.jpg"
# #IMAGE_FILE = "./23cm.png"
# im = cv2.imread(IMAGE_FILE,1)
#
# _, caps = best_image_rotation(im)
# make_rois(caps,None)
#
#


    # compactness,labels,centers = cv2.kmeans(np.imag(centres),2,None,criteria,10,flags)




    #
    # #show(bak)
    # vert = np.mean(dst ,0)
    #
    # pl.plot(vert)
    #
    # pl.show()
    # # ffr = np.fft.fft(vert)
    # #
    # # pl.plot(np.real(ffr), np.imag(ffr), "o")
    # #
    # #
    # # pl.show()
    # # affr = np.abs(ffr)
    # # peak = np.argmax(affr[1:])
    # # peak_val = affr[peak]
    # # affr[1:] = 0
    # # affr[peak_val] = peak_val
    # #
    # #
    # # pl.plot(np.fft.ifft(affr))
    # # pl.show()
    #
    # # pl.plot(np.abs(np.fft.rfft(vert))[1:])
    # # pl.show()
    #
