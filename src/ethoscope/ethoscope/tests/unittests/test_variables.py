"""
Unit tests for core variable types.

Tests variable classes used for type-safe storage of tracking data.
"""

import unittest
from unittest.mock import Mock

from ethoscope.core.variables import (
    BaseIntVariable,
    BaseRelativeVariable,
    HeightVariable,
    IsInferredVariable,
    Label,
    PhiVariable,
    WidthVariable,
    XPosVariable,
    YPosVariable,
    mLogLik,
)


class TestVariableTypes(unittest.TestCase):
    """Test suite for variable type classes."""

    def test_base_int_variable_requires_functional_type(self):
        """Test that BaseIntVariable requires functional_type to be defined."""
        with self.assertRaises(NotImplementedError):

            class BadVariable(BaseIntVariable):
                sql_data_type = "INT"
                header_name = "test"
                # Missing functional_type

            BadVariable(10)

    def test_base_int_variable_requires_sql_type(self):
        """Test that BaseIntVariable requires sql_data_type to be defined."""
        with self.assertRaises(NotImplementedError):

            class BadVariable(BaseIntVariable):
                functional_type = "test"
                header_name = "test"
                sql_data_type = None  # Explicitly set to None

            BadVariable(10)

    def test_base_int_variable_requires_header_name(self):
        """Test that BaseIntVariable requires header_name to be defined."""
        with self.assertRaises(NotImplementedError):

            class BadVariable(BaseIntVariable):
                functional_type = "test"
                sql_data_type = "INT"
                # Missing header_name

            BadVariable(10)

    def test_is_inferred_variable_creation(self):
        """Test IsInferredVariable can be created with valid values."""
        var = IsInferredVariable(1)
        self.assertEqual(int(var), 1)
        self.assertEqual(var.header_name, "is_inferred")
        self.assertEqual(var.functional_type, "bool")

    def test_phi_variable_creation(self):
        """Test PhiVariable can be created."""
        var = PhiVariable(180)
        self.assertEqual(int(var), 180)
        self.assertEqual(var.header_name, "phi")
        self.assertEqual(var.functional_type, "angle")

    def test_label_variable_creation(self):
        """Test Label variable can be created."""
        var = Label(5)
        self.assertEqual(int(var), 5)
        self.assertEqual(var.functional_type, "label")

    def test_width_height_variables(self):
        """Test width and height variables."""
        width = WidthVariable(50)
        height = HeightVariable(30)

        self.assertEqual(int(width), 50)
        self.assertEqual(int(height), 30)
        self.assertEqual(width.header_name, "w")
        self.assertEqual(height.header_name, "h")
        self.assertEqual(width.functional_type, "distance")

    def test_mloglik_variable(self):
        """Test mLogLik variable for probability storage."""
        var = mLogLik(1000)
        self.assertEqual(int(var), 1000)
        self.assertEqual(var.functional_type, "proba")


class TestRelativeVariables(unittest.TestCase):
    """Test suite for relative position variables."""

    def test_x_pos_variable_to_absolute(self):
        """Test XPosVariable converts to absolute coordinates (lines 140-144)."""
        # Create mock ROI with offset
        mock_roi = Mock()
        mock_roi.offset = (100, 50)  # x_offset=100, y_offset=50

        # Create relative X position
        x_rel = XPosVariable(25)

        # Convert to absolute
        x_abs = x_rel.to_absolute(mock_roi)

        # Should be 25 + 100 = 125
        self.assertIsInstance(x_abs, XPosVariable)
        self.assertEqual(int(x_abs), 125)

    def test_y_pos_variable_to_absolute(self):
        """Test YPosVariable converts to absolute coordinates (lines 155-158)."""
        # Create mock ROI with offset
        mock_roi = Mock()
        mock_roi.offset = (100, 50)  # x_offset=100, y_offset=50

        # Create relative Y position
        y_rel = YPosVariable(30)

        # Convert to absolute
        y_abs = y_rel.to_absolute(mock_roi)

        # Should be 30 + 50 = 80
        self.assertIsInstance(y_abs, YPosVariable)
        self.assertEqual(int(y_abs), 80)

    def test_to_absolute_calls_get_absolute_value(self):
        """Test to_absolute method calls _get_absolute_value (line 124)."""
        mock_roi = Mock()
        mock_roi.offset = (10, 20)

        x_var = XPosVariable(5)
        result = x_var.to_absolute(mock_roi)

        # Result should be from _get_absolute_value
        self.assertEqual(int(result), 15)  # 5 + 10

    def test_base_relative_variable_not_implemented(self):
        """Test BaseRelativeVariable requires _get_absolute_value implementation."""

        class IncompleteVariable(BaseRelativeVariable):
            header_name = "test"
            # Missing _get_absolute_value implementation

        var = IncompleteVariable(10)
        mock_roi = Mock()

        with self.assertRaises(NotImplementedError):
            var.to_absolute(mock_roi)


if __name__ == "__main__":
    unittest.main()
