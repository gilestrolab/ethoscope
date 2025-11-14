"""
Unit tests for debug utilities.

Tests custom exception and debug display functions.
"""

import unittest
from unittest.mock import patch

import numpy as np

from ethoscope.utils.debug import EthoscopeException, show


class TestEthoscopeException(unittest.TestCase):
    """Test suite for EthoscopeException."""

    def test_exception_with_message_only(self):
        """Test exception with message but no image."""
        exc = EthoscopeException("Test error message")
        self.assertEqual(exc.value, "Test error message")
        self.assertIsNone(exc.img)

    def test_exception_with_image(self):
        """Test exception with numpy array image (lines 18-22)."""
        test_img = np.zeros((100, 100), dtype=np.uint8)
        exc = EthoscopeException("Test error", img=test_img)

        self.assertEqual(exc.value, "Test error")
        self.assertIsNotNone(exc.img)
        self.assertIsInstance(exc.img, np.ndarray)
        # Should be a copy, not the same object
        self.assertIsNot(exc.img, test_img)
        np.testing.assert_array_equal(exc.img, test_img)

    def test_exception_with_non_array_img(self):
        """Test exception with non-array img parameter (line 22)."""
        exc = EthoscopeException("Test error", img="not an array")
        self.assertEqual(exc.value, "Test error")
        self.assertIsNone(exc.img)

    def test_exception_str_representation(self):
        """Test __str__ method returns repr of value (line 25)."""
        exc = EthoscopeException("Error message")
        str_repr = str(exc)
        # __str__ returns repr(self.value)
        self.assertEqual(str_repr, repr("Error message"))
        self.assertEqual(str_repr, "'Error message'")

    def test_exception_can_be_raised(self):
        """Test exception can be raised and caught."""
        with self.assertRaises(EthoscopeException) as context:
            raise EthoscopeException("Test exception")

        self.assertEqual(context.exception.value, "Test exception")


class TestShowFunction(unittest.TestCase):
    """Test suite for show debug function."""

    @patch("cv2.waitKey")
    @patch("cv2.imshow")
    def test_show_with_default_wait(self, mock_imshow, mock_waitKey):
        """Test show function with default wait time (lines 37-38)."""
        test_img = np.zeros((100, 100), dtype=np.uint8)

        show(test_img)

        # Should call imshow with "debug" window and image
        mock_imshow.assert_called_once_with("debug", test_img)
        # Should call waitKey with default -1 (wait indefinitely)
        mock_waitKey.assert_called_once_with(-1)

    @patch("cv2.waitKey")
    @patch("cv2.imshow")
    def test_show_with_custom_wait(self, mock_imshow, mock_waitKey):
        """Test show function with custom wait time."""
        test_img = np.zeros((50, 50), dtype=np.uint8)

        show(test_img, t=1000)

        mock_imshow.assert_called_once_with("debug", test_img)
        mock_waitKey.assert_called_once_with(1000)

    @patch("cv2.waitKey")
    @patch("cv2.imshow")
    def test_show_with_zero_wait(self, mock_imshow, mock_waitKey):
        """Test show function with zero wait time (immediate)."""
        test_img = np.ones((10, 10), dtype=np.uint8)

        show(test_img, t=0)

        mock_imshow.assert_called_once_with("debug", test_img)
        mock_waitKey.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
