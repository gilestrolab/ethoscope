#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  h264_to_mp4.py
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
#  


import os
import re
import subprocess
from glob import glob
from optparse import OptionParser

def get_video_fps(video_file, user_fps=None):
    """
    Returns the frame rate of the video using ffprobe, or a user-defined FPS.
    """
    if user_fps is not None:
        print(f"Using user-defined FPS: {user_fps}")
        return float(user_fps)
    
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0', 
             '-show_entries', 'stream=avg_frame_rate', '-of', 
             'default=noprint_wrappers=1:nokey=1', video_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        r_frame_rate = result.stdout.decode('utf-8').strip()
        if '/' in r_frame_rate:
            num, den = map(int, r_frame_rate.split('/'))
            fps = num / den
        else:
            fps = float(r_frame_rate)

        print(f"Auto-detected FPS for {video_file}: {fps}")

        # Check if the FPS is within a reasonable range
        if not (1 <= fps <= 120):
            raise ValueError(f"Auto-detected FPS {fps} is out of acceptable range (1-120)")

        return fps
    except Exception as e:
        print(f"Error getting FPS: {e}")
        return None

def process_video(folder, extension="h264", user_fps=None):
    """
    Process video in folder with detailed status updates and a progress bar.
    """
    os.chdir(folder)
    print(f"Processing folder: {folder}")
    video_files = glob(f"*.{extension}")
    if not video_files:
        print(f"No .{extension} files found in the folder.")
        return
    
    # Sort files based on the last 5 digits in the filename
    video_files.sort(key=lambda f: int(f.split('_')[-1].split('.')[0]))
    print(f"Number of .{extension} files: {len(video_files)}")
    
    # Get the first video file to process and create the output filename
    video_file = video_files[0]
    prefix = os.path.splitext(video_file)[0]
    prefix = re.sub(r'_\d{5}$', '_merged', prefix)
    tmp_file = f"{prefix}.tmp"
    filename = f"{prefix}.mp4"
    fps = get_video_fps(video_file, user_fps)
    if fps is None:
        print("Could not determine FPS.")
        return
    
    # Calculate total size of all video files for progress reporting
    total_size = sum(os.path.getsize(f) for f in video_files)
    readable_size = sizeof_fmt(total_size)
    print(f"Total size of all .{extension} files: {readable_size}")

    # Merge files into one big chunk
    with open(tmp_file, 'wb') as wfd:
        for i, file in enumerate(video_files):
            with open(file, 'rb') as fd:
                while chunk := fd.read(1024 * 1024):
                    wfd.write(chunk)
                    print_progress(i + 1, len(video_files), total_size, wfd.tell())

    print("\nStarting ffmpeg conversion... Please wait.")
    
    # Call ffmpeg and capture its output for progress
    cmd = f"ffmpeg -f h264 -r {fps} -i {tmp_file} -vcodec copy -y {filename} -loglevel info"
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    duration_regex = re.compile(r"time=(\d{2}:\d{2}:\d{2}\.\d{2})")
    last_reported_time = None
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            time_match = duration_regex.search(output)
            if time_match:
                current_time = time_match.group(1)
                if last_reported_time != current_time:
                    print(f"ffmpeg processing time: {current_time}", end='\r')
                    last_reported_time = current_time

    process.poll()
    print("\nffmpeg conversion completed.")
    os.remove(tmp_file)

def print_progress(current_file, total_files, total_size, current_size):
    percent = (current_size / total_size) * 100
    bar_length = 40
    filled_length = int(round(bar_length * current_file / float(total_files)))
    bar = '#' * filled_length + '-' * (bar_length - filled_length)
    os.sys.stdout.write(f"\rMerging file {current_file}/{total_files} |{bar}| {percent:.2f}% Completed")
    os.sys.stdout.flush()

def sizeof_fmt(num, suffix='B'):
    """
    Converts bytes to a human-readable format.
    """
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"

def list_mp4s(root_path):
    """
    Returns a list of folders that contains an mp4 file.
    """
    all_folders = [x[0] for x in os.walk(root_path)]
    have_mp4s = [p for p in all_folders if glob(os.path.join(p, "*.mp4"))]
    
    return have_mp4s

def crawl(root_path, extension="h264", force=False, user_fps=None):
    """
    Crawl all terminal folders in root_path.
    """
    all_folders = [x[0] for x in os.walk(root_path)]
    have_mp4s = [p for p in all_folders if glob(os.path.join(p, "*.mp4"))]
    terminal_folders = [p for p in all_folders if glob(os.path.join(p, f"*.{extension}"))]
    
    folders_to_process = terminal_folders if force else [folder for folder in terminal_folders if folder not in have_mp4s]
    print(f"We have {len(folders_to_process)} new folders to process")
    for folder in folders_to_process:
        process_video(folder, extension, user_fps)

def purge_h264_files(root_path, extension="h264"):
    """
    Crawl through all folders in root_path and delete .h264 files
    only if an .mp4 file exists in the same folder.
    """
    print(f"Starting purge process in root path: {root_path}")
    all_folders = [x[0] for x in os.walk(root_path)]
    folders_with_mp4 = [p for p in all_folders if glob(os.path.join(p, "*.mp4"))]
    total_folders = len(folders_with_mp4)
    
    print(f"Found {total_folders} folders with .mp4 files. Proceeding to delete .{extension} files.")
    
    for idx, folder in enumerate(folders_with_mp4, start=1):
        h264_files = glob(os.path.join(folder, f"*.{extension}"))
        if h264_files:
            print(f"[{idx}/{total_folders}] Deleting {len(h264_files)} .{extension} files in folder: {folder}")
            for file_path in h264_files:
                try:
                    os.remove(file_path)
                    print(f"Deleted: {file_path}")
                except Exception as e:
                    print(f"Failed to delete {file_path}: {e}")
        else:
            print(f"[{idx}/{total_folders}] No .{extension} files found in folder: {folder}")
    
    print("Purge process completed.")

if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option("-p", "--path", dest="path", default="/ethoscope_data/videos", help="The root path containing the videos to process")
    parser.add_option("-l", "--list", dest="list", default=False, help="Returns a list of folders containing mp4 files", action="store_true")
    parser.add_option("-e", "--extension", dest="extension", default="h264", help="The extension of the video file chunks generated by the ethoscope")
    parser.add_option("--force", dest="force", default=False, help="Force recreating videos even when MP4s are present", action="store_true")
    parser.add_option("--fps", dest="fps", type="float", help="Override the auto-detection of FPS with a user-defined value")
    parser.add_option("--purge", dest="purge", default=False, help="Purge .h264 files in folders where .mp4 exists", action="store_true")
    (options, args) = parser.parse_args()
    option_dict = vars(options)

    # Handle mutually exclusive options
    actions = ['list', 'purge']
    selected_actions = [action for action in actions if option_dict.get(action)]
    if len(selected_actions) > 1:
        parser.error("Options --list and --purge are mutually exclusive.")

    if option_dict['list']:
        l = list_mp4s(option_dict['path'])
        print("\n".join(l))
        print("Found %s folders with mp4 files" % len(l))
        os.sys.exit()

    if option_dict['purge']:
        purge_h264_files(option_dict['path'], extension=option_dict["extension"])
        os.sys.exit()

    crawl(
        option_dict['path'],
        extension=option_dict["extension"],
        force=option_dict["force"],
        user_fps=option_dict.get("fps")
    )