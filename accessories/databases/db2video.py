"""
A script to extract frames from a .db file and create a video.

Dependencies:
    - ffmpeg: Used to compile the extracted images into a video.
    - ImageMagick: Specifically the `convert` tool is used for annotating images.

Typical .db File Path:
    /ethoscope_data/results/0256424ac3f545b6b3c687723085ffcb/ETHOSCOPE_025/2024-10-06_17-36-47/2024-10-06_17-36-47_0256424ac3f545b6b3c687723085ffcb.db

Usage Example:
    python db_to_video.py \
        -i /ethoscope_data/results/0256424ac3f545b6b3c687723085ffcb/ETHOSCOPE_025/2024-10-06_17-36-47/2024-10-06_17-36-47_0256424ac3f545b6b3c687723085ffcb.db \
        -o output_video.mp4 \
        -f 5 \
        -a

    This command will:
        - Extract frames from the specified `.db` file.
        - Annotate each frame with the corresponding date and time.
        - Compile the annotated frames into a video named `output_video.mp4` at 5 frames per second.

Options:
    -i, --input      : The input `.db` file containing image snapshots.
    -o, --output     : The desired output video file (e.g., `output.mp4`).
    -f, --fps        : Frames per second for the output video (default is 1).
    -a, --annotate   : If set, annotations (date and time) will be added to each frame.

Ensure that both `ffmpeg` and `ImageMagick` are installed and accessible in your system's PATH before running this script.
"""

import sqlite3
import io
import tempfile
import shutil
import os
from optparse import OptionParser
import datetime
import glob
from multiprocessing import Pool

def annotate_image(args):
    """
    Annotates an image with a timestamp.

    Args:
        args (tuple): Contains the file path, timestamp, and base time.
    """
    input_file, time, t0 = args
    # Convert timestamp to human-readable format
    label = datetime.datetime.fromtimestamp(time/1000 + t0).strftime('%Y-%m-%d %H:%M:%S')
    out_file = input_file + "_tmp.jpg"
    # Command to annotate the image using ImageMagick's convert tool
    command = (
        f"convert {input_file} "
        f"-pointsize 50 -font FreeMono -background Khaki "
        f"label:'{label}' +swap -gravity Center -append {out_file}"
    )
    os.system(command)
    # Replace the original image with the annotated version
    shutil.move(out_file, input_file)

def make_video_file(file, output, fps=1, annotate=True):
    """
    Extracts images from the database, optionally annotates them, and compiles them into a video.

    Args:
        file (str): Path to the input `.db` file.
        output (str): Path for the output video file.
        fps (int, optional): Frames per second for the video. Defaults to 1.
        annotate (bool, optional): Whether to annotate images with timestamps. Defaults to True.
    """
    # Create a temporary directory to store extracted images
    dir = tempfile.mkdtemp(prefix="etho_video")
    try:
        with sqlite3.connect(file, check_same_thread=False) as conn:
            cursor = conn.cursor()
            # Retrieve metadata to get base timestamp
            sql_metadata = 'SELECT field, value FROM METADATA'
            cursor.execute(sql_metadata)
            t0 = 0
            for field, value in cursor:
                if field == "date_time":
                    t0 = float(value)
            # Retrieve image snapshots
            sql_images = 'SELECT id, t, img FROM IMG_SNAPSHOTS'
            cursor.execute(sql_images)

            # Extract and save each image to the temporary directory
            for i, record in enumerate(cursor):
                id, t, blob = record
                file_name = os.path.join(dir, f"{id:05d}_{t}.jpg")
                with open(file_name, "wb") as out_file:
                    out_file.write(blob)

            if annotate:
                # Prepare arguments for multiprocessing
                pool = Pool(4)
                pool_args = []
                for f in glob.glob(os.path.join(dir, "*.jpg")):
                    t = int(os.path.basename(f).split("_")[1].split(".")[0])
                    pool_args.append((f, t, t0))
                # Annotate images in parallel
                pool.map(annotate_image, pool_args)
                pool.close()
                pool.join()

            # Compile annotated images into a video using ffmpeg
            command = (
                f"ffmpeg -loglevel panic -y -framerate {fps} "
                f"-pattern_type glob -i '{dir}/*.jpg' -c:v libx264 {output}"
            )
            os.system(command)
    finally:
        # Clean up the temporary directory
        shutil.rmtree(dir)

if __name__ == '__main__':
    # Set up command-line argument parsing
    parser = OptionParser()
    parser.add_option(
        "-i", "--input", dest="input", help="The input .db file"
    )
    parser.add_option(
        "-o", "--output", dest="output", help="The output mp4 video file"
    )
    parser.add_option(
        "-f", "--fps", dest="fps", default=1, type="int",
        help="Frames per second for the output video (default: 1)"
    )
    parser.add_option(
        "-a", "--annotate", dest="annot", default=False,
        help="Annotate frames with date and time", action="store_true"
    )
    (options, args) = parser.parse_args()
    option_dict = vars(options)

    # Validate required arguments
    if not option_dict["input"] or not option_dict["output"]:
        parser.error("Both input and output files must be specified. Use -h for help.")

    # Call the main function to create the video
    make_video_file(
        file=option_dict["input"],
        output=option_dict["output"],
        fps=option_dict["fps"],
        annotate=option_dict["annot"]
    )