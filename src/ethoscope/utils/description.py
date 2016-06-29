__author__ = 'quentin'


class DescribedObject(object):
    r"""
    An object that contains a ``description`` attribute.
    This is used to parse user option for the web interface.
    This way, users can send option to the different objects used.
    ``description`` is a dictionary with the fields "overview" and "arguments".
    "overview" is simply a string. "arguments" is a list of dictionaries. Each has the field:

     * name: The name of the argument as it is in "__init__"
     * description: "A user friendly description of the argument"
     * type: "number", "datetime", "daterange" and "string".
     * min, max and step: only for type "number", defines the accepted limits of the arguments as well as the increment in the user interface
     * default: the default value

    Each argument must match a argument in `__init__`.
    """
    _description = None

    @property
    def description(self):
        return self._description



