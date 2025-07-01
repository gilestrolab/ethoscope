"""
Video Utilities Module

This module provides utility functions for video file management including
file listing, MD5 hash generation, video file indexing operations, and
migration utilities for directory structure updates.
"""

import os
import glob
import logging
import time
import hashlib
import shutil
import subprocess

def list_local_video_files(rootdir, createMD5=True):
    """
    Creates an index of all the video files in the provided formats and their associated MD5 checksum values.

    Scans the `rootdir` directory and subdirectories for video files with the specified formats,
    and retrieves the corresponding MD5 checksum values from `.md5` files located in the same directory
    as each video file. Returns the information as a JSON dictionary. 

    With createMD5 set to True (Default) it will compute the hash and save a new file when
    an associated `.md5` is not found on the first place.

    Returns:
        dict: A dictionary with video file paths as keys and their associated MD5 checksum values as values.
        Example:
            {
                "/path/to/video1.mp4": "e99a18c428cb38d5f260853678922e03",
                "/path/to/video2.avi": "098f6bcd4621d373cade4e832627b4f6"
            }

    Raises:
        KeyError: If a required property such as `_ETHOSCOPE_DIR` is missing.
        IOError: If there is an issue reading the video or `.md5` files.
    """
    #video_formats = ['h264', 'avi', 'mp4']
    video_formats = ['h264']
    result = {}

    # Retrieve all video files in the specified formats
    all_video_files = [
        video_file
        for root, dirs, files in os.walk(rootdir)
        for video_file in glob.glob(os.path.join(root, '*.*'))
        if video_file.endswith(tuple(video_formats))
    ]

    for video_file in all_video_files:
        # Generate the corresponding `.md5` filename
        filename = os.path.basename(video_file)
        md5_file = f"{video_file}.md5"
        try:
            # Read the MD5 checksum from the `.md5` file
            if os.path.exists(md5_file):
                with open(md5_file, "r") as f:
                    md5sum_value = f.read().strip()
            else:
                if createMD5:
                    logging.info (f"MD5 file {md5_file} not found. Calculating ex novo for {video_file}")                
                    md5sum_value = save_hash_info_file (video_file)
                else:
                    md5sum_value = ""

            result[filename] = {'path' : video_file, 'hash' : md5sum_value}

        except Exception as e:
            logging.error(f"Failed to process file {video_file} or its MD5 checksum: {str(e)}")
            result[filename] = {}

    return result


def save_hash_info_file(filename_to_hash, writefile=True):
    """
    Generate an MD5 hash for the specified file and save it to a new file with a ".md5" extension.

    This function computes the MD5 hash of the given file (e.g., a video file) and writes the
    computed hash string to a text file. The generated hash file will have the same name
    as the input file, with a ".md5" extension appended.

    Parameters:
    -----------
    filename_to_hash : str
        The path to the file for which the MD5 hash should be calculated and saved.

    Returns:
    --------
    str
        The computed MD5 hash of the input file.

    Internal Functions:
    -------------------
    compute_md5(file_path):
        Computes the MD5 hash of a given file. The file is read in chunks to conserve memory
        when processing large files.

    Example:
    --------
    If `filename_to_hash` is "example_video.mp4", this function will:
    1. Compute the MD5 hash of "example_video.mp4".
    2. Create a new file named "example_video.mp4.md5".
    3. Write the computed hash to "example_video.mp4.md5".

    Usage:
    ------
    >>> save_hash_info_file("example_video.mp4")
    'd41d8cd98f00b204e9800998ecf8427e'  # Example hash value (real values will differ)
    """
    def compute_md5(file_path):
        """
        Compute the MD5 hash of the provided file.

        Parameters:
        -----------
        file_path : str
            The path to the file for which the MD5 hash will be calculated.

        Returns:
        --------
        str
            The MD5 hash of the input file in hexadecimal format.
        """
        md5_hash = hashlib.md5()
        with open(file_path, "rb") as file:
            # Read the file in 4 KB chunks to avoid high memory usage
            for chunk in iter(lambda: file.read(4096), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()


    # Wait until the file is fully written
    stable = False
    previous_size = os.path.getsize(filename_to_hash)
    time.sleep(0.5)
    while not stable:
        time.sleep(0.5)
        current_size = os.path.getsize(filename_to_hash)
        if current_size == previous_size:
            stable = True  # The file size has stabilized, we can proceed with the hash
        else:
            previous_size = current_size  # Update size for the next check

    file_hash = compute_md5(filename_to_hash)
    if writefile:
        hash_file = filename_to_hash + ".md5"
        with open(hash_file, "w") as file:
            file.write(file_hash)

    return file_hash


def ensure_video_directory_structure(ethoscope_root_dir, videos_dir):
    """
    Ensure videos directory exists, migrating from legacy ethoscope_data/results if needed.
    """
  
    legacy_results_dir = os.path.join(ethoscope_root_dir, 'results')
    
    # If legacy results directory exists and videos doesn't, move it
    if os.path.exists(legacy_results_dir) and not os.path.exists(videos_dir):
        try:
            subprocess.run(['mv', legacy_results_dir, videos_dir], check=True)
            logging.info(f"Migrated {legacy_results_dir} to {videos_dir}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to move {legacy_results_dir} to {videos_dir}: {e}")
    
    # Ensure videos directory exists
    if not os.path.exists(videos_dir):
        os.makedirs(videos_dir, exist_ok=True)
        logging.info(f"Created videos directory: {videos_dir}")
    
    return videos_dir