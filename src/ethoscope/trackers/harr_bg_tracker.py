from ethoscope.trackers.trackers import BaseTracker, NoPositionError
from ethoscope.core.data_point import DataPoint
from adaptive_bg_tracker import BackgroundModel
from ethoscope.core.variables import *
import cv2
import numpy as np
from matplotlib import pyplot as plt


class ObjectModel(object):
    def __init__(self):
        self.img = None
        self.mask = None
        self.hist_mask = None
        self.hist_feature = []
        self.hist_feature_len = 150
        self.point_feature = []
        self.point_feature_len = 2
        self.x = None
        self.y = None
        self.w = None
        self.h = None
        self.phi = None

    def add_point_feature(self, feature_params):
        if self.mask is not None:
            mask = self.mask.copy()
            for i, j in [np.int32(tr[-1]) for tr in self.point_feature]:
                cv2.circle(mask, (i, j), 5, 0, -1)
            p = cv2.goodFeaturesToTrack(self.img, mask=mask, **feature_params)
            if p is not None:
                for i, j in np.float32(p).reshape(-1, 2):
                    self.point_feature.append([(i, j)])

    def update_point_feature(self, pre_grey, grey, lk_params):
        if len(self.point_feature):
            p0 = np.float32([tr[-1] for tr in self.point_feature]).reshape(-1, 1, 2)
            p1, st, err = cv2.calcOpticalFlowPyrLK(pre_grey, grey, p0, None, **lk_params)
            p0r, st, err = cv2.calcOpticalFlowPyrLK(grey, pre_grey, p1, None, **lk_params)
            d = abs(p0 - p0r).reshape(-1, 2).max(-1)
            good = d < 1
            new_features = []
            for tr, (x, y), good_flag in zip(self.point_feature, p1.reshape(-1, 2), good):
                if not good_flag or np.linalg.norm((x - self.x, y - self.y)) > 45:
                    continue
                tr.append((x, y))
                if len(tr) > self.point_feature_len:
                    del tr[0]
                new_features.append(tr)
            self.point_feature = new_features

    def update_hist_feature(self):
        hist = cv2.calcHist([self.img], [0], self.hist_mask, [100], [0, 101])
        self.hist_feature.append(hist)
        if len(self.hist_feature) > self.hist_feature_len:
            del self.hist_feature[0]

    def of_track(self):
        vec = []
        for tr in self.point_feature:
            if len(tr) > 1:
                tr = np.array(tr)
                v = tr[-1] - tr[-2]
                if np.linalg.norm(v) >= 0.5:
                    vec.append(v)
        dx, dy = np.mean(vec, axis=0) if vec else (0, 0)
        self.x += int(round(dx))
        self.y += int(round(dy))
        self.w = 10
        self.h = 10
        self.phi = 0

    def bg_track(self):
        contours, _ = cv2.findContours(self.mask, 0, 1)
        ((self.x, self.y), (self.w, self.h), self.phi) = cv2.fitEllipse(contours[0])
        self.x = int(round(self.x))
        self.y = int(round(self.y))
        self.w = int(round(self.w))
        self.h = int(round(self.h))
        self.phi = int(round(self.phi))

    def get_position(self):
        x = XPosVariable(self.x - 30)
        y = YPosVariable(self.y)
        w = WidthVariable(self.w)
        h = HeightVariable(self.h)
        phi = PhiVariable(self.phi)
        return DataPoint([x, y, w, h, phi])


