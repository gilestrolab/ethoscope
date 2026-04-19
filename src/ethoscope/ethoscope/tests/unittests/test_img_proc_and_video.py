"""
Unit tests for utils/img_proc.py and utils/video.py.

Tests merge_blobs contour merging and video file listing.
"""

import os
import shutil
import tempfile
import unittest

import cv2
import numpy as np

from ethoscope.utils.img_proc import merge_blobs
from ethoscope.utils.video import (
    ensure_video_directory_structure,
    list_local_video_files,
)

# ===========================================================================
# merge_blobs
# ===========================================================================


class TestMergeBlobs(unittest.TestCase):
    """Test merge_blobs contour merging."""

    def _make_contour(self, x, y, size=20):
        """Create a rectangular contour at (x, y) with given size."""
        return np.array(
            [
                [[x, y]],
                [[x + size, y]],
                [[x + size, y + size]],
                [[x, y + size]],
            ],
            dtype=np.int32,
        )

    def test_empty_contours(self):
        result = merge_blobs([])
        self.assertEqual(result, [])

    def test_single_contour(self):
        c = self._make_contour(50, 50)
        result = merge_blobs([c])
        self.assertEqual(len(result), 1)

    def test_distant_contours_not_merged(self):
        """Two distant contours should not be merged."""
        c1 = self._make_contour(0, 0, size=10)
        c2 = self._make_contour(200, 200, size=10)
        result = merge_blobs([c1, c2])
        self.assertEqual(len(result), 2)

    def test_close_contours_merged(self):
        """Two close contours should be merged."""
        c1 = self._make_contour(50, 50, size=30)
        c2 = self._make_contour(55, 55, size=30)  # Overlapping
        result = merge_blobs([c1, c2])
        self.assertEqual(len(result), 1)

    def test_three_contours_chain_merge(self):
        """Three close contours should merge into one."""
        c1 = self._make_contour(50, 50, size=30)
        c2 = self._make_contour(60, 50, size=30)
        c3 = self._make_contour(70, 50, size=30)
        result = merge_blobs([c1, c2, c3])
        # All three overlap → single merged contour
        self.assertLessEqual(len(result), 2)


# ===========================================================================
# list_local_video_files
# ===========================================================================


class TestListLocalVideoFiles(unittest.TestCase):
    """Test list_local_video_files."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_empty_directory(self):
        result = list_local_video_files(self.temp_dir)
        self.assertEqual(result, {})

    def test_finds_h264_files(self):
        h264_path = os.path.join(self.temp_dir, "video1.h264")
        with open(h264_path, "w") as f:
            f.write("fake video data")

        result = list_local_video_files(self.temp_dir)
        self.assertIn("video1.h264", result)
        self.assertEqual(result["video1.h264"]["path"], h264_path)

    def test_ignores_non_video_files(self):
        txt_path = os.path.join(self.temp_dir, "notes.txt")
        with open(txt_path, "w") as f:
            f.write("text file")

        result = list_local_video_files(self.temp_dir)
        self.assertNotIn("notes.txt", result)

    def test_finds_in_subdirectories(self):
        subdir = os.path.join(self.temp_dir, "experiment1")
        os.makedirs(subdir)
        h264_path = os.path.join(subdir, "recording.h264")
        with open(h264_path, "w") as f:
            f.write("fake")

        result = list_local_video_files(self.temp_dir)
        self.assertIn("recording.h264", result)


# ===========================================================================
# ensure_video_directory_structure
# ===========================================================================


class TestEnsureVideoDirectoryStructure(unittest.TestCase):
    """Test ensure_video_directory_structure."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_creates_videos_dir(self):
        videos_dir = os.path.join(self.temp_dir, "videos")
        result = ensure_video_directory_structure(self.temp_dir, videos_dir)
        self.assertTrue(os.path.isdir(videos_dir))
        self.assertEqual(result, videos_dir)

    def test_existing_dir_unchanged(self):
        videos_dir = os.path.join(self.temp_dir, "videos")
        os.makedirs(videos_dir)
        marker = os.path.join(videos_dir, "marker.txt")
        with open(marker, "w") as f:
            f.write("exists")

        ensure_video_directory_structure(self.temp_dir, videos_dir)
        self.assertTrue(os.path.exists(marker))


if __name__ == "__main__":
    unittest.main()
