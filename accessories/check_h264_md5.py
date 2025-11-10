#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  check_h264_md5.py
#
#  Copyright 2020 Giorgio Gilestro <giorgio@gilest.ro>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#

import os
import hashlib
import argparse

def calculate_md5(file_path):
    """Calculate the MD5 checksum of a file."""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def verify_md5(md5_file_path, replace):
    """Verify the MD5 checksum against the calculated MD5 for the corresponding file."""
    # Read the expected MD5 value from the .md5 file
    with open(md5_file_path, 'r') as md5_file:
        expected_md5 = md5_file.read().strip().split()[0]  # Get the hash value from the file

    # Construct the corresponding .h264 file path
    h264_file_path = md5_file_path.replace('.md5', '')

    # Calculate MD5 for the .h264 file
    calculated_md5 = calculate_md5(h264_file_path)

    # Compare the hashes
    if expected_md5 == calculated_md5:
        print(f"MD5 match for: {h264_file_path}")
    else:
        print(f"MD5 mismatch for: {h264_file_path}")
        print(f"Expected: {expected_md5}, Calculated: {calculated_md5}")

        if replace:
            print("Removing the old .md5 file and creating a new one...")
            # Remove the old .md5 file
            os.remove(md5_file_path)
            # Create a new .md5 file with the correct value
            with open(md5_file_path, 'w') as md5_file:
                md5_file.write(f"{calculated_md5}")
            print(f"Recreated {md5_file_path} with the correct MD5 value: {calculated_md5}")

def main(directory, replace):
    # Find all .md5 files in the specified directory and subdirectories
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.md5'):
                md5_file_path = os.path.join(root, file)
                verify_md5(md5_file_path, replace)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Verify MD5 checksums for video files.')
    parser.add_argument('directory', type=str, help='The directory to crawl for .md5 files.')
    parser.add_argument('--replace', action='store_true', help='Remove the .md5 file on mismatch and replace it with the correct value.')

    args = parser.parse_args()

    main(args.directory, args.replace)
