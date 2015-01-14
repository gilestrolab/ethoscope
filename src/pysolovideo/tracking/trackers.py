__author__ = 'quentin'

import numpy as np
import cv2
from pysolovideo.utils.img_proc import merge_blobs
from pysolovideo.utils.debug import show
from collections import deque





class NoPositionError(Exception):
    pass

class BaseTracker(object):
    def __init__(self, roi,data=None):
        self._positions = deque()
        self._times =deque()
        self._data = data
        self._roi = roi
        self._last_non_inferred_time = 0
        self._max_history_length = 60  # in seconds
    def __call__(self, t, img):
        sub_img, mask = self._roi(img)
        try:
            point = self._find_position(sub_img,mask,t)
            if point is None:
                return None
            point = self.normalise_position(point)
            self._last_non_inferred_time = t
        except NoPositionError:
            if len(self._positions) == 0:
                return None
            else:
                point = self._infer_position(t)
                if point is None:
                    return None
                point["is_inferred"] = True


        self._positions.append(point)
        self._times.append(t)


        if len(self._times) > 2 and (self._times[-1] - self._times[0]) > self._max_history_length:
            self._positions.popleft()
            self._times.popleft()

        return point

    def _infer_position(self, t, max_time=60):
        if len(self._times) == 0:
            return None
        if t - self._last_non_inferred_time  > max_time:
            return None

        return self._positions[-1]



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




class ObjectModel(object):
    """
    A class to model, update and predict foreground object (i.e. tracked animal).
    """
    def __init__(self, history_length=1000):
        #fixme this should be time, not number of points!
        self._features_header = [
            "fg_model_area",
            "fg_model_width",
            "fg_model_aspect_ratio",
            "fg_model_mean_grey"
        ]

        self._history_length = history_length
        self._ring_buff = np.zeros((self._history_length, len(self._features_header)), dtype=np.float32, order="F")
        self._std_buff = np.zeros((self._history_length, len(self._features_header)), dtype=np.float32, order="F")
        self._ring_buff_idx=0
        self._is_ready = False
        self._roi_img_buff = None
        self._mask_img_buff = None

    @property
    def is_ready(self):
        return self._is_ready
    @property
    def features_header(self):
        return self._features_header


    def update(self, img, contour):

        self._ring_buff[self._ring_buff_idx] = self.compute_features(img,contour)

        self._ring_buff_idx += 1

        if self._ring_buff_idx == self._history_length:
            self._is_ready = True
            self._ring_buff_idx = 0



        return self._ring_buff[self._ring_buff_idx]

    def distance(self, features):

        if not self._is_ready:
            last_row = self._ring_buff_idx
        else:
            last_row = self._history_length -1

        means = np.mean(self._ring_buff[:last_row], 0)

        np.subtract(self._ring_buff[:last_row], means, self._std_buff[:last_row])
        np.abs(self._std_buff[:last_row], self._std_buff[:last_row])

        stds = np.mean(self._std_buff[:last_row], 0)


        # print means
        # print stds
        # print features
        # stds = np.std(self._ring_buff, 0)

        a = 1 / (stds* np.sqrt(2.0 * np.pi))
        b = np.exp(- (features - means) ** 2  / (2 * stds ** 2))

        likelihoods =  a * b
        logls = np.sum(np.log10(likelihoods))


        return -1.0 * logls


    def compute_features(self, img, contour):
        x,y,w,h = cv2.boundingRect(contour)

        # fixme this is potentially slow!
        # at leat, we can preallocate arrays


        if self._roi_img_buff is None:
            self._roi_img_buff = cv2.cvtColor(img[y : y + h, x : x + w, :],cv2.COLOR_BGR2GRAY)
            self._mask_img_buff = np.zeros_like(self._roi_img_buff)

        cv2.cvtColor(img[y : y + h, x : x + w, :],cv2.COLOR_BGR2GRAY,self._roi_img_buff)
        self._mask_img_buff.fill(0)

        cv2.drawContours(self._mask_img_buff,[contour],-1, (1,1,1),-1,offset=(-x,-y))
        mean_col = cv2.mean(self._roi_img_buff, self._mask_img_buff)[0]
        # todo NOT use colour

        (_,_) ,(width,height), angle  = cv2.minAreaRect(contour)
        width, height= max(width,height), min(width,height)
        ar = ((height+1) / (width+1))
        #todo speed should use time
        #
        # if len(self.positions) > 2:
        #
        #     pm, pmm = self._positions[-1],self._positions[-2]
        #     xm, xmm = pm["x"], pmm["x"]
        #     ym, ymm = pm["y"], pmm["y"]
        #
        #     instantaneous_speed = abs(xm + 1j*ym - xmm + 1j*ymm)
        # else:
        #     instantaneous_speed = 0
        # if np.isnan(instantaneous_speed):
        #     instantaneous_speed = 0

        features = np.array([np.log10(cv2.contourArea(contour) + 1.0),
                            width + 1,
                            ar,
                            #instantaneous_speed +1.0,
                            mean_col +1
                            # 1.0
                             ])

        return features


