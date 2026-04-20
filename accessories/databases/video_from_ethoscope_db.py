import os
import subprocess
import cv2
import sqlite3
import numpy as np
from datetime import datetime, timedelta

import argparse
from tqdm import tqdm


def load_tracking_data(conn):
    """
    Load ROI map and all tracking positions from the database.

    Args:
        conn: SQLite connection object.

    Returns:
        dict: Mapping of ROI index to list of (t_ms, abs_x, abs_y, w, h, phi)
              tuples, sorted by timestamp. Returns empty dict if no tracking data.
    """
    cursor = conn.cursor()

    # Load ROI_MAP for coordinate offsets
    try:
        cursor.execute("SELECT roi_idx, x, y FROM ROI_MAP")
        roi_offsets = {int(row[0]): (int(row[1]), int(row[2])) for row in cursor.fetchall()}
    except sqlite3.OperationalError:
        return {}

    if not roi_offsets:
        return {}

    # Discover ROI_* tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ROI_%'")
    roi_tables = [row[0] for row in cursor.fetchall() if row[0] != "ROI_MAP"]

    tracking = {}
    for table_name in roi_tables:
        roi_idx = int(table_name.split("_")[1])
        offset_x, offset_y = roi_offsets.get(roi_idx, (0, 0))

        try:
            cursor.execute(f"SELECT t, x, y, w, h, phi FROM {table_name} ORDER BY t")
            positions = [
                (int(row[0]), int(row[1]) + offset_x, int(row[2]) + offset_y,
                 int(row[3]), int(row[4]), int(row[5]))
                for row in cursor.fetchall()
            ]
            if positions:
                tracking[roi_idx] = positions
        except sqlite3.OperationalError:
            continue

    return tracking


def find_nearest_positions(tracking, snap_t, tolerance_ms=30000):
    """
    For each ROI, find the tracked position nearest to snap_t.

    Args:
        tracking (dict): ROI index -> list of (t_ms, abs_x, abs_y, w, h, phi).
        snap_t (int): Snapshot timestamp in milliseconds.
        tolerance_ms (int): Max time difference to consider a match (default 30s).

    Returns:
        list: List of (roi_idx, abs_x, abs_y, w, h, phi) for positions within tolerance.
    """
    results = []
    for roi_idx, positions in tracking.items():
        # Binary search for nearest timestamp
        lo, hi = 0, len(positions) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if positions[mid][0] < snap_t:
                lo = mid + 1
            else:
                hi = mid

        # Check the candidate and its neighbor for closest match
        best = lo
        if best > 0 and abs(positions[best - 1][0] - snap_t) < abs(positions[best][0] - snap_t):
            best = best - 1

        t, x, y, w, h, phi = positions[best]
        if abs(t - snap_t) <= tolerance_ms:
            results.append((roi_idx, x, y, w, h, phi))

    return results


def draw_tracking_overlay(img, positions, original_size, display_size):
    """
    Draw fly position ellipses on the frame, matching the live tracking style.

    Uses cv2.ellipse with (x, y) as center, (w, h) as axes, and phi as angle,
    consistent with DefaultDrawer._annotate_frame() in drawers.py.

    Args:
        img (numpy.ndarray): The frame to draw on (modified in-place).
        positions (list): List of (roi_idx, abs_x, abs_y, w, h, phi) in original image coords.
        original_size (tuple): (width, height) of the original image.
        display_size (tuple): (width, height) of the displayed/resized image.
    """
    scale_x = display_size[0] / original_size[0]
    scale_y = display_size[1] / original_size[1]

    for roi_idx, abs_x, abs_y, w, h, phi in positions:
        disp_x = int(abs_x * scale_x)
        disp_y = int(abs_y * scale_y)
        disp_w = max(int(w * scale_x), 1)
        disp_h = max(int(h * scale_y), 1)
        cv2.ellipse(img, ((disp_x, disp_y), (disp_w, disp_h), phi), (0, 0, 255), 1, cv2.LINE_AA)


def connect_and_extract_video(db_name, resolution=(640, 480), font_scale: float = 0.5,
                              font_color: tuple = (255, 255, 255), track: bool = False) -> None:
    """
    Extract snapshots from a .db file and compile them into a video.

    Args:
        db_name (str): Path to the SQLite database file.
        resolution (tuple): Output video resolution (width, height).
        font_scale (float): Font scale for timestamp text.
        font_color (tuple): BGR color for timestamp text.
        track (bool): If True, overlay tracked fly positions on each frame.
    """
    # Connect to the SQLite database
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    # Retrieve start_time from METADATA table, assuming date_time is in milliseconds since the epoch
    cursor.execute("SELECT value FROM METADATA WHERE field='date_time'")
    start_time_s = cursor.fetchone()[0]
    start_time = datetime(1970, 1, 1) + timedelta(seconds=float(start_time_s))

    # Load tracking data if requested
    tracking = load_tracking_data(conn) if track else {}
    if track and not tracking:
        print("Warning: --track enabled but no tracking data found in database")

    # Retrieve the image blobs from the IMG_SNAPSHOTS table
    cursor.execute("SELECT img, t FROM IMG_SNAPSHOTS")
    img_data = cursor.fetchall()

    # Convert each image blob to a numpy array
    images = [(np.frombuffer(data[0], dtype=np.uint8), int(data[1]),
               start_time + timedelta(milliseconds=int(data[1]))) for data in img_data]

    # Create video via ffmpeg pipe for maximum compatibility (H.264 + MP4)
    base_name, _ = os.path.splitext(db_name)
    video_name = base_name + ".mp4"

    ffmpeg_cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{resolution[0]}x{resolution[1]}",
        "-r", "30",
        "-i", "pipe:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "fast", "-crf", "23",
        video_name,
    ]
    ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)
    count = 0

    # Iterate through the images and write them to the video file
    for img, t_ms, timestamp in tqdm(images):
        # Decode the image from the numpy array
        decoded_img = cv2.imdecode(img, cv2.IMREAD_COLOR)
        original_size = (decoded_img.shape[1], decoded_img.shape[0])
        # Resize the image to the desired video size
        resized_img = cv2.resize(decoded_img, resolution)
        # Put timestamp on the image
        timestamp_text = timestamp.strftime('%Y-%m-%d %H:%M:%S')[:-3]
        cv2.putText(resized_img, timestamp_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_color, 1, cv2.LINE_AA)

        # Draw tracked fly positions if enabled
        if tracking:
            positions = find_nearest_positions(tracking, t_ms)
            draw_tracking_overlay(resized_img, positions, original_size, resolution)

        # Write raw frame to ffmpeg stdin
        ffmpeg_proc.stdin.write(resized_img.tobytes())
        count += 1

    # Finalize video and close database
    ffmpeg_proc.stdin.close()
    ffmpeg_proc.wait()
    conn.close()
    print("Processed %s frames into file: %s" % (count, video_name))


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Process a db file, extract images and make a video out of them.')
    parser.add_argument('filename', help='The name of the ethoscope sqlite3 file to process')
    parser.add_argument('-t', '--track', action='store_true', default=False,
                        help='Overlay tracked fly positions (x,y) from ROI tables onto each frame')
    args = parser.parse_args()

    connect_and_extract_video(args.filename, track=args.track)