class harr_bg_tracker(BaseTracker):
    def __init__(self, roi, data):
        super(harr_bg_tracker, self).__init__(roi, data)
        self._bg_model = BackgroundModel()
        self.objs = [ObjectModel(), ObjectModel()]
        self.cascade = cv2.CascadeClassifier(self._data)
        self.appearance_flag = False
        self.lk_params = dict(winSize=(15, 15), maxLevel=0, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03))
        self.feature_params = dict(maxCorners=100, qualityLevel=0.5, minDistance=5, blockSize=5)
        self.collision_start_time = None

    def _find_position(self, img, mask, t):
        return self._track(img, mask, t)

    def _distance(self, p1, p2):
        return max(abs(p1[0] - p2[0]), abs(p1[1] - p2[1]))

    def distance(self, objs=None):
        try:
            return self._distance(objs[0], objs[1])
        except:
            prev_p1 = (self._positions[-1][0]["x"], self._positions[-1][0]["y"])
            prev_p2 = (self._positions[-1][1]["x"], self._positions[-1][1]["y"])
            return self._distance(prev_p1, prev_p2)

    def is_collision(self, objs=None):
        return self.distance(objs) <= 70

    def check_objs(self, objs, mask, distance_flag=False):
        if not len(objs):
            return [None, None]
        prev_p1 = (self._positions[-1][0]["x"], self._positions[-1][0]["y"])
        prev_p2 = (self._positions[-1][1]["x"], self._positions[-1][1]["y"])
        candidate = []
        for obj in objs:
            p = (obj[0] + obj[2] / 2 - 30, obj[1] + obj[3] / 2)
            d1 = self._distance(p, prev_p1)
            d2 = self._distance(p, prev_p2)
            m = mask[obj[1]: obj[1] + obj[3], obj[0]: obj[0] + obj[2]].copy()
            m = len(np.where(m == 255)[0])
            if (distance_flag and (min(d1, d2) < self.distance() / 4)) or (not distance_flag and (m > 200 or min(d1, d2) < 70)):
                candidate.append((obj, d1, d2))
        if not candidate:
            return [None, None]
        else:
            if len(candidate) == 1:
                candidate = candidate[0]
                if candidate[1] < candidate[2]:
                    return [candidate[0], None]
                else:
                    return [None, candidate[0]]
            out1 = sorted(candidate, key=lambda x: x[1])
            out2 = sorted(candidate, key=lambda x: x[2])
            if np.all(out1[0][0] == out2[0][0]):
                if out1[0][1] <= out1[0][2]:
                    return [out1[0][0], out2[1][0]]
                else:
                    return [out1[1][0], out2[0][0]]
            else:
                return [out1[0][0], out2[0][0]]

    def _track(self, img, mask, t):
        grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if self._bg_model.bg_img is None:
            self._bg_model._bg_mean = grey.astype(np.float32)
        bg = self._bg_model.bg_img.astype(np.uint8)
        fg = cv2.subtract(bg, grey)
        _, fg_mask = cv2.threshold(fg, 20, 255, cv2.THRESH_BINARY)
        kernel = np.ones((4, 4), np.uint8)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        self._bg_model.update(grey, t, fg_mask)

        cascade_objs = self.cascade.detectMultiScale(grey, 4, 4, 0, (80, 80), (110, 110))
        if not self._positions:
            if len(cascade_objs) == 2 and not self.is_collision(cascade_objs):
                out = []
                for obj, (x, y, w, h) in zip(self.objs, cascade_objs):
                    obj.x = x + w / 2
                    obj.y = y + h / 2
                    obj.w = 10
                    obj.h = 10
                    obj.phi = 0
                    obj.img = grey
                    obj.mask = np.zeros_like(grey)
                    obj.mask[y - 15: y + 15, x - 15: x + 15] = 255
                    obj.add_point_feature(self.feature_params)
                    out.append(obj.get_position())
                self.pre_grey = grey
                return out
            else:
                return []
        else:
            out = []
            if not self.is_collision(cascade_objs):
                self.collision_start_time = None
                if self.appearance_flag:
                    cascade_objs = self.check_objs(cascade_objs, fg_mask)
                    if any(cascade_obj is None for cascade_obj in cascade_objs):
                        raise NoPositionError
                    else:
                        trainData = []
                        responses = []
                        for i, obj in enumerate(self.objs):
                            for hist in obj.hist_feature:
                                trainData.append(hist)
                                responses.append(i)
                        knn = cv2.KNearest()
                        trainData = np.array(trainData, dtype=np.float32)
                        responses = np.array(responses)
                        knn.train(trainData, responses, maxK=len(responses) / 2)
                        knn_res = []
                        for (x, y, w, h) in cascade_objs:
                            x += w / 2
                            y += h / 2
                            mask = np.zeros_like(grey)
                            mask[y - 35: y + 35, x - 35: x + 35] = 255
                            hist = cv2.calcHist([fg], [0], mask, [100], [0, 101])
                            hist = np.array([hist], dtype=np.float32)
                            _, results, neighbours, dist = knn.find_nearest(hist, len(responses) / 2)
                            knn_res.append([results[0][0], np.count_nonzero(neighbours == results[0][0])])

                        if knn_res[0][0] == knn_res[1][0]:
                            if knn_res[0][1] < knn_res[1][1]:
                                knn_res[0][0] = 1 - knn_res[1][0]
                            else:
                                knn_res[1][0] = 1 - knn_res[0][0]
                        for (x, y, w, h), res in zip(cascade_objs, knn_res):
                            res = int(res[0])
                            x += w / 2
                            y += h / 2
                            self.objs[res].img = np.zeros_like(grey)
                            self.objs[res].mask = np.zeros_like(grey)
                            self.objs[res].hist_mask = np.zeros_like(grey)
                            self.objs[res].img[y - 35: y + 35, x - 35: x + 35] = fg[y - 35: y + 35, x - 35: x + 35]
                            self.objs[res].mask[y - 35: y + 35, x - 35: x + 35] = fg_mask[y - 35: y + 35, x - 35: x + 35]
                            self.objs[res].hist_mask[y - 35: y + 35, x - 35: x + 35] = 255
                            self.objs[res].update_hist_feature()
                            self.objs[res].add_point_feature(self.feature_params)
                            self.objs[res].x = x
                            self.objs[res].y = y
                            self.objs[res].w = 10
                            self.objs[res].h = 10
                            self.objs[res].phi = 0
                        for obj in self.objs:
                            if len(np.where(obj.mask == 255)[0]) > 200:
                                obj.bg_track()
                                out.append(obj.get_position())
                            else:
                                out.append(obj.get_position())
                        self.appearance_flag = False
                else:
                    cascade_objs = self.check_objs(cascade_objs, fg_mask)
                    for cascade_obj, obj in zip(cascade_objs, self.objs):
                        if cascade_obj is None:
                            obj.update_point_feature(self.pre_grey, grey, self.lk_params)
                            obj.of_track()
                            obj.img = np.zeros_like(grey)
                            obj.mask = np.zeros_like(grey)
                            obj.hist_mask = np.zeros_like(grey)
                            obj.img[obj.y - 35: obj.y + 35, obj.x - 35: obj.x + 35] = fg[obj.y - 35: obj.y + 35, obj.x - 35: obj.x + 35]
                            obj.mask[obj.y - 35: obj.y + 35, obj.x - 35: obj.x + 35] = fg_mask[obj.y - 35: obj.y + 35, obj.x - 35: obj.x + 35]
                            obj.hist_mask[obj.y - 35: obj.y + 35, obj.x - 35: obj.x + 35] = 255
                            obj.update_hist_feature()
                            obj.add_point_feature(self.feature_params)
                            if len(np.where(obj.mask == 255)[0]) > 200:
                                obj.bg_track()
                                out.append(obj.get_position())
                            else:
                                out.append(obj.get_position())
                        else:
                            obj.update_point_feature(self.pre_grey, grey, self.lk_params)
                            x, y, w, h = cascade_obj
                            x += w / 2
                            y += h / 2
                            obj.img = np.zeros_like(grey)
                            obj.mask = np.zeros_like(grey)
                            obj.hist_mask = np.zeros_like(grey)
                            obj.img[y - 35: y + 35, x - 35: x + 35] = fg[y - 35: y + 35, x - 35: x + 35]
                            obj.mask[y - 35: y + 35, x - 35: x + 35] = fg_mask[y - 35: y + 35, x - 35: x + 35]
                            obj.hist_mask[y - 35: y + 35, x - 35: x + 35] = 255
                            obj.update_hist_feature()
                            obj.add_point_feature(self.feature_params)
                            if len(np.where(obj.mask == 255)[0]) > 200:
                                obj.bg_track()
                                out.append(obj.get_position())
                            else:
                                obj.x = x
                                obj.y = y
                                obj.w = 10
                                obj.h = 10
                                obj.phi = 0
                                out.append(obj.get_position())
            else:
                cascade_objs = self.check_objs(cascade_objs, fg_mask, True)
                if self.collision_start_time is None:
                    self.collision_start_time = t
                    self.collision_start_mask_size = len(np.where(fg_mask == 255)[0])
                for obj, cascade_obj in zip(self.objs, cascade_objs):
                    if cascade_obj is not None and not self.appearance_flag:
                        obj.update_point_feature(self.pre_grey, grey, self.lk_params)
                        x, y, w, h = cascade_obj
                        x += w / 2
                        y += h / 2
                        obj.x = x
                        obj.y = y
                        obj.w = 10
                        obj.h = 10
                        obj.phi = 0
                        out.append(obj.get_position())
                    else:
                        obj.update_point_feature(self.pre_grey, grey, self.lk_params)
                        obj.of_track()
                        out.append(obj.get_position())
                if sum(len(obj.point_feature) for obj in self.objs) == 0:
                    self.appearance_flag = True
                for obj in self.objs:
                    if len(obj.hist_feature) != obj.hist_feature_len:
                        self.appearance_flag = False
                    elif t - self.collision_start_time > 1000 and self.collision_start_mask_size - len(np.where(fg_mask == 255)[0]) > self.collision_start_mask_size / 4:
                        self.appearance_flag = True
                        break
        self.pre_grey = grey
        # for i, obj in enumerate(self.objs):
        #     cv2.polylines(img, [np.int32(tr) for tr in obj.point_feature], False, [(255, 0, 0), (0, 0, 255)][1 - i])
        if self._roi.idx == 8 and t == 16000:
            idx = -1
            for obj in self.objs:
                idx += 1
                cv2.imshow('img%d' % self._roi.idx, obj.img)
                cv2.imwrite('img%d.png' % idx, obj.img)
                cv2.imshow('hist_mask%d' % self._roi.idx, obj.hist_mask)
                if idx:
                    for i in obj.hist_feature[-15::]:
                        plt.figure(1)
                        plt.subplot(131)
                        plt.plot(i, 'b-')
                        plt.subplot(133)
                        plt.plot(i, 'b-')
                    plt.figure(2)
                    plt.subplot(131)
                    plt.plot(obj.hist_feature[-1], 'b-')
                    plt.subplot(133)
                    plt.plot(obj.hist_feature[-1], 'b-')
                else:
                    for i in obj.hist_feature[-15::]:
                        plt.figure(1)
                        plt.subplot(132)
                        plt.plot(i, 'r-')
                        plt.subplot(133)
                        plt.plot(i, 'r-')
                    plt.figure(2)
                    plt.subplot(132)
                    plt.plot(obj.hist_feature[-1], 'r-')
                    plt.subplot(133)
                    plt.plot(obj.hist_feature[-1], 'r-')
                    # plt.plot(obj.hist_feature[-1], 'r-')
            plt.show()
        return out
