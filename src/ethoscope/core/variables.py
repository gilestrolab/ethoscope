__author__ = 'quentin'


class BaseIntVariable(int):
    """
    Template class for defining arbitrary variable types.
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
    """
    Abstract type encoding boolean values. Internally stored as int as bool type cannot be derived.
    """
    functional_type = "bool"
    sql_data_type = "BOOLEAN"

class IsInferredVariable(BaseBoolVariable):
    """
    Type encoding whether a data point is inferred (from past values) or observed; 0 or 1, respectively.
    """
    header_name = "is_inferred"


class PhiVariable(BaseIntVariable):
    """
    Type encoding the angle of a detected object, in degrees.
    """
    header_name = "phi"
    functional_type = "angle"

class Label(BaseIntVariable):
    """
    Type encoding a discrete label when several objects, in the same ROI, are detected.
    """
    header_name = "label"
    functional_type = "label"


class BaseDistanceIntVar(BaseIntVariable):
    """
    Abstract type encoding variables representing distances.
    """
    functional_type = "distance"

class mLogLik(BaseIntVariable):
    """
    Type representing a log likelihood. It should be multiplied by 1000 to be stored as an int.
    """
    header_name= "mlog_L_x1000"
    functional_type = "proba"


class XYDistance(BaseIntVariable):
    """
    Type storing distance moved between two consecutive observations. Log10 x 1000 is used so that floating point distance is stored as an int.
    """
    header_name = "xy_dist_log10x1000"
    functional_type = "relative_distance_1e6"


class WidthVariable(BaseDistanceIntVar):
    """
    Type storing the width of a detected object.
    """
    header_name = "w"

class HeightVariable(BaseDistanceIntVar):
    """
    Type storing the height of a detected object.
    """
    header_name = "h"

class BaseRelativeVariable(BaseDistanceIntVar):
    """
    Abstract type encoding distance variables that can be expressed relatively to an origin.
    They converted to absolute using information form the ROI.
    """
    def to_absolute(self, roi):
        """
        Converts a positional variable from a relative (to the top left of a ROI) to an absolute (e.i. top left of the parent image).

        :param roi: a region of interest
        :type roi: :class:`~ethoscope.rois.roi_builders.ROI`.
        :return: A new variable
        :rtype: :class:`~ethoscope.core.variable.BaseRelativeVariable`
        """
        return self._get_absolute_value(roi)
    def _get_absolute_value(self, roi):
        raise NotImplementedError("Relative variable must implement a `get_absolute_value()` method")


class XPosVariable(BaseRelativeVariable):
    """
    Type storing the X position of a detected object.
    """
    header_name = "x"
    def _get_absolute_value(self, roi):
        out = int(self)

        ox, _ = roi.offset
        out += ox
        return XPosVariable(out)

class YPosVariable(BaseRelativeVariable):
    """
    Type storing the Y position of a detected object.
    """
    header_name = "y"
    def _get_absolute_value(self, roi):
        out = int(self)
        _, oy = roi.offset
        out += oy
        return YPosVariable(out)


