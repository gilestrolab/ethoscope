__author__ = 'quentin'

import numpy as np
import cv2
import itertools
import roi_builders
import pandas as pd
class NoPositionError(Exception):
    pass

class BaseTracker(object):
    # a list of complex number representing x(real) and y(imaginary) coordinatesT


    def __init__(self, roi,data=None):
        self._positions = pd.DataFrame()


        self._data = data
        self._roi = roi


    def __call__(self, t, img):
        sub_img, mask = self._roi(img)

        try:

            point = self._find_position(sub_img,mask)

            point = pd.DataFrame(point,index=[t])
            point = self.normalise_position(point)

        except NoPositionError:
            if len(self._positions) == 0:
                return None
            else:

                point = self._positions.tail(1)



        self._positions = self._positions.append(point)

        return point

    def normalise_position(self,point):
        point.x = point.x / self._roi.longest_axis
        point.y = point.y / self._roi.longest_axis
        point.w = point.w / self._roi.longest_axis
        point.h = point.h / self._roi.longest_axis
        return point


    @property
    def positions(self):
        return self._positions

    def xy_pos(self, i):
        return self._positions[i][0]

    @property
    def times(self):
        return self._positions.index

    def _find_position(self,img, mask):
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
        self._max_learning_rate = 5e-1
        self._learning_rate = self._max_learning_rate
        self._min_learning_rate = 1e-3
        self._increment = 1.2

        self._bg_mean = None
        self._fg_features = None
        self._bg_sd = None

        super(AdaptiveBGModel, self).__init__(roi, data)



    def _update_fg_blob_model(self, img, contour, lr = 1e-2):
        features = self._comput_blob_features(img, contour)
        if self._fg_features is None:
            self._fg_features = features

        self._fg_features = lr * features  + (1 - lr) * self._fg_features


    def _comput_blob_features(self, img, contour, lr = 1e-5):
        hull = contour

        x,y,w,h = cv2.boundingRect(contour)

        roi = img[y : y + h, x : x + w]
        mask = np.zeros_like(roi)
        cv2.drawContours(mask,[hull],-1, 1,-1,offset=(-x,-y))

        mean_col = cv2.mean(roi,mask)[0]


        if len(self.positions) > 2:

            last_two_pos = self._positions.tail(2)
            xm, xmm = last_two_pos.x
            ym, ymm = last_two_pos.y

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
            self._bg_mean = img
            self._bg_sd = img

        learning_mat = np.ones_like(img,dtype = np.float32) * np.float32(self._learning_rate)
        if fgmask is not None:
            cv2.dilate(fgmask,None,fgmask)
            cv2.dilate(fgmask,None,fgmask)
            learning_mat[fgmask.astype(np.bool)] = 0

        self._bg_mean = learning_mat * img  + (1 - learning_mat) * self._bg_mean

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

    def _find_position(self, img, mask):
        # TODO preallocated buffers
        #  TODO try exepect slice me with mask

        # minor preprocessing
        grey = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
        cv2.GaussianBlur(grey,(3,3), 1.5, grey)

        # if len(self._positions) == 0:
        #
        #     self._update_bg_model(grey)
        #
        #     raise NoPositionError

        # fixme this should NOT be needed !
        if self._bg_mean is None:
            self._update_bg_model(grey)
            print "fixme"
            raise NoPositionError

        # fixme use preallocated buffers next line ?
        fg = grey - self._bg_mean
        np.abs(fg, fg)
        fg = fg.astype(np.uint8)

        cv2.dilate(fg,None,fg)
        cv2.erode(fg,None,fg)


        #todo make this objective
        cv2.threshold(fg,13,255,cv2.THRESH_BINARY, dst=fg)

        if mask is not None:
            #todo test me
            cv2.bitwise_and(fg, mask, fg)
        # fixme magi numbers. use cv2.CONSTS instead !!
        contours,hierarchy = cv2.findContours(fg, 1, 2)

        if len(contours) == 0:
            self._learning_rate *= self._increment
            self._update_bg_model(grey)
            raise NoPositionError


        elif len(contours) > 1:
            self._learning_rate *= self._increment

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

        fg.fill(0)

        (x,y) ,(w,h), angle  = cv2.minAreaRect(hull)

        cv2.drawContours(fg ,[hull],0, (255,0,0),-1)






        self._update_bg_model(grey, fg)
        # cv2.drawContours(grey ,[hull],0, (255,0,0),-1)
        # cv2.imshow(str(self), grey)

        return {
            'x':x,
            'y':y,
            'w':w,
            'h':h,
            'phi':angle
        }
