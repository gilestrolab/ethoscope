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


import json
import os
import re
import subprocess
import time
from glob import glob
from optparse import OptionParser

# Marker file written by the ethoscope device when a recording terminates (see
# src/ethoscope/ethoscope/control/record.py). Its presence means the .h264 chunks in the
# folder are final and safe to merge.
MARKER_FILENAME = "recording.info"

# Written next to a merged video, last, once the video is complete: <video>.json lists
# every chunk the video holds, with its size. It is what makes a chunk safe to delete,
# here (--purge) and on the node's "Free up space" check
# (src/node/ethoscope_node/utils/device_storage.py, which reads the same format).
MANIFEST_SUFFIX = ".json"

_CHUNK_INDEX = re.compile(r"_(\d{5})$")


def chunk_index(name):
    """
    Return the sequence number of a chunk (``..._00042.h264`` -> 42), or None.

    Args:
        name (str): Chunk file name.

    Returns:
        int | None: The chunk's index.
    """
    match = _CHUNK_INDEX.search(os.path.splitext(os.path.basename(name))[0])
    return int(match.group(1)) if match else None


def list_chunks(folder, extension="h264"):
    """
    Return the folder's chunk names in recording order.

    Hidden files are left out: rsync writes a chunk in transit as ``.<name>.XXXXXX``.

    Args:
        folder (str): Folder holding the chunks.
        extension (str): Chunk file extension.

    Returns:
        list[str]: Chunk file names (not paths), sorted by index.
    """
    names = [os.path.basename(p) for p in glob(os.path.join(folder, f"*.{extension}"))]
    return sorted((n for n in names if chunk_index(n) is not None), key=chunk_index)


def chunks_contiguous(names):
    """
    Tell whether chunks run 1, 2, ... N without a gap.

    Reason: a merge must be the whole recording up to now. A gap means a chunk has not
    arrived yet; a missing chunk 1 means earlier chunks were purged, and merging the
    rest would overwrite the video that holds them.

    Args:
        names (list[str]): Chunk names, sorted by index.

    Returns:
        bool: True for a complete sequence starting at 1.
    """
    return bool(names) and [chunk_index(n) for n in names] == list(range(1, len(names) + 1))


def read_manifest(video_path):
    """
    Read the chunk list written next to a merged video.

    Args:
        video_path (str): Path of the merged .mp4.

    Returns:
        dict | None: The manifest, or None when absent or unreadable.
    """
    try:
        with open(video_path + MANIFEST_SUFFIX) as f:
            manifest = json.load(f)
        return manifest if isinstance(manifest.get("chunks"), list) else None
    except (OSError, ValueError, AttributeError):
        return None


def folder_is_ready(folder, extension="h264", max_age_hours=6, now=None):
    """
    Decide whether a folder's video chunks are safe to convert.

    A folder is ready when the recording-complete marker is present, or - as a safety net for
    legacy recordings and unclean stops where no marker was ever written - when no new chunk
    has arrived for at least ``max_age_hours``.

    Arrival is the chunk's ctime on this machine. Its mtime is the time the device wrote
    it, which rsync preserves: a device on a slow link can be hours behind, and its last
    chunk then looks old the moment it lands (ETHOSCOPE_361, 2026-10-03: a recording still
    under way was merged at 03:22 from the 21 chunks that had arrived).

    Args:
        folder (str): Folder containing the .{extension} chunks.
        extension (str): Chunk file extension (default "h264").
        max_age_hours (float): Age threshold for the marker-less fallback.
        now (float | None): Current time, defaults to ``time.time()``.

    Returns:
        bool: True if the folder should be converted now.
    """
    if os.path.exists(os.path.join(folder, MARKER_FILENAME)):
        return True

    chunks = list_chunks(folder, extension)
    if not chunks:
        return False

    newest_arrival = max(os.stat(os.path.join(folder, n)).st_ctime for n in chunks)
    now = time.time() if now is None else now
    return (now - newest_arrival) / 3600.0 >= max_age_hours


def needs_merge(folder, extension="h264"):
    """
    Decide whether a folder's chunks should be (re)merged, and why.

    A folder is merged when it has no video, or when chunks have arrived that its video
    does not hold: per its manifest, or, for a video merged before manifests existed,
    any chunk that arrived (ctime) after the video was written.

    Args:
        folder (str): Folder holding the chunks.
        extension (str): Chunk file extension.

    Returns:
        tuple[bool, str]: Whether to merge, and the reason.
    """
    chunks = list_chunks(folder, extension)
    if not chunks:
        return False, "no chunks"
    if not chunks_contiguous(chunks):
        return False, "chunks do not run from 00001 without a gap"
    videos = sorted(glob(os.path.join(folder, "*.mp4")))
    if not videos:
        return True, "not merged yet"
    manifest = read_manifest(videos[0])
    if manifest is not None:
        held = {c.get("name") for c in manifest["chunks"]}
        new = [n for n in chunks if n not in held]
        if new:
            return True, f"{len(new)} chunk(s) arrived after the merge"
        return False, "merged"
    video_ctime = os.stat(videos[0]).st_ctime
    if any(os.stat(os.path.join(folder, n)).st_ctime > video_ctime for n in chunks):
        return True, "chunks arrived after the merge (video has no chunk list)"
    return False, "merged (no chunk list)"


