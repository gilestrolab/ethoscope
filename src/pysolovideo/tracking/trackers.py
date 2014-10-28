__author__ = 'quentin'

import numpy as np
import cv2
import itertools
import roi_builders




class NoPositionError(Exception):
    pass

class BaseTracker(object):
    # a list of complex number representing x(real) and y(imaginary) coordinatesT


    def __init__(self, roi,data=None):
        self._positions =[]
        self._times =[]
        self._data = data
        self._roi = roi

    def __call__(self, t, img):
        sub_img, mask = self._roi(img)
        try:
            point = self._find_position(sub_img,mask,t)
            point = self.normalise_position(point)

        except NoPositionError:
            if len(self._positions) == 0:
                return None
            else:
                point = self._positions[-1]
        self._positions.append(point)
        self._times.append(t)
        return point

    def normalise_position(self,point):
        point["x"] /= self._roi.longest_axis
        point["y"] /=  self._roi.longest_axis
        point["w"] /=  self._roi.longest_axis
        point["h"] /= self._roi.longest_axis
        return point


    @property
    def positions(self):
        return self._positions

    def xy_pos(self, i):
        return self._positions[i][0]

    @property
    def times(self):
        return self._times

    def _find_position(self,img, mask,t):
        raise NotImplementedError


class DummyTracker(BaseTracker):

    def _find_position(self,img, mask):
        # random_walk
        x, y = np.random.uniform(size=2)
        point = np.complex64(x + y * 1j)
        if len(self._positions) == 0:
            return point
        return self._positions[-1] + point
#


