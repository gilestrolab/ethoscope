__author__ = 'quentin'


import numpy as np
import cv2
import cv
# from pysolovideo.utils.memoisation import memoised_property


class ROI(object):

    def __init__(self, polygon, value=None, orientation = None, regions=None):

        # TODO if we do not need polygon, we can drop it
        self._polygon = np.array(polygon)
        if len(self._polygon.shape) == 2:
            self._polygon = self._polygon.reshape((self._polygon.shape[0],1,self._polygon.shape[1]))

        self._value = value
        x,y,w,h = cv2.boundingRect(self._polygon)

        self._mask = np.zeros((h,w), np.uint8)
        cv2.drawContours(self._mask, [self._polygon], 0, 255,-1,offset=(-x,-y))

        self._rectangle = x,y,w,h
        # todo NOW! sort rois by value. if no values, left to right/ top to bottom!

    def bounding_rect(self):
        raise NotImplementedError


    def mask(self):
        return self._mask

    @property
    def offset(self):
        x,y,w,h = self._rectangle
        return x,y

    @property
    def polygon(self):

        return self._polygon


    @property
    def longest_axis(self):
        x,y,w,h = self._rectangle
        return float(max(w, h))


    @property
    def value(self):
        return self._value

    def __call__(self,img):
        x,y,w,h = self._rectangle
        out = img[y : y + h, x : x +w]


        assert(out.shape[0:2] == self._mask.shape)

        return out, self._mask


class BaseROIBuilder(object):

    def __call__(self, camera):


        for _, frame in camera:

            rois = self._rois_from_img(frame)
            # TODO here, we should make an average of a few frames

            break

        rois = self._sort_rois(rois)
        return rois


    def _sort_rois(self, rois):
        # TODO Implement the left to right/top to bottom sorting algo
        return rois

    def _rois_from_img(self,img):
        raise NotImplementedError



class DefaultROIBuilder(BaseROIBuilder):

    def _rois_from_img(self,img):
        h, w = img.shape[0],img.shape[1]
        return[
            ROI([
                (   0,        0       ),
                (   0,        h -1    ),
                (   w - 1,    h - 1   ),
                (   w - 1,    0       )]
        )]



def show(im):
    cv2.imshow("test", im)
    cv2.waitKey(-1)


