#!/usr/bin/env python2
# -*- coding: utf-8 -*-
#
#  pvg_headless.py
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

import numpy as np
import cv2
import pysolovideo

class pvg_cli():

    """
    A completeley headless pysolo-video monitor
    Does not require wx
    """

    def __init__(self, source, resolution=None):
        """
        """
    
        self.resolution = resolution

        self.mon = pysolovideo.Monitor()
        self.mon.setSource(source, resolution)
        
    def setTracking(self, track_type, mask_file, output_file):
        track = ( int(track_type) > -1 )
        self.mon.setTracking(track, track_type, mask_file, output_file)
     
    def startTracking(self):
        self.mon.startTracking()
     
    def stopTracking(self):
        self.mon.stopTracking()
        
    def saveSnapshot(self, filename):
        self.mon.saveSnapshot(filename)
        
    def isRunning(self):
        return self.mon.isTracking
        
        

if __name__ == '__main__':

    pysolo_headless = pvg_cli(0, resolution=(640,480), mask_file="mask.msk", track_type=0, output_file="test.txt")
    
    while True:
        c = raw_input("Service started, enter S to stop it or P to take a snapshot:\n ")
        if "S" in str(c).upper(): 
            pysolo_headless.stopTracking()
            print ("Tracking stopped")
            exit()
        elif "P" in str(c).upper(): 
            pysolo_headless.saveSnapshot("0.jpg")
            print ("Snapshot taken")
