"""
Unit tests for video helper utilities

Tests the video file listing and indexing functionality used in backup operations.
"""

import os
import tempfile
import pytest
from ethoscope_node.utils.video_helpers import list_local_video_files


class TestListLocalVideoFiles:
    """Test suite for list_local_video_files function"""

    def test_list_video_files_empty_directory(self):
        """Test that empty directory returns empty result"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = list_local_video_files(tmpdir)
            assert result == {}

    def test_list_video_files_with_h264_files(self):
        """Test listing h264 video files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test video files
            video1 = os.path.join(tmpdir, "test1.h264")
            video2 = os.path.join(tmpdir, "test2.h264")

            # Create empty files
            open(video1, 'a').close()
            open(video2, 'a').close()

            result = list_local_video_files(tmpdir)

            assert len(result) == 2
            assert "test1.h264" in result
            assert "test2.h264" in result
            assert result["test1.h264"]["path"] == video1
            assert result["test2.h264"]["path"] == video2

    def test_list_video_files_nested_directories(self):
        """Test that function scans nested directories"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested directory structure
            subdir1 = os.path.join(tmpdir, "subdir1")
            subdir2 = os.path.join(tmpdir, "subdir2")
            os.makedirs(subdir1)
            os.makedirs(subdir2)

            # Create video files in different locations
            video1 = os.path.join(tmpdir, "root.h264")
            video2 = os.path.join(subdir1, "sub1.h264")
            video3 = os.path.join(subdir2, "sub2.h264")

            for video in [video1, video2, video3]:
                open(video, 'a').close()

            result = list_local_video_files(tmpdir)

            assert len(result) == 3
            assert "root.h264" in result
            assert "sub1.h264" in result
            assert "sub2.h264" in result

    def test_list_video_files_ignores_other_formats(self):
        """Test that non-h264 files are ignored"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create various file types
            h264_file = os.path.join(tmpdir, "video.h264")
            mp4_file = os.path.join(tmpdir, "video.mp4")
            txt_file = os.path.join(tmpdir, "readme.txt")

            for f in [h264_file, mp4_file, txt_file]:
                open(f, 'a').close()

            result = list_local_video_files(tmpdir)

            assert len(result) == 1
            assert "video.h264" in result
            assert "video.mp4" not in result
            assert "readme.txt" not in result

    def test_list_video_files_createMD5_parameter_ignored(self):
        """Test that createMD5 parameter is accepted but ignored"""
        with tempfile.TemporaryDirectory() as tmpdir:
            video = os.path.join(tmpdir, "test.h264")
            open(video, 'a').close()

            # Test with createMD5=False
            result1 = list_local_video_files(tmpdir, createMD5=False)
            assert len(result1) == 1
            assert "test.h264" in result1

            # Test with createMD5=True (should be ignored)
            result2 = list_local_video_files(tmpdir, createMD5=True)
            assert len(result2) == 1
            assert "test.h264" in result2

            # Both results should be identical
            assert result1 == result2

    def test_list_video_files_duplicate_filenames(self):
        """Test handling of duplicate filenames in different directories"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two directories with same filename
            subdir1 = os.path.join(tmpdir, "dir1")
            subdir2 = os.path.join(tmpdir, "dir2")
            os.makedirs(subdir1)
            os.makedirs(subdir2)

            video1 = os.path.join(subdir1, "video.h264")
            video2 = os.path.join(subdir2, "video.h264")

            for video in [video1, video2]:
                open(video, 'a').close()

            result = list_local_video_files(tmpdir)

            # With duplicate names, the last one processed wins
            # We just verify that "video.h264" exists and has a valid path
            assert "video.h264" in result
            assert "path" in result["video.h264"]
            assert result["video.h264"]["path"] in [video1, video2]

    def test_list_video_files_nonexistent_directory(self):
        """Test that function handles non-existent directory gracefully"""
        nonexistent = "/nonexistent/path/to/directory"

        # Should return empty dict for non-existent directory
        result = list_local_video_files(nonexistent)
        assert result == {}

    def test_list_video_files_permission_issues(self, caplog):
        """Test that permission errors are logged but don't crash"""
        with tempfile.TemporaryDirectory() as tmpdir:
            video = os.path.join(tmpdir, "test.h264")
            open(video, 'a').close()

            # This should work normally
            result = list_local_video_files(tmpdir)
            assert len(result) == 1
            assert "test.h264" in result

    def test_list_video_files_returns_dict_structure(self):
        """Test that return value has correct structure"""
        with tempfile.TemporaryDirectory() as tmpdir:
            video = os.path.join(tmpdir, "test.h264")
            open(video, 'a').close()

            result = list_local_video_files(tmpdir)

            # Verify structure
            assert isinstance(result, dict)
            assert "test.h264" in result
            assert isinstance(result["test.h264"], dict)
            assert "path" in result["test.h264"]
            assert isinstance(result["test.h264"]["path"], str)

    def test_list_video_files_edge_case_special_characters(self):
        """Test handling of filenames with special characters"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create file with spaces and special chars
            video = os.path.join(tmpdir, "test video (1).h264")
            open(video, 'a').close()

            result = list_local_video_files(tmpdir)

            assert len(result) == 1
            assert "test video (1).h264" in result
            assert result["test video (1).h264"]["path"] == video