def read_marker_fps(folder):
    """
    Return the recording FPS stored in the folder's marker file, or None if unavailable.

    Args:
        folder (str): Folder that may contain a ``recording.info`` marker.

    Returns:
        float | None: The recorded FPS, or None if no/invalid marker.
    """
    marker_path = os.path.join(folder, MARKER_FILENAME)
    try:
        with open(marker_path) as f:
            fps = json.load(f).get("fps")
        return float(fps) if fps is not None else None
    except (OSError, ValueError, TypeError):
        return None


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

def write_manifest(video_path, chunks, fps):
    """
    Record which chunks a merged video holds, atomically, as the merge's last step.

    Args:
        video_path (str): Path of the merged .mp4 (already in place).
        chunks (list[str]): Chunk names merged into it, in order.
        fps (float): Frame rate the video was written at.
    """
    folder = os.path.dirname(video_path)
    manifest = {
        "video": os.path.basename(video_path),
        "fps": fps,
        "merged_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "chunks": [
            {"name": n, "size": os.path.getsize(os.path.join(folder, n))} for n in chunks
        ],
    }
    tmp = video_path + MANIFEST_SUFFIX + ".tmp"
    with open(tmp, "w") as f:
        json.dump(manifest, f, indent=1)
    os.replace(tmp, video_path + MANIFEST_SUFFIX)


def process_video(folder, extension="h264", user_fps=None):
    """
    Merge a folder's chunks into one .mp4 and record which chunks it holds.

    The video is written under a temporary name and moved into place only when ffmpeg
    succeeds; the chunk list is written after it. A merge that fails or is interrupted
    therefore leaves the previous video and its list as they were.

    Args:
        folder (str): Folder holding the chunks.
        extension (str): Chunk file extension.
        user_fps (float | None): Frame rate to use instead of the marker's or ffprobe's.

    Returns:
        bool: True when the video and its chunk list were written.
    """
    os.chdir(folder)
    print(f"Processing folder: {folder}")
    video_files = list_chunks(folder, extension)
    if not video_files:
        print(f"No .{extension} files found in the folder.")
        return False
    if not chunks_contiguous(video_files):
        print(f"Chunks do not run from 00001 without a gap; not merging {folder}")
        return False
    print(f"Number of .{extension} files: {len(video_files)}")

    # Get the first video file to process and create the output filename
    video_file = video_files[0]
    prefix = os.path.splitext(video_file)[0]
    prefix = re.sub(r'_\d{5}$', '_merged', prefix)
    tmp_file = f"{prefix}.tmp"
    filename = f"{prefix}.mp4"
    # Precedence: explicit --fps > recording marker fps > ffprobe auto-detection.
    effective_fps = user_fps if user_fps is not None else read_marker_fps(folder)
    fps = get_video_fps(video_file, effective_fps)
    if fps is None:
        print("Could not determine FPS.")
        return False

    # Calculate total size of all video files for progress reporting
    total_size = sum(os.path.getsize(f) for f in video_files)
    readable_size = sizeof_fmt(total_size)
    print(f"Total size of all .{extension} files: {readable_size}")

    part_file = f"{filename}.part"
    try:
        # Merge files into one big chunk
        with open(tmp_file, 'wb') as wfd:
            for i, file in enumerate(video_files):
                with open(file, 'rb') as fd:
                    while chunk := fd.read(1024 * 1024):
                        wfd.write(chunk)
                        print_progress(i + 1, len(video_files), total_size, wfd.tell())

        print("\nStarting ffmpeg conversion... Please wait.")

        # Call ffmpeg and capture its output for progress
        cmd = ["ffmpeg", "-f", "h264", "-r", str(fps), "-i", tmp_file, "-vcodec", "copy",
               "-f", "mp4", "-y", part_file, "-loglevel", "info"]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

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

        if process.wait() != 0:
            print(f"\nffmpeg failed (exit {process.returncode}); {folder} left as it was.")
            return False
        os.replace(part_file, filename)
        write_manifest(os.path.join(folder, filename), video_files, fps)
        print(f"\nffmpeg conversion completed: {len(video_files)} chunks in {filename}")
        return True
    finally:
        for leftover in (tmp_file, part_file):
            if os.path.exists(leftover):
                os.remove(leftover)

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

