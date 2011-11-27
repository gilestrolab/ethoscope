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

import os, time
import optparse

import pysolovideo as pv
from pvg_common import pvg_config, acquireThread

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
    print ( "%s: Acquisition started." % time.ctime() )
    
    return monitors
 
if __name__ == '__main__':

    parser = optparse.OptionParser(usage='%prog [options] [argument]', version='%prog version 1.0')
    parser.add_option('-c', '--config', dest='config_file', metavar="CONFIG_FILE", help="The full path to the config file to open")

    (options, args) = parser.parse_args()

    configfile = options.config_file
    
    if configfile is None:
        print ('You need to specify the path to a config file')
        parser.print_help()
        exit(-1)
    
    if not os.path.isfile(configfile):
        print ('%s does not exist or is not accessible' % configfile)
        exit(-1)
        
    monitorsData = getMonitorsData(configfile)
        
    for mn in monitorsData:
        m = monitorsData[mn]
        startTrack = True
        at = acquireThread(mn, m['source'], m['resolution'], m['mask_file'], startTrack, m['track_type'], m['dataFolder'])
        at.keepGoing = True
        at.start()
