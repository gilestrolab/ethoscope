#!/usr/bin/env python2
# -*- coding: utf-8 -*-
#
#       convert.py
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

import numpy as np
import os
import optparse


HEADER_LENGTH=10 # 10 is the same as trikinetics files
TAB = '\t'

def CoordsFromFile(filename):
    """
    Reads coordinates from a result file
    Returns a 3 dimensional array of shape ( frames, flies, (x,y) )
    """
    coords = []
    empty_coord = ['0', '0']
    
    try:
        fh = open(filename, 'r')
        rawfile = fh.read().split('\n')
        fh.close()

        for line in rawfile:
            if line:
                data = [xy.split(',') if ',' in xy else empty_coord for xy in line.split(TAB)[HEADER_LENGTH:] ]
                if len(data) == 32: # If the computer crashes during data collection sometimes a line is not saved properly
                    coords.append( data )
                    
        
        a = np.array(coords, dtype=float)
        
        return a
        
    except IOError:
        print "Error opening the file"
        return False
       
        
def CountsFromFile(filename):
    """
    Reads beam counts from a result file
    Returns a 2 dimensional array of shape (frames, flies)
    where each value is the count for a fly per minute
    """
    counts = []
    try:
        fh = open(filename, 'r')
        rawfile = fh.read().split('\n')
        fh.close()

        for line in rawfile:
            if line:
                counts.append( line.split(TAB)[HEADER_LENGTH:] )

        a = np.array(counts, dtype=int)
        
        return a
        
    except IOError:
        print "Error opening the file"
        return False
    

def DistanceFromFile(filename):
    """
    Reads distance counts from a result file
    Returns a 2 dimensional array of shape (frames, flies)
    where each value is the distance for a fly per minute
    """
    return CountsFromFile(filename)

def plotFlyActivity(coords, fly):
    """
    """
    orientation, md = getMidlines(coords)
    x = coords[:,:,:1]; y = coords[:,:,1:]
    
    if orientation == 'H':
        activity = x[:,fly]
    if orientation == 'V':
        activity = y[:,fly]
        
    m = md[fly]
    
    up = np.ma.array(activity, mask=activity>=m)
    down = np.ma.array(activity, mask=activity<=m)
    pylab.plot(up, 'b-')
    pylab.plot(down, 'g-')
    

def getMidlines(coords):
    """
    """
    x = coords[:,:,:1]; y = coords[:,:,1:]
    
    
    x_span = x.max(0) - x.min(0)
    y_span = y.max(0) - y.min(0)
    
    if y_span.max() > x_span.max(): 
        orientation = 'V'
        md = y_span / 2
        
    if x_span.max() > y_span.max(): 
        orientation = 'H'
        md = x_span / 2
    
    return orientation, md

def compressArray(a, resolution=60):
    """
    This is used to compress an array having data in seconds
    to an array summing each 60 seconds into one minute
    """
    
    frames, flies, d = a.shape

    resolution = np.round(frames / 1440.)

    bins = frames / resolution 
    rest = frames % resolution

    if rest:
        lastbit = a[frames-rest:].sum(0)
        b = a[:frames-rest].reshape(-1,resolution,flies,d).sum(1)
        c = np.append(b, lastbit).reshape(-1,flies,d)
    else:
        c = a[:frames-rest].reshape(-1,resolution,flies,d).sum(1)
    
    c = np.array(c, dtype=int)
    return c


def CoordsToBeamCrossings(coords):
    """
    Transform an array containing coordinates to a beam crossing count
    coords should be a numpy array of shape ( frames, flies, (x,y) )
    
    orientation     H   Horizontal, use X value to check crossing
                    V   Vertical    use Y value to check crossing
    """
   
    orientation, md = getMidlines(coords)
    
    fs = np.roll(coords, -1, 0)
    
    x = coords[:,:,:1]; y = coords[:,:,1:]
    x1 = fs[:,:,:1]; y1 = fs[:,:,1:]
    
    if orientation == 'H':
        crossed = (x < md ) * ( md < x1) + (x > md) * (md > x1)
    else:
        crossed = (y < md ) * ( md < y1) + (y > md) * (md > y1)

    return compressArray(crossed)
    
    
