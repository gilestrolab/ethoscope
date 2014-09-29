#!/usr/bin/env python2
# -*- coding: utf-8 -*-
#
#  receive_stream.py
#  
#  Copyright 2014 Giorgio Gilestro <giorgio@gilest.ro>
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

import cv2
import socket, io, struct
from PIL import Image
import numpy as np


title = "streaming test"
cv2.namedWindow(title, cv2.CV_WINDOW_AUTOSIZE)

def open_with_socket():

    # Connect a client socket to my_server:8000 (change my_server to the
    # hostname of your server)
    client_socket = socket.socket()

    client_socket.connect(('192.168.1.201', 8000))

    connection = client_socket.makefile('rb')

    try:
        while True:
            # Read the length of the image as a 32-bit unsigned int. If the
            # length is zero, quit the loop
            image_len = struct.unpack('<L', connection.read(4))[0]
            if not image_len:
                break
            # Construct a stream to hold the image data and read the image
            # data from the connection
            image_stream = io.BytesIO()
            image_stream.write(connection.read(image_len))
            # Rewind the stream, open it as an image with PIL and do some
            # processing on it
            image_stream.seek(0)
            image = Image.open(image_stream).convert('RGB') 
            cv_image = np.array(image) 
            cv2.imshow( title, cv_image )

            key = cv2.waitKey(20)
            if key > 0: # exit on ESC
                break
    finally:
        connection.close()
        client_socket.close()


def open_with_cv():
    
    cap = cv2.VideoCapture("192.168.1.201:9000")
    
    while(True):
        ret, frame = cap.read()

        #gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Display the resulting frame
        cv2.imshow(title, frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # When everything done, release the capture
    cap.release()
    cv2.destroyAllWindows()
    
#open_with_cv()
open_with_socket()
