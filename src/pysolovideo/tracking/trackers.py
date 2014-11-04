__author__ = 'quentin'

import numpy as np
import cv2
from pysolovideo.utils.img_proc import merge_blobs
from pysolovideo.utils.debug import show





class NoPositionError(Exception):
    pass

class BaseTracker(object):
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
                point = self._positions[-1].copy()
                point["is_inferred"] = True

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






class BackgroundModel(object):
    def __init__(self, max_half_life=100., min_half_life=5., increment = 1.5):
        # the maximal half life of a pixel from background, in seconds
        self._max_half_life = float(max_half_life)
        # the minimal one
        self._min_half_life = float(min_half_life)

        # starts with the fastest learning rate
        self._current_half_life = self._min_half_life

        # fixme theoritically this should depend on time, not frame index
        self._increment = 1.1
        # the mean background
        self._bg_mean = None
        self._bg_sd = None

        self._buff_alpha_matrix = None
        self._buff_invert_alpha_mat = None
        # the time stamp of the frame las used to update
        self.last_t = 0

    @property
    def bg_img(self):
        return self._bg_mean

    def increase_learning_rate(self):
        self._current_half_life  /=  self._increment

    def decrease_learning_rate(self):
        self._current_half_life  *=  self._increment


    def update(self, img_t, t, fg_mask=None):
        dt = float(t - self.last_t)
        assert(dt >= 0)

        # clip the half life to possible value:
        self._current_half_life = np.clip(self._current_half_life, self._min_half_life, self._max_half_life)

        # ensure preallocated buffers exist. otherwise, initialise them
        if self._bg_mean is None:
            self._bg_mean = img_t.astype(np.float32)
            self._bg_sd = np.zeros_like(img_t)
            self._bg_sd.fill(128)

        if self._buff_alpha_matrix is None:
            self._buff_alpha_matrix = np.ones_like(img_t,dtype = np.float32)

        # the learning rate, alpha, is an exponential function of half life
        # it correspond to how much the present frame should account for the background

        lam =  np.log(2)/self._current_half_life
        # how much the current frame should be accounted for
        alpha = 1 - np.exp(-lam * dt)
        print self._current_half_life, lam, alpha

        # print dt , alpha, self._current_half_life

        # set-p a matrix of learning rate. it is 0 where foreground map is true
        self._buff_alpha_matrix.fill(alpha)
        if fg_mask is not None:
            cv2.dilate(fg_mask,None,fg_mask)
            cv2.subtract(self._buff_alpha_matrix, self._buff_alpha_matrix, self._buff_alpha_matrix, mask=fg_mask)


        if self._buff_invert_alpha_mat is None:
            self._buff_invert_alpha_mat = 1 - self._buff_alpha_matrix
        else:
            np.subtract(1, self._buff_alpha_matrix, self._buff_invert_alpha_mat)


        np.multiply(self._buff_alpha_matrix, img_t, self._buff_alpha_matrix)
        np.multiply(self._buff_invert_alpha_mat, self._bg_mean, self._buff_invert_alpha_mat)
        np.add(self._buff_alpha_matrix, self._buff_invert_alpha_mat, self._bg_mean)

        self.last_t = t


