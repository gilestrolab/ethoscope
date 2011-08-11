# -*- coding: utf-8 -*-
#
#       pvg.py pysolovideogui
#       
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
"""Version 1.2

Interaction with webcam:                opencv      liveShow.py / imageAquisition.py
Saving movies as stream:                opencv      realCam
Saving movies as single files:          ?           realCam
Opening movies as avi:                  opencv      virtualCamMovie
Opening movies as sequence of files:    PIL         virtualCamFrames

Each Monitor has a camera that can be: realCam || VirtualCamMovies || VirtualCamFrames
The class monitor is handling the motion detection and data processing while the CAM only handle
IO of image sources

Algorithm for motion analysis:          PIL through kmeans (vector quantization)
    http://en.wikipedia.org/wiki/Vector_quantization
    http://stackoverflow.com/questions/3923906/kmeans-in-opencv-python-interface
"""

import cv
from math import sqrt
import os, sys, datetime, time
import numpy as np
import cPickle

pySoloVideoVersion ='0.8-master-git'

def getCameraCount():
    """
    FIX THIS
    """
    n = 0
    Cameras = True
    
    while Cameras:
        try:
            print ( cv.CaptureFromCAM(n) )
            n += 1
        except:
            Cameras = False
    return n

class Cam:
    """
    Functions and properties inherited by all cams
    """
    
    def __addText__(self, frame, text = None):
        """
        Add current time as stamp to the image
        """

        if not text: text = time.asctime(time.localtime(time.time()))

        normalfont = cv.InitFont(cv.CV_FONT_HERSHEY_PLAIN, 1, 1, 0, 1, 8)
        boldfont = cv.InitFont(cv.CV_FONT_HERSHEY_SIMPLEX, 1, 1, 0, 3, 8)
        font = normalfont
        textcolor = (255,255,255)

        (x1, _), ymin = cv.GetTextSize(text, font)
        width, height = frame.width, frame.height
        x = width - x1 - (width/64)
        y = height - ymin - 2

        cv.PutText(frame, text, (x, y), font, textcolor)
        
        return frame

    def getResolution(self):
        """
        Returns frame resolution as tuple (w,h)
        """
        return self.resolution      
        
    def saveSnapshot(self, filename, quality=90, timestamp=False):
        """
        """
        img = self.getImage(timestamp, imgType)
        cv.SaveImage(filename, img) #with opencv



        
class realCam(Cam):
    """
    a realCam class will handle a webcam connected to the system
    camera is handled through opencv and images can be transformed to PIL
    """
    def __init__(self, devnum=0, showVideoWindow=False, resolution=(640,480)):
        self.scale = False
        self.resolution = resolution
        self.camera = cv.CaptureFromCAM(devnum)
        self.setResolution (*resolution)

    def getFrameTime(self):
        """
        """
        return time.time() #current time epoch in secs.ms

    def addTimeStamp(self, img):
        """
        """
        return self.__addText__(img)

    def setResolution(self, x, y):
        """
        Set resolution of the camera we are acquiring from
        """
        x = int(x); y = int(y)
        self.resolution = (x, y)
        cv.SetCaptureProperty(self.camera, cv.CV_CAP_PROP_FRAME_WIDTH, x)
        cv.SetCaptureProperty(self.camera, cv.CV_CAP_PROP_FRAME_HEIGHT, y)
        x1, y1 = self.getResolution()
        self.scale = ( (x, y) != (x1, y1) ) # if the camera does not support resolution, we need to scale the image
        
    def getResolution(self):
        """
        Return real resolution
        """
        x1 = cv.GetCaptureProperty(self.camera, cv.CV_CAP_PROP_FRAME_WIDTH)
        y1 = cv.GetCaptureProperty(self.camera, cv.CV_CAP_PROP_FRAME_HEIGHT)
        return (int(x1), int(y1))
        

    def getImage( self, timestamp=False):
        """
        Returns frame
        
        timestamp   False   (Default) Does not add timestamp
                    True              Add timestamp to the image
                    
        """        
        frame = cv.QueryFrame(self.camera)

        if self.scale:
            newsize = cv.CreateImage(self.resolution , cv.IPL_DEPTH_8U, 3)
            cv.Resize(frame, newsize)
            frame = newsize
        
        if timestamp: frame = self.__addText__(frame)
        
        return frame

    def isLastFrame(self):
        """
        Added for compatibility with other cams
        """
        return False

