#!/usr/bin/env python
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

from pvg_common import pvg_config, acquireThread, acquireObject

if __name__ == '__main__':

    parser = optparse.OptionParser(usage='%prog [options] [argument]', version='%prog version 1.0')
    parser.add_option('-c', '--config', dest='config_file', metavar="CONFIG_FILE", help="The full path to the config file to open")

    (options, args) = parser.parse_args()

    configfile = options.config_file
    
    if configfile is None:
        print ('You need to specify the path to a config file')
        parser.print_help()
        exit(-1)
    
    try:
        option_file = pvg_config(configfile)
    except:
        print ('Problem with configuration file %s.' % configfile)
        exit(-1)
        
    monitorsData = option_file.getMonitorsData()
    print ( "Found %s monitors." % len(monitorsData) )
        
    for mn in monitorsData:
        m = monitorsData[mn]
        at = acquireObject(mn, m['source'], m['resolution'], m['mask_file'], m['track'], m['track_type'], m['dataFolder'])
        at.keepGoing = True
        at.start()
        print ( "%s: Acquisition for monitor %s started." % ( time.ctime(), mn ))