def crawl(root_path, extension="h264", force=False, user_fps=None,
          ignore_marker=False, max_age_hours=6):
    """
    Crawl all terminal folders in root_path and convert those whose recording has finished.

    A folder is converted only when its recording is complete - signalled either by the
    ``recording.info`` marker or, as a fallback, by no chunk arriving for
    ``max_age_hours``. ``force`` and ``ignore_marker`` bypass this gate. A folder already
    merged is merged again when chunks have arrived that its video does not hold
    (:func:`needs_merge`); ``force`` re-merges every folder whose chunks are complete.
    """
    all_folders = [x[0] for x in os.walk(root_path)]
    terminal_folders = [p for p in all_folders if list_chunks(p, extension)]

    folders_to_process = []
    for folder in terminal_folders:
        merge, reason = needs_merge(folder, extension)
        if force and chunks_contiguous(list_chunks(folder, extension)):
            merge = True
        if merge:
            print(f"{folder}: {reason}")
            folders_to_process.append(folder)
        elif reason.startswith("chunks do not run"):
            print(f"Not merging {folder}: {reason}")

    if not (force or ignore_marker):
        ready = [f for f in folders_to_process if folder_is_ready(f, extension, max_age_hours)]
        skipped = len(folders_to_process) - len(ready)
        if skipped:
            print(f"Skipping {skipped} folder(s) still recording or too recent (no marker, "
                  f"chunks newer than {max_age_hours}h)")
        folders_to_process = ready

    print(f"We have {len(folders_to_process)} folders to merge")
    for folder in folders_to_process:
        process_video(folder, extension, user_fps)

def purge_h264_files(root_path, extension="h264"):
    """
    Delete the chunks a merged video is known to hold, and no others.

    A chunk goes only when the video's chunk list names it at its current size. A video
    without a list (merged before lists were written) may lack chunks that arrived after
    it, so its folder is left alone; ``--force`` re-merges it and writes the list.

    Args:
        root_path (str): Root of the video folders.
        extension (str): Chunk file extension.
    """
    print(f"Starting purge process in root path: {root_path}")
    all_folders = [x[0] for x in os.walk(root_path)]
    folders_with_mp4 = [p for p in all_folders if glob(os.path.join(p, "*.mp4"))]
    total_folders = len(folders_with_mp4)

    print(f"Found {total_folders} folders with .mp4 files.")

    for idx, folder in enumerate(folders_with_mp4, start=1):
        listed = {}
        for video in glob(os.path.join(folder, "*.mp4")):
            manifest = read_manifest(video)
            if manifest is not None:
                listed.update({c.get("name"): c.get("size") for c in manifest["chunks"]})
        chunks = list_chunks(folder, extension)
        if not listed:
            if chunks:
                print(f"[{idx}/{total_folders}] Keeping {len(chunks)} chunk(s) in {folder}: "
                      "its video has no chunk list (re-merge with --force to write one)")
            continue
        for name in chunks:
            path = os.path.join(folder, name)
            if listed.get(name) != os.path.getsize(path):
                print(f"Keeping {path}: not in the merged video")
                continue
            try:
                os.remove(path)
                print(f"Deleted: {path}")
            except Exception as e:
                print(f"Failed to delete {path}: {e}")

    print("Purge process completed.")

if __name__ == '__main__':
    # Get default path from environment variable
    default_videos_path = os.getenv("ETHOSCOPE_VIDEOS_DIR", "/ethoscope_data/videos")

    parser = OptionParser()
    parser.add_option("-p", "--path", dest="path", default=default_videos_path, help=f"The root path containing the videos to process (default: {default_videos_path})")
    parser.add_option("-l", "--list", dest="list", default=False, help="Returns a list of folders containing mp4 files", action="store_true")
    parser.add_option("-e", "--extension", dest="extension", default="h264", help="The extension of the video file chunks generated by the ethoscope")
    parser.add_option("--force", dest="force", default=False, help="Re-merge every folder whose chunks run from 00001 without a gap, even when its .mp4 looks current", action="store_true")
    parser.add_option("--fps", dest="fps", type="float", help="Override the auto-detection of FPS with a user-defined value")
    parser.add_option("--purge", dest="purge", default=False, help="Delete the .h264 chunks a merged .mp4 is known to hold (listed in its .mp4.json)", action="store_true")
    parser.add_option("--ignore-marker", dest="ignore_marker", default=False, help="Convert regardless of the recording.info marker / chunk age (process unfinished recordings too)", action="store_true")
    parser.add_option("--max-age-hours", dest="max_age_hours", type="float", default=6, help="For folders without a marker, only convert when the newest chunk is older than this many hours (default: 6)")
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
        user_fps=option_dict.get("fps"),
        ignore_marker=option_dict["ignore_marker"],
        max_age_hours=option_dict["max_age_hours"],
    )
