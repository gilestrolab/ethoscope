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

HEADER_LENGTH=8

def CoordsFromFile(filename):
    """
    Reads coordinates from a result file
    Returns a 3 dimensional array of shape ( frames, flies, (x,y) )
    """
    coords = []
    try:
        fh = open(filename, 'r')
        rawfile = fh.read().split('\n')
        fh.close()

        for line in rawfile:
            if line:
                coords.append( [xy.split(',') for xy in line.split('\t')[HEADER_LENGTH:] ] )

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
                counts.append( line.split('\t')[HEADER_LENGTH:] )


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

def getMidlines(filename=None, orientation=None):
    """
    FIX THIS
    """
    return np.array([130,]*10).reshape(10,1)


def compressArray(a, resolution=60):
    """
    This is used to compress an array having data in seconds
    to an array summing each 60 seconds into one minute
    """
    frames, flies, d = a.shape
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


def CoordsToBeamCrossings(coords, orientation='V'):
    """
    Transform an array containing coordinates to a beam crossing count
    coords should be a numpy array of shape ( frames, flies, (x,y) )
    
    orientation     H   Horizontal, use X value to check crossing
                    V   Vertical    use Y value to check crossing
    """
   
    md = getMidlines(orientation)
    
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
                headers.append( line.split('\t')[:HEADER_LENGTH] )

        
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

    trackType = lastline.split('\t')[position]
    
    return int(trackType)
    
#Conversion front-ends  

def c2b(file_in, file_out, extend=True):
    """
    """
    data =  CoordsFromFile(file_in)
    dist = CoordsToBeamCrossings(data)
    
    headers = getHeaders(file_in)
    
    flies = dist.shape[1]
    
    if extend and flies < 32:
        extension = '\t' + '\t'.join(['0',] * (32-flies) )
    else:
        extension = ''
    
    try:
        fh = open(file_out, 'w')

        for h, c in zip ( headers[::60], dist):
            fh.write (
                         '\t'.join(h) +
                         '\t0\t0\t' +
                         '\t'.join( [str(xy)[1:-1] for xy in c.tolist()] ) +
                         extension +
                         '\n'
                       )
        fh.close()

    except IOError:
        print "Error opening the output file"

    
   
def c2d(file_in, file_out, extend=True):
    """
    """
    data =  CoordsFromFile(file_in)
    dist = CoordsToDistance(data)
    
    headers = getHeaders(file_in)
    
    flies = dist.shape[1]
    
    if extend and flies < 32:
        extension = '\t' + '\t'.join(['0',] * (32-flies) )
    else:
        extension = ''
    
    try:
        fh = open(file_out, 'w')

        for h, c in zip ( headers[::60], dist):
            fh.write (
                         '\t'.join(h) +
                         '\t0\t0\t' +
                         '\t'.join( [str(xy)[1:-1] for xy in c.tolist()] ) +
                         extension +
                         '\n'
                       )
        fh.close()

    except IOError:
        print "Error opening the output file"

if __name__ == '__main__':
    
 
    ctrl = '/home/gg/Dropbox/Work/Projects/Sandflies/raw/11.08.25/Monitor001.txt'
    caff = '/home/gg/Dropbox/Work/Projects/Sandflies/raw/11.08.25/Monitor002.txt'
    
    c2d (caff, '/home/gg/Dropbox/Work/Projects/Sandflies/converted/new/Monitor002.txt')
    

