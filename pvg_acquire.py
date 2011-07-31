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

import os
import pysolovideo as pv
from pvg_common import pvg_config


def acquire(configfile):
    '''
    '''
    
    options = pvg_config(configfile)
    print "Reading configuration from file %s" % configfile
   
    resolution = options.GetOption('FullSize')
    monitors = options.GetOption('Monitors')

    ms = []

    for mon in range(monitors):
        
        if options.HasMonitor(mon):
            sourceType, source, track, mask_file = options.GetMonitor(mon)
            if sourceType == 0: source = int(source.split(' ')[1]) # get webcam number
            
            if track and mask_file:
                m = pv.Monitor()
                m.setSource(source, resolution)
                m.tracking = track
                m.arena.outputFile = 'MON%s.txt' % mon
                m.loadROIS(mask_file)
                ms.append( m )
                print "Setting monitor %s with source %s and mask %s. Output to %s " % (mon, source, mask_file, m.arena.outputFile)
    
    while True:
        for m in ms:
            m.GetImage()
        
if __name__ == '__main__':
    
    if len(os.sys.argv) > 1:
        configfile = os.sys.argv[1]
        if os.path.isfile(configfile): acquire(configfile)


