import collections
import copy

__author__ = 'quentin'


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
        :rtype: :class:`~ethoscope.core.data_point.DataPoint`
        """
        return DataPoint(copy.deepcopy(list(self.values())))

    def append(self, item):
        """
        Add a new variable in the `DataPoint` The order is preserved.

        :param item: A variable to be added.
        :param item: :class:`~ethoscope.core.variables.BaseIntVariable`
        :return:
        """
        self.__setitem__(item.header_name, item)