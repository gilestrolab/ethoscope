import os
import cv2
import sqlite3
import numpy as np
from datetime import datetime, timedelta

import argparse
from tqdm import tqdm

def connect_and_extract_video(db_name, resolution=(640, 480), font_scale: float = 0.5, font_color: tuple = (255, 255, 255)) -> None:

    # Connect to the SQLite database
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()

    # Retrieve start_time from METADATA table, assuming date_time is in milliseconds since the epoch
    cursor.execute("SELECT value FROM METADATA WHERE field='date_time'")
    start_time_s = cursor.fetchone()[0]
    start_time = datetime(1970, 1, 1) + timedelta(seconds=float(start_time_s))


    # Retrieve the image blobs from the IMG_SNAPSHOTS table
    cursor.execute("SELECT img, t FROM IMG_SNAPSHOTS")
    img_data = cursor.fetchall()

    # Convert each image blob to a numpy array
    images = [(np.frombuffer(data[0], dtype=np.uint8), start_time + timedelta(milliseconds=int(data[1]))) for data in img_data]

    # Create a video writer object
    base_name, _ = os.path.splitext(db_name)
    video_name = base_name + ".avi"

    video_writer = cv2.VideoWriter(video_name, cv2.VideoWriter_fourcc(*'XVID'), 30, resolution)
    count = 0

    #print (f"start time is {start_time_ms}")

    # Iterate through the images and write them to the video file
    for img, timestamp in tqdm(images):
        # Decode the image from the numpy array
        decoded_img = cv2.imdecode(img, cv2.IMREAD_COLOR)
        # Resize the image to the desired video size
        resized_img = cv2.resize(decoded_img, resolution)
        # Put timestamp on the image
        timestamp_text = timestamp.strftime('%Y-%m-%d %H:%M:%S')[:-3]
        cv2.putText(resized_img, timestamp_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_color, 1, cv2.LINE_AA)
        # Write the resized image to the video file
        video_writer.write(resized_img)
        count += 1


    # Release the video writer and close the database connection
    video_writer.release()
    conn.close()
    print ("Processed %s frames into file: %s" % (count, video_name))


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Process a db file, extract images and make a video out of them.')
    parser.add_argument('filename', help='The name of the ethoscope sqlite3 file to process')
    args = parser.parse_args()

    connect_and_extract_video(args.filename)
