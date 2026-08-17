#!/usr/bin/env python3
"""
Unit tests for manual_polygons ROI templates.

Every such template was unusable, including the shipped ``default_full_image``:

* polygons were built as float32, while ``cv2.fillPoly`` downstream requires
  int32, raising ``(-215:Assertion failed) p.checkVector(2, CV_32S) > 0``;
* coordinates normalised to 0..1 - which is how ``default_full_image`` is
  written - were never scaled by the camera, so a "full image" ROI would have
  been one pixel across had it built at all.

Found on hardware, where the failure surfaced as "insufficient targets
detected" and sent us looking at the camera.
"""

import numpy as np
import pytest

from ethoscope.roi_builders.template import ROITemplate, ROITemplateValidationError


class _Camera:
    def __init__(self, width=1280, height=960):
        self.width = width
        self.height = height


def _template(polygon, value=0):
    """A minimal valid manual_polygons template around one polygon."""
    return {
        "template_info": {"name": "test", "version": "1.0"},
        "roi_definition": {
            "type": "manual_polygons",
            "manual_rois": [{"polygon": polygon, "value": value}],
        },
    }


def _rois_for(polygon, camera=None):
    template = ROITemplate(_template(polygon))
    roi_def = template.data["roi_definition"]
    return template._generate_manual_rois(camera or _Camera(), roi_def)


def _points(roi):
    """ROI stores its polygon reshaped to (N, 1, 2); flatten it back."""
    return roi.polygon.reshape(-1, 2)


def test_polygon_points_are_int32():
    """cv2.fillPoly requires CV_32S; float32 made every manual template fail."""
    rois = _rois_for([[0, 0], [100, 0], [100, 100], [0, 100]])

    assert rois[0].polygon.dtype == np.int32


def test_normalised_polygon_is_scaled_to_the_camera():
    """The shipped default_full_image template is written as 0..1."""
    rois = _rois_for([[0, 0], [1, 0], [1, 1], [0, 1]], camera=_Camera(1280, 960))

    xs, ys = _points(rois[0])[:, 0], _points(rois[0])[:, 1]
    # 1.0 maps to the last valid pixel, not one past the edge of the frame.
    assert xs.min() == 0 and xs.max() == 1279
    assert ys.min() == 0 and ys.max() == 959


def test_pixel_polygon_is_left_alone():
    """Coordinates beyond the unit square are already in pixels."""
    rois = _rois_for([[10, 20], [110, 20], [110, 120], [10, 120]])

    xs, ys = _points(rois[0])[:, 0], _points(rois[0])[:, 1]
    assert xs.min() == 10 and xs.max() == 110
    assert ys.min() == 20 and ys.max() == 120


def test_full_image_roi_covers_the_frame():
    """End to end: the default_full_image geometry yields a full-frame ROI."""
    rois = _rois_for([[0, 0], [1, 0], [1, 1], [0, 1]], camera=_Camera(640, 480))

    x, y, w, h = rois[0].rectangle
    assert (x, y) == (0, 0)
    assert (w, h) == (640, 480)


def test_normalised_polygon_without_camera_dimensions_is_refused():
    """Better to fail loudly than to build a one-pixel ROI."""
    with pytest.raises(ROITemplateValidationError, match="no dimensions"):
        _rois_for([[0, 0], [1, 0], [1, 1], [0, 1]], camera=_Camera(0, 0))
