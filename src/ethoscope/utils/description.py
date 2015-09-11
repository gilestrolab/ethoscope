__author__ = 'quentin'


#
#
# class DescribedArgumentBase(object):
#     __name = None
#     __description = None
#     __type = None
#     __range = None
#     __default_value = None
#
#     @property
#     def name(self):
#         if self.__name is None:
#             raise NotImplementedError
#         return self.__name
#
#     @property
#     def description(self):
#         if self.__description is None:
#             raise NotImplementedError
#         return self.__description
#
#     @property
#     def default_value(self):
#         if self.__default_value is None:
#             raise NotImplementedError
#         return self.__default_value
#
#     @property
#     def type(self):
#         if self.__type is None:
#             raise NotImplementedError
#         return self.__type
#
#     @property
#     def range(self):
#         return self.__range
#
#
# class DescribedNumericalArgument(DescribedArgumentBase):
#     @property
#     def range(self):
#         if self.__range is None:
#             raise NotImplementedError
#         return self.__range
#
#
# class DescribedStringArgument(DescribedArgumentBase):
#     __type = "str"
#
# class DescribedIntArgument(DescribedNumericalArgument):
#     __type = "int"
#
# class DescribedFloatArgument(DescribedNumericalArgument):
#     __type = "float"
#

class DescribedObject(object):
    _description = None

    @property
    def description(self):
        return self._description



