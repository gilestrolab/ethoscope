__author__ = 'quentin'

import numpy as np
import cv
import cv2
from sklearn.cluster import MeanShift, estimate_bandwidth


class BaseTracker(object):
    # a list of complex number representing x(real) and y(imaginary) coordinatesT
    _positions = []
    _angles = []
    _time_stamps = []
    _data=None

    def __init__(self, data=None):
        self._data = data

    def __call__(self, t, img, mask):
        point, angle = self._find_position(img,mask)
        self._positions.append(point)
        self._time_stamps.append(t)
        return point, angle

    @property
    def positions(self):
        return self._positions
    @property
    def angles(self):
        return self._angles
    @property
    def times(self):
        return self._time_stamps

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


class AdaptiveMOGTracker(BaseTracker):
    def __init__(self, data=None):
        self._mog = cv2.BackgroundSubtractorMOG(1000,2, 0.9, 1.0)

        self._max_learning_rate = 1e-2
        self._learning_rate = self._max_learning_rate
        self._min_learning_rate = 1e-7
        self._increment = 1.2
        super(AdaptiveMOGTracker, self).__init__(data)

    def _find_position(self, img, mask):
        # TODO preallocated buffers
        # TODO  slice me with mask
        #  TODO try exepect slice me with mask



        tmp = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)

        tmp = cv2.GaussianBlur(tmp,(3,3), 1.5)

        tmp = self._mog.apply(tmp, None, self._learning_rate)


        if len(self._positions) > 0:
            pos = self._positions[-1]
        else:
            pos= np.NaN




        # TODO if  a large proportion of the image is True, we should abort here.

        yx = np.where(tmp)

        if len(yx[0]) < 10:
            self._learning_rate *= self._increment
        else:
            yx = np.column_stack((yx[1],yx[0]))

            # FIXME magic number here
            ms = MeanShift(bandwidth=10, bin_seeding=True)
            ms.fit(yx)
            labels = ms.labels_
            labels_unique = np.unique(labels)
            n_clusters_ = len(labels_unique)


            if n_clusters_ > 1:
                self._learning_rate *= self._increment
            else:
                hull = cv2.convexHull(yx)

                self._learning_rate /= self._increment
                moments = cv2.moments(hull)
                pos = moments['m10']/moments['m00'] + 1j * moments['m01']/moments['m00']


        if self._learning_rate > self._max_learning_rate:
            self._learning_rate = self._max_learning_rate

        if self._learning_rate < self._min_learning_rate:
            self._learning_rate = 0

        try:
            cv2.drawContours(img,[hull],0, (255,0,0),2)
        except:
            pass
        # cv2.imshow(str(self),img)


        return pos, np.NaN





class AdaptiveBGModel(BaseTracker):
    def __init__(self, data=None):
        self._max_learning_rate = 1e-2
        self._learning_rate = self._max_learning_rate
        self._min_learning_rate = 1e-5
        self._increment = 1.2

        self._bg_mean = None
        self._fg_features = None
        self._bg_sd = None

        super(AdaptiveBGModel, self).__init__(data)


    def _update_fg_blob_model(self, img, points, lr = 1e-2):
        features = self._comput_blob_features(img, points)
        if self._fg_features is None:
            self._fg_features = features

        self._fg_features = lr * features  + (1 - lr) * self._fg_features


    def _comput_blob_features(self, img, points, lr = 1e-5):
        hull = cv2.convexHull(points)
        # moments = cv2.moments(hull)

        if len(self.positions) > 2:
            instantaneous_speed = abs(self.positions[-1] - self.positions[-2])
        else:
            instantaneous_speed = 0
        if np.isnan(instantaneous_speed):
            instantaneous_speed = 0

        features = np.array([cv2.contourArea(hull),
                             cv2.arcLength(hull,True),
                            instantaneous_speed +1.0
                             ])

        return features

    def _feature_distance(self, features):
        d = np.abs((self._fg_features - features) / self._fg_features) #fixme div by 0 possible?
        return np.sum(d)



    def _update_bg_model(self, img, fgmask=None):
        # todo array preallocation and np.ufuns will help to optimise this part !
        if self._bg_mean is None:
            self._bg_mean = img
            self._bg_sd = img

        learning_mat = np.ones_like(img) * self._learning_rate
        if fgmask is not None:
            learning_mat[fgmask] = 0

        self._bg_mean = learning_mat * img  + (1 - learning_mat) * self._bg_mean
        self._bg_sd = learning_mat * np.abs(self._bg_mean - img)  + (1 - learning_mat) * self._bg_sd



    def _find_position(self, img, mask):
        # TODO preallocated buffers
        # TODO  slice me with mask
        #  TODO try exepect slice me with mask

        tmp = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
        tmp = cv2.GaussianBlur(tmp,(3,3), 1.5)

        if len(self._positions) > 0:
            pos = self._positions[-1]
        else:
            self._update_bg_model(tmp)
            return np.NaN, np.NaN
        fg_mask = None

        # cv2.imshow("m", self._bg_mean/255)

        fg = np.abs(tmp - self._bg_mean) > 10 #fixme magic number -> otsu
        fg = fg.astype(np.uint8) * 255

        yx = np.where(fg)

        if len(yx[0]) < 10: #TODO, OR if more than ~20% of the image is fg
            self._learning_rate *= self._increment
        else:
            yx = np.column_stack((yx[1],yx[0]))

            ms = MeanShift(bandwidth=7.5, bin_seeding=False) # todo magic number
            ms.fit(yx)
            labels = ms.labels_
            labels_unique = np.unique(labels)
            n_clusters_ = len(labels_unique)

            if n_clusters_ > 1:
                self._learning_rate *= self._increment
                cluster_features = [self._comput_blob_features(tmp,yx[labels==i,:]) for i in np.unique(labels)]
                good_clust = np.argmin([self._feature_distance(cf) for cf in cluster_features])
                good_points = yx[labels==good_clust ,:]
            else:
                self._learning_rate /= self._increment
                self._update_fg_blob_model(tmp, yx)
                good_points = yx
            fg_mask = np.zeros_like(tmp)
            hull = cv2.convexHull(good_points)
            # cv2.drawContours(fg_mask ,[hull],0, (255,0,0),-1)
            # cv2.imshow("t", fg_mask )

            moments = cv2.moments(hull)
            pos = moments['m10']/moments['m00'] + 1j * moments['m01']/moments['m00']


        if self._learning_rate > self._max_learning_rate:
            self._learning_rate = self._max_learning_rate

        if self._learning_rate < self._min_learning_rate:
            self._learning_rate = self._min_learning_rate

        self._update_bg_model(tmp,fg_mask)


        return pos,-1


