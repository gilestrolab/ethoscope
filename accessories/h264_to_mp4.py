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


def get_video_fps(video_file):
    """
    Returns the frame rate of the video using ffprobe.
    """
    try:
        result = subprocess.run(
            ['ffprobe', '-v', '0', '-of', 'csv=p=0', '-select_streams', 'v:0', 
             '-show_entries', 'stream=r_frame_rate', video_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        output = result.stdout.decode('utf-8').strip()
        # Calculate FPS from the fraction given by ffprobe
        num, den = map(int, output.split('/'))
        fps = num / den
        return fps
    except Exception as e:
        print(f"Error getting FPS: {e}")
        return None

def process_video(folder, verbose=True):
    """
    Process video in folder with detailed status updates and a progress bar.
    """
    os.chdir(folder)
    print(f"Processing folder: {folder}")

    video_files = glob("*.h264")
    if not video_files:
        print("No .h264 files found in the folder.")
        return

    print(f"Number of .h264 files: {len(video_files)}")

    # Get the first video file to process
    video_file = video_files[0]
    prefix = os.path.splitext(video_file)[0]

    fps = get_video_fps(video_file)
    if fps is None:
        print("Could not determine FPS.")
        return

    tmp_file = f"{prefix}.tmp"
    filename = f"{prefix}.mp4"

    # Calculate total size of all .h264 files for progress reporting
    total_size = sum(os.path.getsize(f) for f in video_files)
    readable_size = sizeof_fmt(total_size)
    print(f"Total size of all .h264 files: {readable_size}")
    
    # Merge files into one big chunk
    with open(tmp_file, 'wb') as wfd:
        for i, file in enumerate(video_files):
            with open(file, 'rb') as fd:
                while chunk := fd.read(1024 * 1024):  # Read in 1MB chunks
                    wfd.write(chunk)
                    print_progress(i + 1, len(video_files), total_size, wfd.tell())

    print("\nStarting ffmpeg conversion... Please wait.")
    # Call ffmpeg and capture its output for progress
    cmd = f"ffmpeg -r {fps} -i {tmp_file} -vcodec copy -y {filename} -loglevel info"
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
    # Cleanup temporary files
    os.system(f"rm {tmp_file}")

    if verbose:
        print(f"\nSuccessfully processed files in folder {folder}")

def print_progress(current_file, total_files, total_size, current_size):
    percent = (current_size / total_size) * 100
    bar_length = 40
    filled_length = int(round(bar_length * current_file / float(total_files)))
    bar = '#' * filled_length + '-' * (bar_length - filled_length)
    sys.stdout.write(f"\rMerging file {current_file}/{total_files} |{bar}| {percent:.2f}% Completed")
    sys.stdout.flush()


def sizeof_fmt(num, suffix='B'):
    """
    Converts bytes to a human-readable format.
    """
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"


def list_mp4s (root_path):
    '''
    returns a list of folders that contains a mp4 file
    '''

    all_folders = [ x[0] for x in os.walk(root_path) ]
    have_mp4s = [p for p in all_folders if glob(os.path.join(p, "*.mp4"))]
    
    return have_mp4s
    

def crawl (root_path):
    '''
    crawl all terminal folders in root_path
    '''

    all_folders = [ x[0] for x in os.walk(root_path) ]

    have_mp4s = [p for p in all_folders if glob(os.path.join(p, "*.mp4"))]
    terminal_folders = [p for p in all_folders if glob(os.path.join(p, "*.h264"))]
    
    for folder in terminal_folders:
        if folder not in have_mp4s:
            process_video (folder)


if __name__ == '__main__':
    
    parser = OptionParser()
    parser.add_option("-p", "--path", dest="path", default="/ethoscope_data/videos", help="The root path containing the videos to process")
    parser.add_option("-l", "--list", dest="list", default=False, help="Returns a list of folders containing mp4 files", action="store_true")

    (options, args) = parser.parse_args()
    option_dict = vars(options)
    
    if option_dict['list']:
        l = list_mp4s (option_dict['path'])
        
        print ("\n".join(l))
        print ("Found %s folders with mp4 files" % len(l))
        os.sys.exit()
    
    crawl( option_dict['path'] )
