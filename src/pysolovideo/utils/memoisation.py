__author__ = 'quentin'

from functools import wraps


def memoised_property(function):
    @wraps(function)
    def wrapper(self):
        if not isinstance(self, MemoisableObject):
            raise TypeError('Can only memoise properties of MemoisableObject instances')
        try:
            return self._memoised_properties[function]
        except AttributeError:
            self._memoised_properties = {function: function(self)}
            return self._memoised_properties[function]
        except KeyError:
            self._memoised_properties[function] = function(self)
            return self._memoised_properties[function]
    return property(wrapper)

