__author__ = "quentin"

import unittest

from ethoscope.utils.description import DescribedObject


class TestExple(unittest.TestCase):

    def test_exple(self):

        ans = 1
        ref = 1
        self.assertEqual(ans, ref)


class TestDescribedObject(unittest.TestCase):
    """Test suite for DescribedObject base class."""

    def test_description_property_default(self):
        """Test description property returns None by default."""
        obj = DescribedObject()
        self.assertIsNone(obj.description)

    def test_description_property_with_value(self):
        """Test description property returns set value."""

        class TestObject(DescribedObject):
            _description = {"overview": "Test object", "arguments": []}

        obj = TestObject()
        self.assertIsNotNone(obj.description)
        self.assertIn("overview", obj.description)
        self.assertEqual(obj.description["overview"], "Test object")