class virtualCamMovie(Cam):
    """
    A Virtual cam to be used to pick images from a movie (avi, mov) rather than a real webcam
    Images are handled through opencv
    """
    def __init__(self, path, step = None, start = None, end = None, loop=False, resolution=None):
        """
        Specifies some of the parameters for working with the movie:
        
            path        the path to the file
            
            step        distance between frames. If None, set 1
            
            start       start at frame. If None, starts at first
            
            end         end at frame. If None, ends at last
            
            loop        False   (Default)   Does not playback movie in a loop
                        True                Playback in a loop
        
        """
        self.path = path
        
        if start < 0: start = 0
        self.start = start or 0
        self.currentFrame = self.start

        self.step = step or 1
        if self.step < 1: self.step = 1
        
        self.loop = loop

        self.capture = cv.CaptureFromFile(self.path)

        #finding the input resolution
        w = cv.GetCaptureProperty(self.capture, cv.CV_CAP_PROP_FRAME_WIDTH)
        h = cv.GetCaptureProperty(self.capture, cv.CV_CAP_PROP_FRAME_HEIGHT)
        self.in_resolution = (int(w), int(h))
        self.resolution = self.in_resolution

        # setting the output resolution
        self.setResolution(*resolution)

        self.totalFrames = self.getTotalFrames()
        if end < 1 or end > self.totalFrames: end = self.totalFrames
        self.lastFrame = end
       
        self.blackFrame = cv.CreateImage(self.resolution , cv.IPL_DEPTH_8U, 3)
        cv.Zero(self.blackFrame)
        
    def getFrameTime(self, asString=None):
        """
        Return the time of the frame
        """
        
        frameTime = cv.GetCaptureProperty(self.capture, cv.CV_CAP_PROP_POS_MSEC)

        
        if asString:
            frameTime = str( datetime.timedelta(seconds=frameTime / 100.0) )
            return '%s - %s/%s' % (frameTime, self.currentFrame, self.totalFrames) #time.asctime(time.localtime(fileTime))
        else:
            return frameTime / 1000.0 #returning seconds compatibility reasons
    
    def getImage(self, timestamp=False):
        """
        Returns frame
        
        timestamp   False   (Default) Does not add timestamp
                    True              Add timestamp to the image
                    
        """

        #cv.SetCaptureProperty(self.capture, cv.CV_CAP_PROP_POS_FRAMES, self.currentFrame)
        # this does not work properly. Image is very corrupted
        im = cv.QueryFrame(self.capture)

        if not im: im = self.blackFrame
        
        self.currentFrame += self.step
            
        #elif self.currentFrame > self.lastFrame and not self.loop: return False

        if self.scale:
            newsize = cv.CreateImage(self.resolution , cv.IPL_DEPTH_8U, 3)
            cv.Resize(im, newsize)
            im = newsize

        if timestamp:
            text = self.getFrameTime(asString=True)
            im = self.__addText__(im, text)

        return im
      
    def setResolution(self, w, h):
        """
        Changes the output resolution
        """
        self.resolution = (w, h)
        self.scale = (self.resolution != self.in_resolution)
    
    def getTotalFrames(self):
        """
        Returns total number of frames
        Be aware of this bug
        https://code.ros.org/trac/opencv/ticket/851
        """
        return cv.GetCaptureProperty( self.capture , cv.CV_CAP_PROP_FRAME_COUNT )

    def isLastFrame(self):
        """
        Are we processing the last frame in the movie?
        """

        if ( self.currentFrame > self.totalFrames ) and not self.loop:
            return True
        elif ( self.currentFrame == self.totalFrames ) and self.loop:
            self.currentFrame = self.start
            return False
        else:
            return False