class SleepDepROIBuilder(BaseROIBuilder):


    def _rois_from_img(self,im):
        rot_mat= self._best_image_rotation(im)

        rois = self._make_rois(im, rot_mat)
        return rois



    # def _decimate(self, im, rate=0.8):
    #     rand = np.random.uniform(0,1,im.shape[0] * im.shape[1]).reshape(im.shape)
    #     decimated = im & (rand > rate)
    #     return decimated

    def _best_image_rotation(self, im):
        hsv_im = cv2.cvtColor(im,cv2.COLOR_BGR2HSV)
        s_im = hsv_im[:,:,1]
        v_im = 255 - hsv_im[:,:,2]
        s_im = cv2.medianBlur(s_im,7)
        v_im = cv2.medianBlur(v_im,7)

        med = cv2.medianBlur(s_im,51)
        cv2.subtract(s_im,med,s_im)
        med = cv2.medianBlur(v_im,51)
        cv2.subtract(v_im,med,v_im)


        cv2.threshold(s_im,-1,255,cv2.THRESH_OTSU | cv2.THRESH_BINARY,s_im)
        cv2.threshold(v_im,-1,255,cv2.THRESH_OTSU | cv2.THRESH_BINARY,v_im)

        caps = cv2.bitwise_and(v_im,s_im)
        dst = cv2.distanceTransform(caps, cv2.cv.CV_DIST_L2, cv2.cv.CV_DIST_MASK_PRECISE)
        return  self._find_best_angle(dst)
        # todo rotate and minimise entropy of dst
        # vert = np.mean(dst ,1)
        #    pl.plot(vert / np.sum(vert))

    ####################################################################


    def make_rotation_mat(self, theta):
        return np.array([
        [np.cos(theta), -np.sin(theta)],
        [np.sin(theta), np.cos(theta)],
        ])

    def _find_best_angle(self, im, min_theta=-30, max_theta=+30, theta_incr=.5 ):

        min_entr, best_rot_mat, out = -np.Inf , None, None
        for theta in np.arange(min_theta, max_theta, theta_incr):
            M= cv2.getRotationMatrix2D((im.shape[1]/2,im.shape[0]/2), theta,  1)
            rotated_im = cv2.warpAffine(im,M, (im.shape[1],im.shape[0]))
            row_means = np.mean(rotated_im,1)
            row_means /= np.sum(row_means)

            entr =  np.sum(np.log2(row_means+1e-10) * row_means)

            if entr > min_entr:
                min_entr = entr
                best_rot_mat = M



        return best_rot_mat

    def _make_rois(self, im, rot_mat):
        #todo watershed/ morph snakes
        print im.shape
        rotated_im = cv2.warpAffine(im, rot_mat, (im.shape[1],im.shape[0]))
        #show(rotated_im)
        hsv_im = cv2.cvtColor(rotated_im,cv2.COLOR_BGR2HSV)
        s_im = hsv_im[:,:,1]
        v_im = 255 - hsv_im[:,:,2]
        s_im = cv2.medianBlur(s_im,7)
        v_im = cv2.medianBlur(v_im,7)

        med = cv2.medianBlur(s_im,51)
        cv2.subtract(s_im,med,s_im)
        med = cv2.medianBlur(v_im,51)
        cv2.subtract(v_im,med,v_im)


        cv2.threshold(s_im,-1,255,cv2.THRESH_OTSU | cv2.THRESH_BINARY,s_im)
        cv2.threshold(v_im,-1,255,cv2.THRESH_OTSU | cv2.THRESH_BINARY,v_im)

        caps = cv2.bitwise_and(v_im,s_im)

        contours, h = cv2.findContours(caps,cv2.RETR_EXTERNAL,cv2.cv.CV_CHAIN_APPROX_SIMPLE)



        centres, wh = [],[]
        for c in contours:
            moms = cv2.moments(c)
            xy = moms["m10"]/moms["m00"]+ 1j *  moms["m01"]/moms["m00"]



            centres.append(xy)
            x0,y0,w,h =  cv2.boundingRect(c)
            #print w -h) / float(max(w,h))
            if min(h,w) / float(max(w,h)) < 0.5:
                continue
            if w > caps.shape[0] / 10. or h > caps.shape[0] / 10.:
                continue

            wh.append(w + 1j * h)


        average_wh = np.mean(wh)
        # pl.plot(np.real(centres),np.imag(centres),"o");pl.show()

        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)

        # Set flags (Just to avoid line break in the code)
        flags = cv2.KMEANS_RANDOM_CENTERS

        compactness,labels,centroids = cv2.kmeans(np.imag(centres).astype(np.float32),2,criteria,attempts=3,flags=flags)
        centroids = centroids.flatten()

        top_lab = np.argmin(centroids)

        top_pos = np.min(centroids)
        bottom_pos = np.max(centroids)

        aw, ah = np.real(average_wh), np.imag(average_wh)

        rois = []

        mask = np.zeros_like(caps)

        for x,l in zip(np.real(centres),  labels):

            a = (x - aw/2.5, top_pos + ah)
            b = (x + aw/2.5, top_pos + ah)
            d = (x - aw/2.5, bottom_pos  - ah)
            c = (x + aw/2.5, bottom_pos - ah)

            pol = np.array([a,b,c,d])
            #todo here: remap according to the invert rotation matrix ;)

            pol = pol.astype(np.int).reshape(4,1,2)
            cv2.drawContours(mask, [pol], 0,255,-1)
        show(mask)

        i_rot_mat = cv2.invertAffineTransform(rot_mat)
        mask= cv2.warpAffine(mask, i_rot_mat, (im.shape[1],im.shape[0]))
        show(mask)

        contours, hiera = cv2.findContours(np.copy(mask), cv.CV_RETR_EXTERNAL, cv.CV_CHAIN_APPROX_SIMPLE)

        rois = []
        for c in contours:
            tmp_mask = np.zeros_like(mask)
            cv2.drawContours(tmp_mask, [c],0, 1)

            rois.append(ROI(c, None))

        return rois

class ImgMaskROIBuilder(BaseROIBuilder):
    """
    Initialised with an grey-scale image file.
    Each continuous region is used as a ROI.
    The colour of the ROI determines it's index
    """


    def __init__(self, mask_path):
        self._mask = cv2.imread(mask_path, cv2.CV_LOAD_IMAGE_GRAYSCALE)

    def _rois_from_img(self,img):
        if len(self._mask.shape) == 3:
            self._mask = cv2.cvtColor(self._mask, cv2.COLOR_BGR2GRAY)



        contours, hiera = cv2.findContours(np.copy(self._mask), cv.CV_RETR_EXTERNAL, cv.CV_CHAIN_APPROX_SIMPLE)

        rois = []
        for c in contours:
            tmp_mask = np.zeros_like(self._mask)
            cv2.drawContours(tmp_mask, [c],0, 1)

            value = int(np.median(self._mask[tmp_mask > 0]))

            rois.append(ROI(c, value))
        return rois


