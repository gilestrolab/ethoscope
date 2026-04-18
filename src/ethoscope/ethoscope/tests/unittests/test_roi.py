"""
Unit tests for core/roi.py.

Tests ROI class including initialization, properties, image cropping,
feature extraction, and boundary handling.
"""

import unittest

import cv2
import numpy as np

from ethoscope.core.roi import ROI
from ethoscope.utils.debug import EthoscopeException


class TestROIInit(unittest.TestCase):
    """Test ROI initialization with various polygon formats."""

    def test_init_with_tuple_polygon(self):
        """Test ROI creation with tuple polygon."""
        roi = ROI(polygon=((0, 0), (100, 0), (100, 50), (0, 50)), idx=1)
        self.assertEqual(roi.idx, 1)
        self.assertEqual(roi._polygon.shape[1], 1)  # reshaped to (N, 1, 2)
        self.assertEqual(roi._polygon.shape[2], 2)

    def test_init_with_numpy_polygon(self):
        """Test ROI creation with numpy array polygon."""
        polygon = np.array([[10, 10], [200, 10], [200, 100], [10, 100]])
        roi = ROI(polygon=polygon, idx=5)
        self.assertEqual(roi.idx, 5)

    def test_init_with_3d_polygon(self):
        """Test ROI creation with already-reshaped 3D polygon."""
        polygon = np.array([[[0, 0]], [[100, 0]], [[100, 80]], [[0, 80]]])
        roi = ROI(polygon=polygon, idx=2)
        self.assertEqual(roi._polygon.shape, (4, 1, 2))

    def test_value_defaults_to_idx(self):
        """Test that value defaults to idx when not provided."""
        roi = ROI(polygon=((0, 0), (50, 0), (50, 50), (0, 50)), idx=7)
        self.assertEqual(roi.value, 7)

    def test_value_set_explicitly(self):
        """Test explicit value assignment."""
        roi = ROI(polygon=((0, 0), (50, 0), (50, 50), (0, 50)), idx=3, value=42)
        self.assertEqual(roi.value, 42)


class TestROIProperties(unittest.TestCase):
    """Test ROI property accessors."""

    def setUp(self):
        """Create a standard ROI for property tests."""
        self.roi = ROI(
            polygon=((10, 20), (110, 20), (110, 70), (10, 70)), idx=1, value=5
        )

    def test_idx(self):
        self.assertEqual(self.roi.idx, 1)

    def test_mask_shape_and_dtype(self):
        """Test mask is correct shape and dtype."""
        x, y, w, h = self.roi.rectangle
        self.assertEqual(self.roi.mask.shape, (h, w))
        self.assertEqual(self.roi.mask.dtype, np.uint8)

    def test_mask_has_nonzero_values(self):
        """Test mask contains filled region (255 values)."""
        self.assertGreater(np.sum(self.roi.mask > 0), 0)

    def test_offset(self):
        """Test offset returns top-left corner."""
        x, y = self.roi.offset
        self.assertEqual(x, 10)
        self.assertEqual(y, 20)

    def test_polygon_shape(self):
        """Test polygon is 3D array."""
        self.assertEqual(len(self.roi.polygon.shape), 3)

    def test_longest_axis(self):
        """Test longest_axis returns max of w, h."""
        x, y, w, h = self.roi.rectangle
        self.assertEqual(self.roi.longest_axis, float(max(w, h)))

    def test_rectangle(self):
        """Test rectangle returns (x, y, w, h)."""
        x, y, w, h = self.roi.rectangle
        self.assertEqual(x, 10)
        self.assertEqual(y, 20)
        # OpenCV boundingRect includes endpoint pixels, so w/h may be +1
        self.assertGreaterEqual(w, 100)
        self.assertGreaterEqual(h, 50)

    def test_value(self):
        self.assertEqual(self.roi.value, 5)

    def test_regions(self):
        """Test regions property is accessible."""
        self.assertIsNotNone(self.roi.regions)

    def test_bounding_rect_raises(self):
        """Test bounding_rect raises NotImplementedError."""
        with self.assertRaises(NotImplementedError):
            self.roi.bounding_rect()


class TestROISetValue(unittest.TestCase):
    """Test ROI value modification."""

    def test_set_value(self):
        roi = ROI(polygon=((0, 0), (50, 0), (50, 50), (0, 50)), idx=1)
        roi.set_value(99)
        self.assertEqual(roi.value, 99)


class TestROIGetFeatureDict(unittest.TestCase):
    """Test ROI feature dictionary generation."""

    def test_feature_dict_keys(self):
        roi = ROI(polygon=((5, 10), (105, 10), (105, 60), (5, 60)), idx=3, value=7)
        fd = roi.get_feature_dict()
        self.assertSetEqual(set(fd.keys()), {"x", "y", "w", "h", "value", "idx"})

    def test_feature_dict_values(self):
        roi = ROI(polygon=((5, 10), (105, 10), (105, 60), (5, 60)), idx=3, value=7)
        fd = roi.get_feature_dict()
        self.assertEqual(fd["x"], 5)
        self.assertEqual(fd["y"], 10)
        # OpenCV boundingRect may include endpoint pixels (+1)
        self.assertGreaterEqual(fd["w"], 100)
        self.assertGreaterEqual(fd["h"], 50)
        self.assertEqual(fd["idx"], 3)
        self.assertEqual(fd["value"], 7)


class TestROIApply(unittest.TestCase):
    """Test ROI image cropping."""

    def setUp(self):
        """Create test image and ROI."""
        self.img = np.zeros((200, 300, 3), dtype=np.uint8)
        self.img[50:100, 50:150] = 128  # Gray region
        self.roi = ROI(polygon=((50, 50), (150, 50), (150, 100), (50, 100)), idx=1)

    def test_apply_returns_cropped_image(self):
        """Test apply returns correctly sized crop."""
        out, mask = self.roi.apply(self.img)
        x, y, w, h = self.roi.rectangle
        self.assertEqual(out.shape[0], h)
        self.assertEqual(out.shape[1], w)

    def test_apply_returns_mask(self):
        """Test apply returns mask matching crop dimensions."""
        out, mask = self.roi.apply(self.img)
        self.assertEqual(mask.shape, out.shape[:2])

    def test_apply_single_channel_image(self):
        """Test apply works with grayscale images."""
        gray_img = np.zeros((200, 300), dtype=np.uint8)
        out, mask = self.roi.apply(gray_img)
        self.assertEqual(len(out.shape), 2)
        self.assertEqual(mask.shape, out.shape)

    def test_apply_roi_at_origin(self):
        """Test apply with ROI at image origin."""
        roi = ROI(polygon=((0, 0), (50, 0), (50, 50), (0, 50)), idx=1)
        img = np.ones((100, 100, 3), dtype=np.uint8) * 200
        out, mask = roi.apply(img)
        # OpenCV boundingRect may add +1 for endpoint pixels
        x, y, w, h = roi.rectangle
        self.assertEqual(out.shape[:2], (h, w))

    def test_apply_roi_at_edge(self):
        """Test apply with ROI at image edge."""
        roi = ROI(polygon=((250, 150), (300, 150), (300, 200), (250, 200)), idx=1)
        img = np.ones((200, 300, 3), dtype=np.uint8)
        out, mask = roi.apply(img)
        self.assertGreater(out.shape[0], 0)
        self.assertGreater(out.shape[1], 0)

    def test_apply_preserves_pixel_values(self):
        """Test cropped image contains correct pixel values."""
        out, mask = self.roi.apply(self.img)
        # The center of the crop should have value 128
        self.assertTrue(np.any(out == 128))


if __name__ == "__main__":
    unittest.main()