class virtualCamFrames(Cam):
    """
    A Virtual cam to be used to pick images from a folder rather than a webcam
    Images are handled through PIL
    """
    def __init__(self, path, step = None, start = None, end = None, loop = False):
        self.path = path
        self.fileList = self.__populateList__(start, end, step)
        self.totalFrames = len(self.fileList)

        self.currentFrame = 0
        self.last_time = None
        self.loop = False

        fp = os.path.join(self.path, self.fileList[0])

        self.resolution = Image.open(fp).size
        
        self.normalfont = cv.InitFont(cv.CV_FONT_HERSHEY_SIMPLEX, 1, 1, 0, 1, 8)
        self.boldfont = cv.InitFont(cv.CV_FONT_HERSHEY_SIMPLEX, 1, 1, 0, 3, 8)
        self.font = None

    def getFrameTime(self, fname):
        """
        Return the time of most recent content modification of the file fname
        """
        if fname and asString:
            fileTime = os.stat(fname)[-2]
            return time.asctime(time.localtime(fileTime))
        elif fname and not asString:
            fileTime = os.stat(fname)[-2]
            return time.localtime(fileTime)
        else:
            return self.last_time
            
    def __populateList__(self, start, end, step):
        """
        Populate the file list
        """
        
        fileList = []
        fileListTmp = os.listdir(self.path)

        for fileName in fileListTmp:
            if '.tif' in fileName or '.jpg' in fileName:
                fileList.append(fileName)

        fileList.sort()
        return fileList[start:end:step]


    def getImage(self, timestamp=False):
        """
        Returns frame
        
        timestamp   False   (Default) Does not add timestamp
                    True              Add timestamp to the image
        """
        n = self.currentFrame
        fp = os.path.join(self.path, self.fileList[n])

        self.currentFrame += 1

        try:
            im = cv.LoadImage(fp) #using cv to open the file
            
        except:
            print ( 'error with image %s' % fp )
            raise

        if self.scale:
            newsize = cv.CreateMat(self.out_resolution[0], self.out_resolution[1], cv.CV_8UC3)
            cv.Resize(im, newsize)

        self.last_time = self.getFileTime(fp)
    
        if timestamp:
            im = self.__addText__(im, self.last_time)
        
        return im
    
    def getTotalFrames(self):
        """
        Return the total number of frames
        """
        return self.totalFrames
        
    def isLastFrame(self):
        """
        Are we processing the last frame in the folder?
        """

        if (self.currentFrame == self.totalFrames) and not self.loop:
            return True
        elif (self.currentFrame == self.totalFrames) and self.loop:
            self.currentFrame = 0
            return False
        else:
            return False        

    def setResolution(self, w, h):
        """
        Changes the output resolution
        """
        self.resolution = (w, h)
        self.scale = (self.resolution != self.in_resolution)

    def compressAllImages(self, compression=90, resolution=(960,720)):
        """
        FIX THIS: is this needed?
        Load all images one by one and save them in a new folder 
        """
        x,y = resolution[0], resolution[1]
        if self.isVirtualCam:
            in_path = self.cam.path
            out_path = os.path.join(in_path, 'compressed_%sx%s_%02d' % (x, y, compression))
            os.mkdir(out_path)
            
            for img in self.cam.fileList:
                f_in = os.path.join(in_path, img)
                im = Image.open(f_in)
                if im.size != resolution: 
                    im = im.resize(resolution, Image.ANTIALIAS)
                
                f_out = os.path.join(out_path, img)
                im.save (f_out, quality=compression)

            return True    

        else:
            return False