class AdaptiveBGModel2(BaseTracker):
    def __init__(self, roi, data=None):

        self._object_expected_size = 0.05 # proportion of the roi main axis
        self._max_area = 10 * self._object_expected_size ** 2
        self._bg_mean = None
        self._fg_features = None
        self._bg_sd = None
        self._learning_mat_buff = None

        super(AdaptiveBGModel2, self).__init__(roi, data)
        self._bg_model = BackgroundModel()

        self._buff_grey = None
        self._buff_grey_blurred = None
        self._buff_fg = None

    def _pre_process_input(self, img, mask):
        if self._buff_grey is None:
            self._buff_grey = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
            self._buff_grey_blurred = np.empty_like(self._buff_grey)
            # self._buff_grey_blurred = np.empty_like(self._buff_grey)

        cv2.cvtColor(img,cv2.COLOR_BGR2GRAY, self._buff_grey)

        blur_rad = int(self._object_expected_size * np.max(self._buff_grey.shape) * 2.0)
        if blur_rad % 2 == 0:
            blur_rad += 1



        # too slow?
        # cv2.medianBlur(self._buff_grey,blur_rad, self._buff_grey_blurred)
        scale = 128. / np.median(self._buff_grey)
        print "scale", scale
        # cv2.imshow("gray",self._buff_grey)
        cv2.multiply(self._buff_grey, scale, dst = self._buff_grey)
        # cv2.imshow("norm", self._buff_grey)

        cv2.GaussianBlur(self._buff_grey,(blur_rad, blur_rad),5.0, self._buff_grey_blurred)
        cv2.GaussianBlur(self._buff_grey,(5,5), 2.5,self._buff_grey)
        cv2.absdiff(self._buff_grey, self._buff_grey_blurred, self._buff_grey)


        if mask is not None:
            cv2.bitwise_and(self._buff_grey, self._buff_grey, self._buff_grey, mask=mask)
            return self._buff_grey

    #todo human friendly time/alpha
    def _update_fg_blob_model(self, img, contour, lr = 1e-3):
        features = self._comput_blob_features(img, contour)
        if self._fg_features is None:
            self._fg_features = features

        self._fg_features = lr * features  + (1 - lr) * self._fg_features


    def _comput_blob_features(self, img, contour):
        hull = contour

        # x,y,w,h = cv2.boundingRect(contour)

        # roi = img[y : y + h, x : x + w]
        # mask = np.zeros_like(roi)

        #
        # cv2.drawContours(mask,[hull],-1, 1,-1,offset=(-x,-y))
        # mean_col = cv2.mean(roi,mask)[0]
        # mean_col = 0
        #todo speed should use time
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
                            #cv2.arcLength(hull,True) + 1.0,
                            instantaneous_speed +1.0,
                            # mean_col +1
                             ])

        return features

    def _feature_distance(self, features):
        d = np.abs((self._fg_features - features) / self._fg_features) #fixme div by 0 possible?
        return np.sum(d)

    def _find_position(self, img, mask,t):
        grey = self._pre_process_input(img, mask)
        try:
            return self._track(grey, mask, t)
        except NoPositionError:
            self._bg_model.update(grey, t)
            raise NoPositionError

    def _track(self, grey, mask,t):
        if self._bg_model.bg_img is None:
            self._buff_fg = np.empty_like(grey)
            raise NoPositionError


        bg = self._bg_model.bg_img.astype(np.uint8)


        # cv2.imshow("gr",grey* 10)

        cv2.subtract(grey, bg, self._buff_fg)

        # cv2.subtract( bg, grey, self._buff_fg)

        # cv2.imshow("bg",bg * 10)
        # cv2.imshow("fg",self._buff_fg * 10)


        cv2.threshold(self._buff_fg,10,255,cv2.THRESH_BINARY, dst=self._buff_fg)
        # cv2.threshold(self._buff_fg,-1,255,cv2.THRESH_BINARY | cv2.THRESH_OTSU, dst=self._buff_fg)

        # cv2.threshold(self._buff_fg,15,255,cv2.THRESH_BINARY , dst=self._buff_fg)

        n_fg_pix = np.count_nonzero(self._buff_fg)
        prop_fg_pix  = n_fg_pix / (1.0 * grey.shape[0] * grey.shape[1])
        if  prop_fg_pix > self._max_area:
            self._bg_model.increase_learning_rate()
            raise NoPositionError

        # fixme magic num
        contours,hierarchy = cv2.findContours(self._buff_fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)


        if len(contours) == 0:
            self._bg_model.increase_learning_rate()
            raise NoPositionError


        elif len(contours) > 1:
            self._bg_model.increase_learning_rate()
            if self._fg_features is None:
                raise NoPositionError

            hulls = [cv2.convexHull( c) for c in contours]
            hulls = merge_blobs(hulls)

            cluster_features = [self._comput_blob_features(grey, h) for h in hulls]
            good_clust = np.argmin([self._feature_distance(cf) for cf in cluster_features])
            hull = hulls[good_clust]

        else:
            self._bg_model.decrease_learning_rate()
            hull = cv2.convexHull(contours[0])
            self._update_fg_blob_model(grey, hull)

        # small hull ==> erroneous bounding rectangle
        if hull.shape[0] < 3:
            raise NoPositionError

        (x,y) ,(w,h), angle  = cv2.minAreaRect(hull)

        self._buff_fg.fill(0)
        cv2.drawContours(self._buff_fg ,[hull],0, 1,-1)

        if mask is not None:
            cv2.bitwise_and(self._buff_fg, mask,  self._buff_fg)

        self._bg_model.update(grey, t, self._buff_fg)
        return {
            'x':x, 'y':y,
            'w':w, 'h':h,
            'phi':angle,
            "is_inferred": False
        }



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

    def _update_fg_blob_model(self, img, contour, lr = 1e-3):
        features = self._comput_blob_features(img, contour)
        if self._fg_features is None:
            self._fg_features = features

        self._fg_features = lr * features  + (1 - lr) * self._fg_features


    def _comput_blob_features(self, img, contour, lr = 1e-5):
        hull = contour

        x,y,w,h = cv2.boundingRect(contour)

        roi = img[y : y + h, x : x + w]
        # mask = np.zeros_like(roi)

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
        cv2.threshold(fg,10,255,cv2.THRESH_BINARY , dst=fg)
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
            hulls = merge_blobs(hulls)

            cluster_features = [self._comput_blob_features(grey, h) for h in hulls]
            good_clust = np.argmin([self._feature_distance(cf) for cf in cluster_features])
            hull = hulls[good_clust]

        else:
            self._learning_rate /= self._increment
            hull = cv2.convexHull(contours[0])
            self._update_fg_blob_model(grey, hull)

        # small hull ==> erroneous bounding rectangle
        if hull.shape[0] < 3:
            raise NoPositionError

        (x,y) ,(w,h), angle  = cv2.minAreaRect(hull)


        fg.fill(0)
        cv2.drawContours( fg ,[hull],0, 1,-1)

        self._update_bg_model(grey, fg)


        return {
            'x':x,
            'y':y,
            'w':w,
            'h':h,
            'phi':angle
        }