def CoordsToDistance(coords):
    """
    Motion is calculated as distance in px per minutes
    """
    fs = np.roll(coords, -1, 0)
    
    x = coords[:,:,:1]; y = coords[:,:,1:]
    x1 = fs[:,:,:1]; y1 = fs[:,:,1:]
    
    d = np.sqrt ( (x1-x)**2 + (y1-y)**2 )
    
    frames, flies, _ = d.shape
    #d = d[~np.isnan(d)]; d = d[~np.isinf(d)]
    #d = d.reshape((frames, flies))

    return compressArray(d)
    #return d

def getHeaders(filename):
    """
    """
    headers = []
    try:
        fh = open(filename, 'r')
        rawfile = fh.read().split('\n')
        fh.close()

        for line in rawfile:
            if line:
                headers.append( line.split(TAB)[:HEADER_LENGTH] )

        
    except IOError:
        print "Error opening the file"

    return headers


def detectFileType(filename):
    """
    Understand the file type by looking at the informative
    byte in the last line of the file to open
    """
    position = 4
    with open(filename, 'r') as inputfile:
        lastline = inputfile.read().split('\n')[-2]

    trackType = lastline.split(TAB)[position]
    
    return int(trackType)
    
#Conversion front-ends  

def c2b(file_in, file_out=None, extend=True):
    """
    Converts Coordinate to virtual beam crossing
    """

    new_content = ''
    data =  CoordsFromFile(file_in) #This contains only the actual coordinates
    beams = CoordsToBeamCrossings(data)
    headers = getHeaders(file_in)
    VALUES_PER_MINUTE = int(np.floor( len(data) / 1440. ))
    
    flies = beams.shape[1]
    
    if extend and flies < 32:
        extension = TAB + TAB.join(['0',] * (32-flies) )
    else:
        extension = ''
    

    for h, c in zip ( headers[::VALUES_PER_MINUTE], beams):
        new_content += (
                             TAB.join(h) + TAB +
                             #'0TAB * 2' + #This is not needed anymore
                             TAB.join( [str(xy)[1:-1] for xy in c.tolist()] ) +
                             extension +
                             '\n'
                           )
                           
    if file_out:
        try:
            fh = open(file_out, 'w')
            fh.write ( new_content )
            fh.close()

        except IOError:
            print "Error opening the output file"
            
    return new_content

   
def c2d(file_in, file_out=None, extend=True):
    """
    Converts coordinates to distance
    """
    
    new_content = ''
    data =  CoordsFromFile(file_in) #This contains only the actual coordinates
    dist = CoordsToDistance(data)
    headers = getHeaders(file_in)
    VALUES_PER_MINUTE = int(np.floor( len(data) / 1440. ))
    
    flies = dist.shape[1]
    
    if extend and flies < 32:
        extension = TAB + TAB.join(['0',] * (32-flies) )
    else:
        extension = ''
    

    for h, c in zip ( headers[::VALUES_PER_MINUTE], dist):
        new_content += (
                             TAB.join(h) + TAB +
                             #'0TAB * 2' + #This is not needed anymore
                             TAB.join( [str(xy)[1:-1] for xy in c.tolist()] ) +
                             extension +
                             '\n'
                           )
                           
    if file_out:
        try:
            fh = open(file_out, 'w')
            fh.write ( new_content )
            fh.close()

        except IOError:
            print "Error opening the output file"
            
    return new_content

if __name__ == '__main__':
    
    parser = optparse.OptionParser(usage='%prog [options] [argument]', version='%prog version 0.1')
    parser.add_option('-i', '--input', dest='source', metavar="SOURCE", help="Input file to be processed")
    parser.add_option('-o', '--output', dest='output', metavar="OUTPUT", help="Output file")

    parser.add_option('--c2d', action="store_true", default=False, dest='c2d', help="Coordinates to distance traveled")
    parser.add_option('--c2b', action="store_true", default=False, dest='c2b', help="Coordinates to virtual beam splitting")
    
    (options, args) = parser.parse_args()

    if not options.source and not (options.c2d or options.c2b):
        parser.print_help()    
        
    input_file = options.source
    
    if input_file and not options.output:
        path_filename, extension = os.path.splitext(input_file)
        output_file = path_filename + '-converted' + extension
    else:
        output_file = options.output
 
    if input_file and options.c2d:
        c2d(input_file, output_file)

    if input_file and options.c2b:
        c2b(input_file, output_file)
        