class Arena():
    """
    The arena define the space where the flies move
    Carries information about the ROI (coordinates defining each vial) and
    the number of flies in each vial
    """
    def __init__(self):
        
        self.ROIS = []
        self.beams = []
        self.trackType = 1
        
        self.period = 60 #in seconds
        self.rowline = 0
        
        self.points_to_track = []
        self.flyDataBuffer = []
        self.flyDataMin = []
        
        self.count_seconds = 0
        
        self.fa = np.zeros( (self.period, 2), np.float )
        self.outputFile = None
        
    def __ROItoRect(self, coords):
        """
        Used internally
        Converts a ROI (a tuple of four points coordinates) into
        a Rect (a tuple of two points coordinates)
        """
        (x1, y1), (x2, y2), (x3, y3), (x4, y4) = coords
        lx = min([x1,x2,x3,x4])
        rx = max([x1,x2,x3,x4])
        uy = min([y1,y2,y3,y4])
        ly = max([y1,y2,y3,y4])
        return ( (lx,uy), (rx, ly) )
        
    
    def __getMidline (self, coords):
        """
           Return the position of each ROI's midline
        """
        (pt1, pt2) = self.__ROItoRect(coords)
        return (pt2[0] - pt1[0])/2
    
    def addROI(self, coords, n_flies):
        """
        Add a new ROI to the arena
        """
        self.ROIS.append( coords )
        self.beams.append ( self.__getMidline (coords)  ) 
        self.points_to_track.append(n_flies)
        self.flyDataBuffer.append( [(0,0)] )
        self.flyDataMin.append ( self.fa )

    def getROI(self, n):
        """
        Returns the coordinates of the nth crop area
        """
        if n > len(self.ROIS):
            coords = []
        else:
            coords = self.ROIS[n]
        return coords
        
    def delROI(self, n):
        """
        removes the nth crop area from the list
        if n -1, remove all
        """
        if n >= 0:
            self.ROIS.pop(n)
            self.points_to_track.pop(n)
            self.flyDataBuffer.pop(n)
            self.flyDataMin.pop(n)
        elif n < 0:
            self.ROIS = []
        
    def saveROIS(self, filename):
        """
        Save the current crop data to a file
        """
        cf = open(filename, 'w')
        cPickle.dump(self.ROIS, cf)
        cPickle.dump(self.points_to_track, cf)

        cf.close()
        
    def loadROIS(self, filename):
        """
        Load the crop data from a file
        """
        try:
            cf = open(filename, 'r')
            self.ROIS = cPickle.load(cf)
            self.points_to_track = cPickle.load(cf)
            cf.close()

            for coords in self.ROIS:
                self.flyDataBuffer.append( [(0,0)] )
                self.flyDataMin.append ( self.fa.copy() )
                self.beams.append ( self.__getMidline (coords)  ) 
                
            return True
        except:
            return False

    def resizeROIS(self, origSize, newSize):
        """
        Resize the mask to new size so that it would properly fit
        resized images
        """
        newROIS = []
        
        ox, oy = origSize
        nx, ny = newSize
        xp = float(ox) / nx
        yp = float(oy) / ny
        
        for ROI in self.ROIS:
            nROI = []
            for pt in ROI:
                nROI.append ( (pt[0]*xp, pt[1]*yp) )
            newROIS.append ( ROI )

        return newROIS


    def isPointInROI(self, pt):
        """
        Check if a given point falls whithin one of the ROI
        Returns the ROI number or else returns -1
        """
        x, y = pt
        
        for ROI in self.ROIS:
            (x1, y1), (x2, y2), (x3, y3), (x4, y4) = ROI
            lx = min([x1,x2,x3,x4])
            rx = max([x1,x2,x3,x4])
            uy = min([y1,y2,y3,y4])
            ly = max([y1,y2,y3,y4])
            if (lx < x < rx) and ( uy < y < ly ):
                return self.ROIS.index(ROI)
        
        return -1


    def ROIStoRect(self):
        """
        translate ROI (list containing for points a tuples)
        into Rect (list containing two points as tuples)
        """
        newROIS = []
        for ROI in self.ROIS:
            newROIS. append ( self.__ROItoRect(ROI) )
            
        return newROIS

    def addFlyCoords(self, count, fly):
        """
        Add the provided coordinates to the existing list
        count   int     the fly number in the arena 
        fly     (x,y)   the coordinates to add 
        """
        max_distance=200
        
        if fly:
            #calculate distance from previous point
            pf = self.flyDataBuffer[count][-1]
            d = np.sqrt ( (fly[0] - pf[0])**2 + (fly[1]-pf[1])**2 )
            #exclude too wide movements unless it's the first movement the fly makes
            if d > max_distance and pf != (0,0): fly = self.flyDataBuffer[count][-1]
            
            self.flyDataBuffer[count].append ( fly )
        else:
            
            fly = self.flyDataBuffer[count][-1]
            self.flyDataBuffer[count].append ( fly )
    
        return fly
        
    def compactSeconds(self):
        """
        Compact the frames collected in the last second
        by averaging the value of the coordinates
        FIX THIS: this function is probably not needed
        """
       
        if self.count_seconds == self.period:
            self.writeActivity()
            self.count_seconds = 0
            
        for c, f in enumerate(self.flyDataBuffer):
            a = np.array(f)
            a = a[a.nonzero()[0]]
            
            m = a.mean(0); m = m[~np.isnan(m)]
            if not m.size: m = [0,0]
            
            self.flyDataMin[c][self.count_seconds] = m

            self.flyDataBuffer[c] = [self.flyDataBuffer[c][-1]]
        
        self.count_seconds += 1

    def writeActivity(self):
        """
        Write the activity to file
        Kind of motion depends on user settings
        """
        year, month, day, hh, mn, sec = time.localtime()[0:6]
        date = '%02d %02d %s' % (day,month,str(year)[-2:])
        tt = '%02d:%02d:%02d' % (hh, mn, sec)
        active = '1'
        zeros = '0\t0\t0\t0'
        
        activity = []
        row = ''


        if self.trackType == 1:
            activity = [self.calculateDistances(),]
        
        elif self.trackType == 0:
            activity = [self.calculateVBM(),]
        
        elif self.trackType == 2:
            activity = self.calculatePosition()
            
        for line in activity:
            self.rowline +=1 
            row_header = '%s\t'*5 % (self.rowline, date, tt, active, zeros)
            row += row_header + line + '\n'

        if self.outputFile:
            fh = open(self.outputFile, 'a')
            fh.write(row)
            fh.close()
            
    
    def calculateDistances(self):
        """
        Motion is calculated as distance in px per minutes
        """
        
        values = []
        for fd in self.flyDataMin:

            fs = np.roll(fd, -1, 0)
            
            x = fd[:,:1]; y = fd[:,1:]
            x1 = fs[:,:1]; y1 = fs[:,1:]
            
            d = np.sqrt ( (x1-x)**2 + (y1-y)**2 )

            d = d[~np.isnan(d)]; d = d[~np.isinf(d)]
            
            values. append ( d[:-1].sum() )

        activity = '\t'.join( [str(v) for v in values] )
        return activity
            
            
    def calculateVBM(self):
        """
        Motion is calculated as virtual beam crossing
        """

        values = []

        for fd, md in zip(self.flyDataMin, self.beams):
            
            fs = np.roll(fd, -1, 0)
            
            x = fd[:,:1]
            x1 = fs[:,:1]
        
            crossed = (x < md ) * ( md < x1) + (x > md) * (md > x1)
            values .append ( crossed.sum() )
        
        activity = '\t'.join( [str(v) for v in values] )
        return activity
            
    def calculatePosition(self, resolution=1):
        """
        Simply write out position of the fly at every time interval, as 
        decided by "resolution" (seconds)
        """
        
        activity = []

        a = np.array( self.flyDataMin ) #( n_flies, interval, (x,y) )
        a = a.transpose(1,0,2) # ( interval, n_flies, (x,y) )
        
        a = a.reshape(resolution, -1, 32, 2).mean(0)
        
        for fd in a:
            onerow = '\t'.join( ['%s,%s' % (x,y) for (x,y) in fd] )
            activity.append(onerow)
        
        return activity
    
