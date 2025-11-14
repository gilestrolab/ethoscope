"""
Unit tests for DataPoint container class.

Tests the DataPoint OrderedDict-based container for tracking variables.
"""

import unittest

from ethoscope.core.data_point import DataPoint
from ethoscope.core.variables import (
    HeightVariable,
    WidthVariable,
    XPosVariable,
    YPosVariable,
)


class TestDataPoint(unittest.TestCase):
    """Test suite for DataPoint class."""

    def test_data_point_creation_with_variables(self):
        """Test DataPoint creation with list of variables (lines 28-30)."""
        x = XPosVariable(100)
        y = YPosVariable(200)
        h = HeightVariable(50)

        # Create DataPoint with list of variables
        data = DataPoint([x, y, h])

        # Should be accessible by header name
        self.assertEqual(data["x"], x)
        self.assertEqual(data["y"], y)
        self.assertEqual(data["h"], h)

        # Should have correct number of items
        self.assertEqual(len(data), 3)

    def test_data_point_empty_initialization(self):
        """Test DataPoint can be created with empty list."""
        data = DataPoint([])
        self.assertEqual(len(data), 0)

    def test_data_point_preserves_order(self):
        """Test DataPoint preserves insertion order."""
        x = XPosVariable(10)
        y = YPosVariable(20)
        w = WidthVariable(5)
        h = HeightVariable(3)

        data = DataPoint([x, y, w, h])

        # OrderedDict should preserve order
        keys = list(data.keys())
        self.assertEqual(keys, ["x", "y", "w", "h"])

    def test_data_point_copy(self):
        """Test DataPoint deep copy method (line 40)."""
        x = XPosVariable(100)
        y = YPosVariable(200)

        original = DataPoint([x, y])
        copied = original.copy()

        # Should be equal but not the same object
        self.assertEqual(copied["x"], original["x"])
        self.assertEqual(copied["y"], original["y"])
        self.assertIsNot(copied, original)

        # Modifying copy should not affect original
        copied["x"] = XPosVariable(999)
        self.assertEqual(int(original["x"]), 100)
        self.assertEqual(int(copied["x"]), 999)

    def test_data_point_append(self):
        """Test DataPoint append method (line 50)."""
        x = XPosVariable(100)
        y = YPosVariable(200)

        data = DataPoint([x, y])

        # Append new variable
        h = HeightVariable(50)
        data.append(h)

        # Should be accessible
        self.assertEqual(data["h"], h)
        self.assertEqual(len(data), 3)

    def test_data_point_append_preserves_order(self):
        """Test append maintains order."""
        data = DataPoint([])

        x = XPosVariable(10)
        y = YPosVariable(20)
        w = WidthVariable(5)

        data.append(x)
        data.append(y)
        data.append(w)

        keys = list(data.keys())
        self.assertEqual(keys, ["x", "y", "w"])

    def test_data_point_append_overwrites_existing(self):
        """Test append overwrites existing variable with same header."""
        x1 = XPosVariable(100)
        data = DataPoint([x1])

        # Append another x variable
        x2 = XPosVariable(200)
        data.append(x2)

        # Should have only one x, with the new value
        self.assertEqual(len(data), 1)
        self.assertEqual(int(data["x"]), 200)


if __name__ == "__main__":
    unittest.main()
