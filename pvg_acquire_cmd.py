#!/usr/bin/env python2
# -*- coding: utf-8 -*-
#
#       pvg_acquire.py
#       
#       Copyright 2011 Giorgio Gilestro <giorgio@gilest.ro>
#       
#       This program is free software; you can redistribute it and/or modify
#       it under the terms of the GNU General Public License as published by
#       the Free Software Foundation; either version 2 of the License, or
#       (at your option) any later version.
#       
#       This program is distributed in the hope that it will be useful,
#       but WITHOUT ANY WARRANTY; without even the implied warranty of
#       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#       GNU General Public License for more details.
#       
#       You should have received a copy of the GNU General Public License
#       along with this program; if not, write to the Free Software
#       Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#       MA 02110-1301, USA.
#       
#       

import os, threading, wx
import pysolovideo as pv
from pvg_common import pvg_config

def getMonitorsData(configfile=None):
    """
    return a list containing the monitors that we need to track 
    based on info found in configfile
    """
    monitors = {}
    
    options = pvg_config(configfile)
    print ("Reading configuration from file %s" % configfile)
      
    ms = options.GetOption('Monitors')
    resolution = options.GetOption('FullSize')
    dataFolder = options.GetOption('Data_Folder')
    
    for mon in range(ms):
        if options.HasMonitor(mon):
            _,source,track,mask_file,track_type = options.GetMonitor(mon)
            monitors[mon] = {}
            monitors[mon]['source'] = source
            monitors[mon]['resolution'] = resolution
            monitors[mon]['mask_file'] = mask_file
            monitors[mon]['track_type'] = track_type
            monitors[mon]['dataFolder'] = dataFolder
            monitors[mon]['track'] = track
        
    print ( "Found %s monitors." % len(monitors) )
    
    return monitors
 
class acquireThread(threading.Thread):

    def __init__(self, monitor, source, resolution, mask_file, track, track_type, dataFolder):
        """
        """
        threading.Thread.__init__(self)
        self.monitor = monitor
        self.keepGoing = True
        self.track = track
        outputFile = os.path.join(dataFolder, 'MON%02d.txt' % monitor)
        
        self.mon = pv.Monitor()
        self.mon.setSource(source, resolution)
        self.mon.setTracking(True, track_type, mask_file, outputFile)
        
        print outputFile
        print ( "Setting monitor %s with source %s and mask %s. Output to %s " % (monitor, source, os.path.split(mask_file)[1], os.path.split(outputFile)[1] ) )
        
    def run(self):
        """
        """
        while self.keepGoing:
            try:
                self.mon.GetImage()
            except KeyboardInterrupt:
                self.halt()
        
    def halt(self):
        """
        """
        self.keepGoing = False
        print ( "Stopping capture" )


if __name__ == '__main__':

    configfile = None
    
    if len(os.sys.argv) > 1 and os.path.isfile(os.sys.argv[1]):
        configfile = os.sys.argv[1]
    else:
        print ('You need to specify a config file')
        exit()
        
    monitorsData = getMonitorsData(configfile)
    
    
    for mn in monitorsData:
        m = monitorsData[mn]
        at = acquireThread(mn, m['source'], m['resolution'], m['mask_file'], m['track_type'], m['dataFolder'])
        at.start()