class Monitor(object):
    """
        The main monitor class
    """

    def __init__(self):

        """
        A Monitor contains a cam, which can be either virtual or real.
        Real CAMs are handled through opencv, frames through PIL.
        """
        self.grabMovie = False
        self.arena = Arena()
        
        self.imageCount = 0
        self.lasttime = 0

        self.maxTick = 60
        
        self.firstFrame = True
        self.tracking = True
        


    def __drawROI(self, img, ROI, color=None):
        """
        Draw ROI on img using given coordinates
        ROI is a tuple of 4 tuples ( (x1, y1), (x2, y2), (x3, y3), (x4, y4) )
        and does not have to be necessarily a rectangle
        """

        if not color: color = (255,255,255)
        width = 1
        line_type = cv.CV_AA


        cv.Line(img, ROI[0], ROI[1], color, width, line_type, 0)
        cv.Line(img, ROI[1], ROI[2], color, width, line_type, 0)
        cv.Line(img, ROI[2], ROI[3], color, width, line_type, 0)
        cv.Line(img, ROI[3], ROI[0], color, width, line_type, 0)

        return img

    def __drawCross(self, img, pt, color=None):
        """
        Draw a cross around a point pt
        """
        if not color: color = (255,255,255)
        width = 1
        line_type = cv.CV_AA
        
        x, y = pt
        a = (x, y-5)
        b = (x, y+5)
        c = (x-5, y)
        d = (x+5, y)
        
        cv.Line(img, a, b, color, width, line_type, 0)
        cv.Line(img, c, d, color, width, line_type, 0)
        
        return img
        

    def __getChannel(self, img, channel='R'):
        """
        Return only the asked channel R,G or B
        """

        cn = 'RGB'.find( channel.upper() )
        
        channels = [None, None, None]
        cv.Split(img, channels[0], channels[1], channels[2], None)
        return channels[cn]

    def __distance(self, x1, y1, x2, y2):
        """
        Calculate the distance between two cartesian points
        """
        return sqrt((x2-x1)**2 + (y2-y1)**2)

    def __angle(self, pt1, pt2, pt0):
        """
        Return the angle between three points
        """
        dx1 = pt1[0] - pt0[0]
        dy1 = pt1[1] - pt0[1]
        dx2 = pt2[0] - pt0[0]
        dy2 = pt2[1] - pt0[1]
        return (dx1*dx2 + dy1*dy2)/sqrt((dx1*dx1 + dy1*dy1)*(dx2*dx2 + dy2*dy2) + 1e-10)

    def CaptureFromCAM(self, devnum=0, resolution=(640,480), options=None):
        """
        """
        self.resolution = resolution
        self.isVirtualCam = False
        self.cam = realCam(devnum=devnum)
        self.cam.setResolution(*resolution)
        self.resolution = self.cam.getResolution()
        self.numberOfFrames = 0
        
    def CaptureFromMovie(self, camera, resolution=None, options=None):
        """
        """
        self.isVirtualCam = True
        
        if options:
            step = options['step']
            start = options['start']
            end = options['end']
            loop = options['loop']

        self.cam = virtualCamMovie(path=camera, resolution = resolution)
        self.resolution = self.cam.getResolution()
        self.numberOfFrames = self.cam.getTotalFrames()
        
    def CaptureFromFrames(self, camera, resolution=None, options=None):
        """
        """
         
        if options:
            step = options['step']
            start = options['start']
            end = options['end']
            loop = options['loop'] 
         
        self.isVirtualCam = True
        self.cam = virtualCamFrame(path = camera, resolution = resolution)
        self.resolution = self.cam.getResolution()
        self.numberOfFrames = self.cam.getTotalFrames()
    
    def setSource(self, camera, resolution, options=None):
        """
        Set source intelligently
        """
        if type(camera) == type(0): 
            self.CaptureFromCAM(camera, resolution, options)
        elif os.path.isfile(camera):
            self.CaptureFromMovie(camera, resolution, options)
        elif os.path.isdir(camera):
            self.CaptureFromFrames(camera, resolution, options)

    def setTracking(self, track, trackType, mask_file, outputFile):
        """
        Set the tracking parameters
        
        track       Boolean     Do we do tracking of flies?
        trackType   0           tracking using the virtual beam method
                    1 (Default) tracking calculating distance moved
        mask_file   text        the file used to load and store masks
        outputFile  text        the txt file where results will be saved
        """

        self.track = track
        self.arena.trackType = int(trackType)
        self.mask_file = mask_file
        self.arena.outputFile = outputFile
        
        if mask_file:
            self.loadROIS(mask_file)

        
    def getFrameTime(self):
        """
        """
        return self.cam.getFrameTime()
    
    def isLastFrame(self):
        """
        Proxy to isLastFrame()
        Handled by camera
        """
        return self.cam.isLastFrame()


    def saveMovie(self, filename, fps=24, codec='FMP4', startOnKey=False):
        """
        Determines whether all the frames grabbed through getImage will also 
        be saved as movie.
        
        filename                           the full path to the file to be written
        fps             24   (Default)     number of frames per second
        codec           FMP4 (Default)     codec to be used
        
        http://stackoverflow.com/questions/5426637/writing-video-with-opencv-python-mac
        """
        fourcc = cv.CV_FOURCC(*[c for c in codec])
        
        self.writer = cv.CreateVideoWriter(filename, fourcc, fps, self.resolution, 1)
        self.grabMovie = not startOnKey


    def saveSnapshot(self, *args, **kwargs):
        """
        proxy to saveSnapshot
        """
        self.cam.saveSnapshot(*args, **kwargs)
    
    def SetLoop(self,loop):
        """
        Set Loop on or off.
        Will work only in virtual cam mode and not realCam
        Return current loopmode
        """
        if self.isVirtualCam:
            self.cam.loop = loop
            return self.cam.loop
        else:
            return False
   
    def processFlyMovements(self):
        """
        """
        
        ct = self.getFrameTime()
        
        if ( ct - self.lasttime) > 1: # if one second has elapsed
            self.lasttime = ct
            self.arena.compactSeconds() #average the coordinates and transfer from buffer to array
                

    def addROI(self, coords, n_flies=1):
        """
        Add the coords for a new ROI and the number of flies we want to track in that area
        selection       (pt1, pt2, pt3, pt4)    A four point selection
        n_flies         1    (Default)      Number of flies to be tracked in that area
        """
        
        self.arena.addROI(coords, n_flies)

    def getROI(self, n):
        """
        Returns the coordinates of the nth crop area
        """
        return self.arena.getROI(n)

    def delROI(self, n):
        """
        removes the nth crop area from the list
        if n -1, remove all
        """
        self.arena.delROI(n)
        
    def saveROIS(self, filename=None):
        """
        Save the current crop data to a file
        """
        if not filename: filename = self.mask_file
        self.arena.saveROIS(filename)
        
    def loadROIS(self, filename=None):
        """
        Load the crop data from a file
        """
        if not filename: filename = self.mask_file
        return self.arena.loadROIS(filename)

    def resizeROIS(self, origSize, newSize):
        """
        Resize the mask to new size so that it would properly fit
        resized images
        """
        return self.arena.resizeROIS(origSize, newSize)

    def isPointInROI(self, pt):
        """
        Check if a given point falls whithin one of the ROI
        Returns the ROI number or else returns -1
        """
        return self.arena.isPointInROI(pt)

    def autoMask(self, pt1, pt2):
        """
        EXPERIMENTAL, FIX THIS
        This is experimental
        For now it works only with one kind of arena
        """
        rows = 16
        cols = 2
        food = .10
        vials = rows * cols
        ROI = [None,] * vials
        
        (x, y), (x1, y1) = pt1, pt2
        w, h = (x1-x), (y1-y)

        d = h / rows
        l = (w / cols) - int(food/2*w)
        
        k = 0
        for v in range(rows):
            ROI[k] = (x, y), (x+l, y+d)
            ROI[k+1] = (x1-l, y) , (x1, y+d)
            k+=2
            y+=d
        
        nROI = []
        for R in ROI:
            (x, y), (x1, y1) = R
            self.arena.addROI( ( (x,y), (x,y1), (x1,y1), (x1,y) ), 1)
    
    def findOuterFrame(self, img, thresh=50):
        """
        EXPERIMENTAL
        Find the greater square 
        """
        N = 11
        sz = (img.width & -2, img.height & -2)
        storage = cv.CreateMemStorage(0)
        timg = cv.CloneImage(img)
        gray = cv.CreateImage(sz, 8, 1)
        pyr = cv.CreateImage((img.width/2, img.height/2), 8, 3)

        squares =[]
        # select the maximum ROI in the image
        # with the width and height divisible by 2
        subimage = cv.GetSubRect(timg, (0, 0, sz[0], sz[1]))

        # down-scale and upscale the image to filter out the noise
        cv.PyrDown(subimage, pyr, 7)
        cv.PyrUp(pyr, subimage, 7)
        tgray = cv.CreateImage(sz, 8, 1)
        # find squares in every color plane of the image
        for c in range(3):
            # extract the c-th color plane
            channels = [None, None, None]
            channels[c] = tgray
            cv.Split(subimage, channels[0], channels[1], channels[2], None) 
            for l in range(N):
                # hack: use Canny instead of zero threshold level.
                # Canny helps to catch squares with gradient shading
                if(l == 0):
                    cv.Canny(tgray, gray, 0, thresh, 5)
                    cv.Dilate(gray, gray, None, 1)
                else:
                    # apply threshold if l!=0:
                    #     tgray(x, y) = gray(x, y) < (l+1)*255/N ? 255 : 0
                    cv.Threshold(tgray, gray, (l+1)*255/N, 255, cv.CV_THRESH_BINARY)

                # find contours and store them all as a list
                contours = cv.FindContours(gray, storage, cv.CV_RETR_LIST, cv.CV_CHAIN_APPROX_SIMPLE)

                if not contours:
                    continue
                    
                contour = contours
                totalNumberOfContours = 0
                while(contour.h_next() != None):
                    totalNumberOfContours = totalNumberOfContours+1
                    contour = contour.h_next()
                # test each contour
                contour = contours
                #print 'total number of contours %d' % totalNumberOfContours
                contourNumber = 0

                while(contourNumber < totalNumberOfContours):
                    
                    #print 'contour #%d' % contourNumber
                    #print 'number of points in contour %d' % len(contour)
                    contourNumber = contourNumber+1
                    
                    # approximate contour with accuracy proportional
                    # to the contour perimeter
                    result = cv.ApproxPoly(contour, storage,
                        cv.CV_POLY_APPROX_DP, cv.ArcLength(contour) *0.02, 0)

                    # square contours should have 4 vertices after approximation
                    # relatively large area (to filter out noisy contours)
                    # and be convex.
                    # Note: absolute value of an area is used because
                    # area may be positive or negative - in accordance with the
                    # contour orientation
                    if(len(result) == 4 and 
                        abs(cv.ContourArea(result)) > 500 and 
                        cv.CheckContourConvexity(result)):
                        s = 0
                        for i in range(5):
                            # find minimum angle between joint
                            # edges (maximum of cosine)
                            if(i >= 2):
                                t = abs(self.__angle(result[i%4], result[i-2], result[i-1]))
                                if s<t:
                                    s=t
                        # if cosines of all angles are small
                        # (all angles are ~90 degree) then write quandrange
                        # vertices to resultant sequence
                        if(s < 0.3):
                            pt = [result[i] for i in range(4)]
                            squares.append(pt)
                            print ('current # of squares found %d' % len(squares))
                    contour = contour.h_next()
         
        return squares    
         
    def GetImage(self, drawROIs = False, selection=None, crosses=None, timestamp=False):
        """
        GetImage(self, drawROIs = False, selection=None, timestamp=0)
        
        drawROIs       False        (Default)   Will draw all ROIs to the image
                       True        
        
        selection      (x1,y1,x2,y2)            A four point selection to be drawn
        
        crosses        (x,y),(x1,y1)            A list of tuples containing single point coordinates
        
        timestamp      True                     Will add a timestamp to the bottom right corner
                       False        (Default)   
        
        Returns the last collected image
        """

        self.imageCount += 1
        frame = self.cam.getImage(timestamp)

        if self.tracking: frame = self.doTrack(frame)
                
        if drawROIs and self.arena.ROIS:
            for ROI in self.arena.ROIS:
                frame = self.__drawROI(frame, ROI)

        if selection:
            frame = self.__drawROI(frame, selection, color=(0,0,255))
            
        if crosses:
            for pt in crosses:
                frame = self.__drawCross (frame, pt, color=(0,0,255))

        if self.grabMovie: cv.WriteFrame(self.writer, frame)
        
        return frame

    def doTrack(self, frame):
        """
        Track flies in ROIS using findContour algorhytm or opencv
        Each frame is compared against the moving average
        """

        grey_image = cv.CreateImage(cv.GetSize(frame), cv.IPL_DEPTH_8U, 1)
        temp = cv.CloneImage(frame)
        difference = cv.CloneImage(frame)

        # Smooth to get rid of false positives
        cv.Smooth(frame, frame, cv.CV_GAUSSIAN, 3, 0)

        if self.firstFrame:
            self.moving_average = cv.CreateImage(cv.GetSize(frame), cv.IPL_DEPTH_32F, 3)
            cv.ConvertScale(frame, self.moving_average, 1.0, 0.0)
            self.firstFrame = False
        else:
            cv.RunningAvg(frame, self.moving_average, 0.08, None) #0.040
            
            
        # Convert the scale of the moving average.
        cv.ConvertScale(self.moving_average, temp, 1.0, 0.0)

        # Minus the current frame from the moving average.
        cv.AbsDiff(frame, temp, difference)

        # Convert the image to grayscale.
        cv.CvtColor(difference, grey_image, cv.CV_RGB2GRAY)

        # Convert the image to black and white.
        cv.Threshold(grey_image, grey_image, 20, 255, cv.CV_THRESH_BINARY)

        # Dilate and erode to get proper blobs
        cv.Dilate(grey_image, grey_image, None, 2) #18
        cv.Erode(grey_image, grey_image, None, 2) #10

        storage = cv.CreateMemStorage(0)
        
        for fly_number, ROI in enumerate(self.arena.ROIStoRect()):
            (x1,y1), (x2,y2) = ROI
            cv.SetImageROI(grey_image, (x1,y1,x2-x1,y2-y1))
            cv.SetImageROI(frame, (x1,y1,x2-x1,y2-y1))
            
            # Calculate movements
            
            contour = cv.FindContours(grey_image, storage, cv.CV_RETR_CCOMP, cv.CV_CHAIN_APPROX_SIMPLE)

            points = []
            fly_coords = None
            while contour:
                # Draw rectangles
                bound_rect = cv.BoundingRect(list(contour))
                contour = contour.h_next()
                if not contour: # this will make sure we are tracking only the biggest rectangle
                    pt1 = (bound_rect[0], bound_rect[1])
                    pt2 = (bound_rect[0] + bound_rect[2], bound_rect[1] + bound_rect[3])
                    points.append(pt1)
                    points.append(pt2)
                    cv.Rectangle(frame, pt1, pt2, cv.CV_RGB(255,0,0), 1)
                    
                    fly_coords = ( pt1[0]+(pt2[0]-pt1[0])/2, pt1[1]+(pt2[1]-pt1[1])/2 )
                    area = (pt2[0]-pt1[0])*(pt2[1]-pt1[1])
                    if area > 400: fly_coords = None
                    #frame = self.__drawCross(frame, fly_coords)

            fly_coords = self.arena.addFlyCoords(fly_number, fly_coords) # for each frame adds fly coordinates to all ROIS
            self.__drawCross(frame, fly_coords)
            
            cv.ResetImageROI(grey_image)
            cv.ResetImageROI(frame)

            #cv.Rectangle(frame, ROI[0], ROI[1], cv.CV_RGB(0,255,0), 1)

        self.processFlyMovements()
        
        return frame