class BackgroundModel(object):
    """
    A class to model background. It uses a dynamic running average and support arbitrary and heterogeneous frame rates
    """
    def __init__(self, max_half_life=100., min_half_life=1., increment = 1.5):
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
        # self._bg_sd = None

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
            # self._bg_sd = np.zeros_like(img_t)
            # self._bg_sd.fill(128)

        if self._buff_alpha_matrix is None:
            self._buff_alpha_matrix = np.ones_like(img_t,dtype = np.float32)

        # the learning rate, alpha, is an exponential function of half life
        # it correspond to how much the present frame should account for the background

        lam =  np.log(2)/self._current_half_life
        # how much the current frame should be accounted for
        alpha = 1 - np.exp(-lam * dt)

        # set-p a matrix of learning rate. it is 0 where foreground map is true
        self._buff_alpha_matrix.fill(alpha)
        if fg_mask is not None:
            cv2.dilate(fg_mask,None,fg_mask)
            cv2.subtract(self._buff_alpha_matrix, self._buff_alpha_matrix, self._buff_alpha_matrix, mask=fg_mask)


        if self._buff_invert_alpha_mat is None:
            self._buff_invert_alpha_mat = 1 - self._buff_alpha_matrix
        else:
            np.subtract(1, self._buff_alpha_matrix, self._buff_invert_alpha_mat)

        # cv2.imshow("imt", img_t)
        # cv2.imshow("bgm", self._bg_mean.astype(np.uint8))

        np.multiply(self._buff_alpha_matrix, img_t, self._buff_alpha_matrix)
        np.multiply(self._buff_invert_alpha_mat, self._bg_mean, self._buff_invert_alpha_mat)
        np.add(self._buff_alpha_matrix, self._buff_invert_alpha_mat, self._bg_mean)

        self.last_t = t


