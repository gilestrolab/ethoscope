__author__ = 'quentin'

import collections
import copy


class BaseIntVariable(int):
    """
    Temlpate class for defining arbitrary variable types.
    Each class derived from this one should at least define the three following attributes:

    * `sql_data_type`, The MySQL data type. This allows to use minimal space to save data points.
    * `header_name`, The name of this variable. this will be used as the column name in the result table, so it must be unique.
    * `functional_type`, A keyword defining what type of variable this is. For instance "distance", "angle" or "proba". this allow specific post-processing per functional type.
    """

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
        return  super(BaseIntVariable, cls).__new__(cls, value)


class BaseBoolVariable(BaseIntVariable):
    functional_type = "bool"
    sql_data_type = "BOOLEAN"

class IsInferredVariable(BaseBoolVariable):
    header_name = "is_inferred"


class PhiVariable(BaseIntVariable):
    header_name = "phi"
    functional_type = "angle"


class BaseDistanceIntVar(BaseIntVariable):
    functional_type = "distance"

class mLogLik(BaseIntVariable):
    header_name= "mlog_L_x1000"
    functional_type = "proba"


class XYDistance(BaseIntVariable):
    header_name = "xy_dist_log10x1000"
    functional_type = "relative_distance_1e6"


class XorDistance(BaseIntVariable):
    header_name = "xor_dist"
    functional_type = "relative_distance_1e3"



class WidthVariable(BaseDistanceIntVar):
    header_name = "w"

class HeightVariable(BaseDistanceIntVar):
    header_name = "h"

class BaseRelativeVariable(BaseDistanceIntVar):
    """
    Variables that are expressed relatively to an origin can be converted to absolute using information form the ROI.

    """
    def to_absolute(self, roi):
        """

        :param roi:
        :type roi:
        :return:
        :rtype: classBaseRelativeVariable
        """
        return self.get_absolute_value(roi)
    def get_absolute_value(self, roi):
        raise NotImplementedError("Relative variable must implement a `get_absolute_value()` method")


class XPosVariable(BaseRelativeVariable):
    header_name = "x"
    def get_absolute_value(self, roi):
        out = int(self)

        ox, _ = roi.offset
        out += ox
        return XPosVariable(out)

class YPosVariable(BaseRelativeVariable):
    header_name = "y"
    def get_absolute_value(self, roi):
        out = int(self)
        _, oy = roi.offset
        out += oy
        return YPosVariable(out)


class DataPoint(collections.OrderedDict):

    def __init__(self, data):
        """
        A container to store variables. It derived from :class:`~collections.OrderedDict`.
        Variables are accessible by header name, which is an individual identifier
        of a variable type (see :class:`~ethoscope.core.variables.BaseIntVariable`):

        >>> from ethoscope.core.variables import DataPoint, XPosVariable, YPosVariable, HeightVariable
        >>> y = YPosVariable(18)
        >>> x = XPosVariable(32)
        >>> data = DataPoint([x,y])
        >>> print data["x"]
        >>> h = HeightVariable(3)
        >>> data.append(h)
        >>> print data


        :param data: a list of data points
        :type data: list(:class:`~ethoscope.core.variables.BaseIntVariable`)
        """
        collections.OrderedDict.__init__(self)
        for i in data:
            self.__setitem__(i.header_name, i)

    def copy(self):
        """
        Deep copy a data point. Copying using the `=` operator will simply create an alias to a `DataPoint`
        object (i.e. allow modification of the original object).

        :return: a copy of this object
        :rtype: :class:`~ethoscope.core.variables.DataPoint`
        """
        return DataPoint(copy.deepcopy(self.values()))

    def append(self, item):
        """
        Add a new variable in the `DataPoint` The order is preserved.

        :param item: A variable to be added.
        :param item: :class:`~ethoscope.core.variables.BaseIntVariable`
        :return:
        """
        self.__setitem__(item.header_name, item)

