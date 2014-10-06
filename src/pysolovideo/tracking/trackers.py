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
                print "ambiguous!"
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
        cv2.imshow("result",img)
        cv2.waitKey(30)

        return pos, np.NaN


