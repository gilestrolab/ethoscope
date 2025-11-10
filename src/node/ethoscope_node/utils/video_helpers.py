"""
Video Helper Utilities

This module provides utility functions for video file management specific to
the node package backup operations. These utilities were extracted from the
device package to maintain package independence.

Note: This is a local copy to avoid cross-package dependencies. Originally from
ethoscope.utils.video, duplicated here to keep ethoscope_node independent.
"""

import glob
import logging
import os


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