class AdaptiveBGModel(BaseTracker):

    def __init__(self, roi, data=None):
        # self._max_learning_rate = 0.1
        self._max_learning_rate = 0.01

        self._learning_rate = self._max_learning_rate
        self._min_learning_rate = 1e-5
        # self._min_learning_rate = 1e-3
        self._increment = 1.5

        self._object_expected_size = 0.05 # proportion of the roi main axis
        self._max_area = 10 * self._object_expected_size ** 2
        self._bg_mean = None
        self._fg_features = None
        self._bg_sd = None
        self._learning_mat_buff = None

        super(AdaptiveBGModel, self).__init__(roi, data)


    def show(self,im,t=-1):
        cv2.imshow(str(self),im)
        cv2.waitKey(t)

    def _update_fg_blob_model(self, img, contour, lr = 1e-3):
        features = self._comput_blob_features(img, contour)
        if self._fg_features is None:
            self._fg_features = features

        self._fg_features = lr * features  + (1 - lr) * self._fg_features


    def _comput_blob_features(self, img, contour, lr = 1e-5):
        hull = contour

        x,y,w,h = cv2.boundingRect(contour)

        roi = img[y : y + h, x : x + w]
        mask = np.zeros_like(roi)

        #
        # cv2.drawContours(mask,[hull],-1, 1,-1,offset=(-x,-y))
        # mean_col = cv2.mean(roi,mask)[0]
        mean_col = 0

        if len(self.positions) > 2:

            pm, pmm = self._positions[-1],self._positions[-2]
            xm, xmm = pm["x"], pmm["x"]
            ym, ymm = pm["y"], pmm["y"]

            instantaneous_speed = abs(xm + 1j*ym - xmm + 1j*ymm)
        else:
            instantaneous_speed = 0
        if np.isnan(instantaneous_speed):
            instantaneous_speed = 0

        features = np.array([cv2.contourArea(hull) + 1.0,
                            cv2.arcLength(hull,True) + 1.0,
                            instantaneous_speed +1.0,
                            mean_col +1
                             ])

        return features

    def _feature_distance(self, features):
        d = np.abs((self._fg_features - features) / self._fg_features) #fixme div by 0 possible?
        return np.sum(d)

    def _update_bg_model(self, img, fgmask=None):
        # todo array preallocation and np.ufuns will help to optimise this part !

        if self._learning_rate > self._max_learning_rate:
            self._learning_rate = self._max_learning_rate

        if self._learning_rate < self._min_learning_rate:
            self._learning_rate = self._min_learning_rate

        if self._bg_mean is None:
            self._bg_mean = np.copy(img)
            #self._bg_sd = img

        if self._learning_mat_buff is None:
            self._learning_mat_buff = np.ones_like(img,dtype = np.float32)

        self._learning_mat_buff.fill(self._learning_rate)

        if fgmask is not None:
            cv2.dilate(fgmask,None,fgmask)
            # cv2.dilate(fgmask,None,fgmask)
            self._learning_mat_buff[fgmask.astype(np.bool)] = 0


        buff = 1. - self._learning_mat_buff
        np.multiply(buff, self._bg_mean,buff)

        np.multiply(self._learning_mat_buff, img, self._learning_mat_buff)


        self._bg_mean = self._learning_mat_buff  + buff

        # self._bg_sd = learning_mat * np.abs(self._bg_mean - img)  + (1 - learning_mat) * self._bg_sd

    def _join_blobs(self, hulls):
        idx_pos_w = []
        for i, c in enumerate(hulls):
            (x,y) ,(w,h), angle  = cv2.minAreaRect(c)
            w = max(w,h)
            h = min(w,h)
            idx_pos_w.append((i, x+1j*y,w + h))

        pairs_to_group = []
        for a,b in itertools.combinations(idx_pos_w,2):

            d = abs(a[1] - b[1])
            wm = max(a[2], b[2])
            if d < wm:
                pairs_to_group.append({a[0], b[0]})


        if len(pairs_to_group) == 0:
            return hulls

        repeat = True
        out_sets = pairs_to_group

        while repeat:
            comps = out_sets
            out_sets = []
            repeat=False
            for s in comps:
                connected = False
                for i,o in enumerate(out_sets):
                    if o & s:
                        out_sets[i] = s | out_sets[i]
                        connected = True
                        repeat=True
                if not connected:
                    out_sets.append(s)

        out_hulls = []
        for c in comps:
            out_hulls.append(np.concatenate([hulls[s] for s in c]))


        out_hulls= [cv2.convexHull(o) for o in out_hulls]



        return out_hulls


    def _pre_process_input(self, img, mask):

        grey = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)

        blur_rad = int(self._object_expected_size * np.max(grey.shape) * 2.0)
        if blur_rad % 2 == 0:
            blur_rad += 1

        #buff = cv2.medianBlur(grey,blur_rad)
        buff = np.zeros_like(grey)
        cv2.blur(grey,(blur_rad,blur_rad),buff)
        cv2.GaussianBlur(grey,(5,5), 2.5,grey)
        cv2.absdiff(grey,buff,grey)
        # fixme, convert before
        if mask is not None:
            m = mask.astype(np.bool)
            np.bitwise_not(m,m)
            grey[m] = 0


        return grey

    def _find_position(self, img, mask,t):
        # TODO preallocated buffers ++
        grey = self._pre_process_input(img,mask)

        if self._bg_mean is None:
            self._update_bg_model(grey)
            raise NoPositionError

        # fixme use preallocated buffers next line
        fg = cv2.absdiff(grey, self._bg_mean.astype(np.uint8))


        #cv2.threshold(fg,25,255,cv2.THRESH_BINARY, dst=fg)
        # fixme magic number
        cv2.threshold(fg,20,255,cv2.THRESH_BINARY , dst=fg)
        # cv2.threshold(fg,20,255,cv2.THRESH_BINARY | cv2.THRESH_OTSU , dst=fg)


        if np.count_nonzero(fg) / (1.0 * img.shape[0] * img.shape[1]) > self._max_area :
            self._learning_rate *= self._increment
            self._update_bg_model(grey)
            raise NoPositionError


        # fixme magi numbers. use cv2.CONSTS instead !!
        contours,hierarchy = cv2.findContours(fg, 1, 2)

        if len(contours) == 0:
            self._learning_rate *= self._increment
            self._update_bg_model(grey)
            raise NoPositionError


        elif len(contours) > 1:
            self._learning_rate *= self._increment
            self._update_bg_model(grey)
            if self._fg_features is None:
                raise NoPositionError

            hulls = [cv2.convexHull( c) for c in contours]
            hulls = self._join_blobs(hulls)

            cluster_features = [self._comput_blob_features(grey, h) for h in hulls]
            good_clust = np.argmin([self._feature_distance(cf) for cf in cluster_features])
            hull = hulls[good_clust]

        else:
            self._learning_rate /= self._increment
            hull = cv2.convexHull(contours[0])
            self._update_fg_blob_model(grey, hull)


        (x,y) ,(w,h), angle  = cv2.minAreaRect(hull)

        fg.fill(0)
        cv2.drawContours( fg ,[hull],0, 1,3)
        self._update_bg_model(grey, fg)


        return {
            'x':x,
            'y':y,
            'w':w,
            'h':h,
            'phi':angle
        }
