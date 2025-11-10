"""
Video Utilities Module

This module provides utility functions for video file management including
file listing, video file indexing operations, and migration utilities
for directory structure updates.
"""

import glob
import logging
import os
import subprocess


def list_local_video_files(rootdir, createMD5=False):
    """
    Creates an index of all the video files in the provided formats.

    Scans the `rootdir` directory and subdirectories for video files with the specified formats.
    Returns the information as a dictionary with filenames as keys and file info as values.

    Args:
        rootdir: Root directory to scan for video files
        createMD5: Ignored (kept for compatibility, hashing no longer used)

    Returns:
        dict: A dictionary with video file names as keys and their info as values.
        Example:
            {
                "video1.h264": {"path": "/path/to/video1.h264"},
                "video2.h264": {"path": "/path/to/video2.h264"}
            }

    Raises:
        IOError: If there is an issue accessing the video files.
    """
    video_formats = ["h264"]
    result = {}

    # Retrieve all video files in the specified formats
    all_video_files = [
        video_file
        for root, dirs, files in os.walk(rootdir)
        for video_file in glob.glob(os.path.join(root, "*.*"))
        if video_file.endswith(tuple(video_formats))
    ]

    for video_file in all_video_files:
        filename = os.path.basename(video_file)
        try:
            result[filename] = {"path": video_file}
        except Exception as e:
            logging.error(f"Failed to process file {video_file}: {str(e)}")
            result[filename] = {}

    return result


def ensure_video_directory_structure(ethoscope_root_dir, videos_dir):
    """
    Ensure videos directory exists, migrating from legacy ethoscope_data/results if needed.
    """

    legacy_results_dir = os.path.join(ethoscope_root_dir, "results")

    # If legacy results directory exists and videos doesn't, move it
    if os.path.exists(legacy_results_dir) and not os.path.exists(videos_dir):
        try:
            subprocess.run(["mv", legacy_results_dir, videos_dir], check=True)
            logging.info(f"Migrated {legacy_results_dir} to {videos_dir}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to move {legacy_results_dir} to {videos_dir}: {e}")

    # Ensure videos directory exists
    if not os.path.exists(videos_dir):
        os.makedirs(videos_dir, exist_ok=True)
        logging.info(f"Created videos directory: {videos_dir}")

    return videos_dir
