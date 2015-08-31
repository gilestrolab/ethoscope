__author__ = 'quentin'

import collections
import copy


class IntVariableBase(int):
    sql_data_type = "SMALLINT"
    header_name = None
    functional_type = None # {distance, angle, bool, confidence,...}
    def __new__(cls, value):
        if cls.functional_type is None:
            raise NotImplementedError("Variables must have a functional data type such as 'distance', 'angle', 'bool', 'confidence'")
        if cls.sql_data_type is None:
            raise NotImplementedError("Variables must have an SQL data type such as INT")
        if cls.header_name is None:
            raise NotImplementedError("Variables must have a header name")
        return  super(IntVariableBase, cls).__new__(cls, value)


class BoolVariableBase(IntVariableBase):
    functional_type = "bool"
    sql_data_type = "BOOLEAN"

class IsInferredVariable(BoolVariableBase):
    header_name = "is_inferred"

class Strong(BoolVariableBase):
    header_name = "am_i_strong"

class PhiVariable(IntVariableBase):
    header_name = "phi"
    functional_type = "angle"


class DistanceIntVarBase(IntVariableBase):
    functional_type = "distance"

class mLogLik(IntVariableBase):
    header_name= "mlog_L_x1000"
    functional_type = "proba"


class XYDistance(IntVariableBase):
    header_name = "xy_dist_log10x1000"
    functional_type = "relative_distance_1e6"


class XorDistance(IntVariableBase):
    header_name = "xor_dist"
    functional_type = "relative_distance_1e3"



class WidthVariable(DistanceIntVarBase):
    header_name = "w"

class HeightVariable(DistanceIntVarBase):
    header_name = "h"

class RelativeVariableBase(DistanceIntVarBase):
    """
    Variables that are expressed relatively to an origin can be converted to absolute using information form the ROI

    """
    def to_absolute(self, roi):
        return self.get_absolute_value(roi)
    def get_absolute_value(self, roi):
        raise NotImplementedError("Relative variable must implement a `get_absolute_value()` method")


class XPosVariable(RelativeVariableBase):
    header_name = "x"
    def get_absolute_value(self, roi):
        out = int(self)

        ox, _ = roi.offset
        out += ox
        return XPosVariable(out)

class YPosVariable(RelativeVariableBase):
    header_name = "y"
    def get_absolute_value(self, roi):
        out = int(self)
        _, oy = roi.offset
        out += oy
        return YPosVariable(out)


class DataPoint(collections.OrderedDict):

    def __init__(self, data):
        collections.OrderedDict.__init__(self)
        for i in data:
            self.__setitem__(i.header_name, i)

    def copy(self):
        return DataPoint(copy.deepcopy(self.values()))

    def append(self, item):
        self.__setitem__(item.header_name, item)