class AdaptiveBGModel(BaseTracker):
    fg_model = ObjectModel()

    def __init__(self, roi, data=None):

        self._object_expected_size = 0.10 # proportion of the roi main axis
        self._max_area = 10 * self._object_expected_size ** 2
        self._smooth_mode = deque()
        self._smooth_mode_tstamp = deque()
        self._smooth_mode_window_dt = 30 #seconds
        # self._bg_mean = None
        # self._fg_features = None
        # self._bg_sd = None
        # self._learning_mat_buff = None

        super(AdaptiveBGModel, self).__init__(roi, data)
        self._bg_model = BackgroundModel()
        self._max_m_log_lik = 15.
        self._buff_grey = None
        self._buff_grey_blurred = None
        self._buff_fg = None
        self._buff_convolved_mask = None

    def _pre_process_input_minimal(self, img, mask, t, darker_fg=True):
        if self._buff_grey is None:
            self._buff_grey = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
            if mask is None:
                mask = np.ones_like(self._buff_grey) * 255

        cv2.cvtColor(img,cv2.COLOR_BGR2GRAY, self._buff_grey)
        if darker_fg:
            cv2.subtract(255, self._buff_grey, self._buff_grey)


        if mask is not None:
            cv2.bitwise_and(self._buff_grey, mask, self._buff_grey)
            return self._buff_grey

    def _pre_process_input(self, img, mask, t):

        blur_rad = int(self._object_expected_size * np.max(img.shape) * 2.0)
        if blur_rad % 2 == 0:
            blur_rad += 1


        if self._buff_grey is None:
            self._buff_grey = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
            self._buff_grey_blurred = np.empty_like(self._buff_grey)
            # self._buff_grey_blurred = np.empty_like(self._buff_grey)
            if mask is None:
                mask = np.ones_like(self._buff_grey) * 255

            mask_conv = cv2.blur(mask,(blur_rad, blur_rad))

            self._buff_convolved_mask  = (1/255.0 *  mask_conv.astype(np.float32))


        cv2.cvtColor(img,cv2.COLOR_BGR2GRAY, self._buff_grey)





        hist = cv2.calcHist([self._buff_grey], [0], None, [256], [0,255]).ravel()
        hist = np.convolve(hist, [1] * 3)
        mode =  np.argmax(hist)

        self._smooth_mode.append(mode)
        self._smooth_mode_tstamp.append(t)

        if len(self._smooth_mode_tstamp) >2 and self._smooth_mode_tstamp[-1] - self._smooth_mode_tstamp[0] > self._smooth_mode_window_dt:
            self._smooth_mode.popleft()
            self._smooth_mode_tstamp.popleft()


        mode = np.mean(list(self._smooth_mode))
        scale = 128. / mode


        # cv2.GaussianBlur(self._buff_grey,(5,5), 1.5,self._buff_grey)

        cv2.multiply(self._buff_grey, scale, dst = self._buff_grey)


        cv2.bitwise_and(self._buff_grey, mask, self._buff_grey)

        cv2.blur(self._buff_grey,(blur_rad, blur_rad), self._buff_grey_blurred)
        #fixme could be optimised
        self._buff_grey_blurred = (self._buff_grey_blurred / self._buff_convolved_mask).astype(np.uint8)


        cv2.absdiff(self._buff_grey, self._buff_grey_blurred, self._buff_grey)

        if mask is not None:
            cv2.bitwise_and(self._buff_grey, mask, self._buff_grey)
            return self._buff_grey


    def _find_position(self, img, mask,t):
        grey = self._pre_process_input_minimal(img, mask, t)
        # grey = self._pre_process_input(img, mask, t)
        try:
            return self._track(img, grey, mask, t)
        except NoPositionError:
            self._bg_model.update(grey, t)
            raise NoPositionError


    def _track(self, img,  grey, mask,t):


        if self._bg_model.bg_img is None:
            self._buff_fg = np.empty_like(grey)
            raise NoPositionError


        bg = self._bg_model.bg_img.astype(np.uint8)

        cv2.subtract(grey, bg, self._buff_fg)

        # cv2.imshow("grey", grey)
        # cv2.imshow("fg", self._buff_fg*3)
        # cv2.imshow("bg", bg)

        #fixme magic number
        cv2.threshold(self._buff_fg,15,255,cv2.THRESH_BINARY, dst=self._buff_fg)

        # cv2.imshow("bin_fg", self._buff_fg)


        n_fg_pix = np.count_nonzero(self._buff_fg)
        prop_fg_pix  = n_fg_pix / (1.0 * grey.shape[0] * grey.shape[1])

        is_ambiguous = False
        if  prop_fg_pix > self._max_area:
            self._bg_model.increase_learning_rate()
            raise NoPositionError

        # fixme magic num
        contours,hierarchy = cv2.findContours(self._buff_fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)


        if len(contours) == 0:
            self._bg_model.increase_learning_rate()
            raise NoPositionError


        elif len(contours) > 1:

            if not self.fg_model.is_ready:
                raise NoPositionError


            hulls = [cv2.convexHull( c) for c in contours]
            hulls = merge_blobs(hulls)
            if len(hulls) > 1:
                is_ambiguous = True
            cluster_features = [self.fg_model.compute_features(img, h) for h in hulls]
            all_distances = [self.fg_model.distance(cf) for cf in cluster_features]
            good_clust = np.argmin(all_distances)

            hull = hulls[good_clust]
            distance = all_distances[good_clust]
            features = cluster_features[good_clust]

            if hull.shape[0] < 3:
                raise NoPositionError
        else:

            hull = cv2.convexHull(contours[0])
            if hull.shape[0] < 3:
                self._bg_model.increase_learning_rate()
                raise NoPositionError

            features = self.fg_model.compute_features(img, hull)
            distance = self.fg_model.distance(features)

        if distance > self._max_m_log_lik:
            self._bg_model.increase_learning_rate()
            raise NoPositionError


        (x,y) ,(w,h), angle  = cv2.minAreaRect(hull)

        self._buff_fg.fill(0)
        cv2.drawContours(self._buff_fg ,[hull],0, 1,-1)

        if mask is not None:
            cv2.bitwise_and(self._buff_fg, mask,  self._buff_fg)

        if is_ambiguous:
            self._bg_model.increase_learning_rate()
            self._bg_model.update(grey, t)
        else:
            self._bg_model.decrease_learning_rate()
            self._bg_model.update(grey, t, self._buff_fg)


        self.fg_model.update(img, hull)


        out_dic = {
            'x':x, 'y':y,
            'w':w, 'h':h,
            'phi':angle,
            "is_inferred": False,
            "m_log_lik": distance
        }

        feature_dic  = dict(zip(self.fg_model.features_header, features))

        return dict(out_dic.items() + feature_dic.items())



