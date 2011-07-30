#!/usr/bin/env python

'''
Version 1.2

Interaction with webcam:                opencv      liveShow.py / imageAquisition.py
Saving movies as stream:                opencv      realCam
Saving movies as single files:          ?           realCam
Opening movies as avi:                  opencv      virtualCamMovie
Opening movies as sequence of files:    PIL         virtualCamFrames

Each Monitor has a camera that can be: realCam || VirtualCamMovies || VirtualCamFrames
The class monitor is handling the motion detection and data processing while the CAM only handle
IO of image sources

Algorithm for motion analysis:          PIL through kmeans (vector quantization)
#    http://en.wikipedia.org/wiki/Vector_quantization
#    http://stackoverflow.com/questions/3923906/kmeans-in-opencv-python-interface
'''

import cv
from math import sqrt
import os, sys, datetime, time

import cPickle

#TODO: FIX THINGS
#FIX the way crops are handled (it's ugly and it's not elegant) see camshift.py 

def getCameraCount():
    '''
    FIX THIS
    '''
    n = 0
    Cameras = True
    
    while Cameras:
        try:
            print cv.CaptureFromCAM(n)
            n += 1
        except:
            Cameras = False
    return n

class Cam:
    '''
    shared by all cams
    '''
    
    def __addText__(self, img, text = None):
        '''
        Add current time as stamp to the image
        '''

        normalfont = cv.InitFont(cv.CV_FONT_HERSHEY_SIMPLEX, 1, 1, 0, 1, 8)
        boldfont = cv.InitFont(cv.CV_FONT_HERSHEY_SIMPLEX, 1, 1, 0, 3, 8)
        font = normalfont

        width, height = self.resolution
        x = 10
        y = height - 15
        textcolor = 0xffffff
        
        if not text: text = time.asctime(time.localtime(time.time()))

        cv.PutText(im, text, (x, y), font, textcolor)
        
        return im

    def getResolution(self):
        '''
        Returns frame resolution as tuple (w,h)
        '''
        return self.resolution      
        
    def saveSnapshot(self, filename, quality=90, timestamp=False):
        '''
        '''
        img = self.getImage(timestamp, imgType)
        cv.SaveImage(filename, img) #with opencv



        
class realCam(Cam):
    '''
    a realCam class will handle a webcam connected to the system
    camera is handled through opencv and images can be transformed to PIL
    '''
    def __init__(self, devnum=0, showVideoWindow=False, resolution=(640,480)):
        self.camera = cv.CaptureFromCAM(devnum)
        self.setResolution (*resolution)

    def addTimeStamp(self, img):
        '''
        '''
        return self.__addText__(img)

    def setResolution(self, x, y):
        '''
        Set resolution of the camera we are aquiring from
        '''
        x = int(x); y = int(y)
        self.resolution = (x, y)
        cv.SetCaptureProperty(self.camera, cv.CV_CAP_PROP_FRAME_WIDTH, x)
        cv.SetCaptureProperty(self.camera, cv.CV_CAP_PROP_FRAME_HEIGHT, y)

    def getImage( self, timestamp=False):
        '''
        Returns frame
        
        timestamp   False   (Default) Does not add timestamp
                    True              Add timestamp to the image
                    
        '''        
        frame = cv.QueryFrame(self.camera)
        if timestamp: frame = self.__addText__(frame)
        
        return frame

    def isLastFrame(self):
        '''
        Added for compatibility with other cams
        '''
        return False

class virtualCamMovie(Cam):
    '''
    A Virtual cam to be used to pick images from a movie (avi, mov) rather than a real webcam
    Images are handled through opencv
    '''
    def __init__(self, path, step = None, start = None, end = None, loop=False, resolution=None):
        '''
        Specifies some of the parameters for working with the movie:
        
            path        the path to the file
            
            step        distance between frames. If None, set 1
            
            start       start at frame. If None, starts at first
            
            end         end at frame. If None, ends at last
            
            loop        False   (Default)   Does not playback movie in a loop
                        True                Playback in a loop
        
        '''
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
        
    def __getFrameTime__(self):
        '''
        Return the time of the frame
        '''
        
        fileTime = cv.GetCaptureProperty(self.capture, cv.CV_CAP_PROP_POS_MSEC)
   
        return '%s - %s/%s' % (fileTime, self.currentFrame, self.totalFrames) #time.asctime(time.localtime(fileTime))

    
    def getImage(self, timestamp=False):
        '''
        Returns frame
        
        timestamp   False   (Default) Does not add timestamp
                    True              Add timestamp to the image
                    
        imgType     PIL               Return a PIL image
                    BMP               Return a BMP image (slowest)
                    CV      (Default) Return a CV native image (IPL)
        
        '''

        #cv.SetCaptureProperty(self.capture, cv.CV_CAP_PROP_POS_FRAMES, self.currentFrame) # this does not work properly. Image is very corrupted
        im = cv.QueryFrame(self.capture)

        if not im: im = self.blackFrame
        
        self.currentFrame += self.step
            
        #elif self.currentFrame > self.lastFrame and not self.loop: return False

        if self.scale:
            #newsize = cv.CreateMat(self.resolution[0], self.resolution[1], cv.CV_8UC3)
            newsize = cv.CreateImage(self.resolution , cv.IPL_DEPTH_8U, 3)
            cv.Resize(im, newsize)
            im = newsize

        if timestamp:
            text = self.__getFrameTime__()
            im = self.__addText__(im, text, imgType)

        return im

      
    def setResolution(self, w, h):
        '''
        Changes the output resolution
        '''
        self.resolution = (w, h)
        self.scale = (self.resolution != self.in_resolution)
    
    def getTotalFrames(self):
        '''
        Returns total number of frames
        Be aware of this bug
        https://code.ros.org/trac/opencv/ticket/851
        '''
        return cv.GetCaptureProperty( self.capture , cv.CV_CAP_PROP_FRAME_COUNT )

    def isLastFrame(self):
        '''
        Are we processing the last frame in the movie?
        '''

        if ( self.currentFrame > self.totalFrames ) and not self.loop:
            return True
        elif ( self.currentFrame == self.totalFrames ) and self.loop:
            self.currentFrame = self.start
            return False
        else:
            return False


class virtualCamFrames(Cam):
    '''
    A Virtual cam to be used to pick images from a folder rather than a webcam
    Images are handled through PIL
    '''
    def __init__(self, path, step = None, start = None, end = None, loop = False):
        self.path = path
        self.fileList = self.__populateList__(start, end, step)
        self.totalFrames = len(self.fileList)

        self.currentFrame = 0
        self.loop = False

        fp = os.path.join(self.path, self.fileList[0])

        self.resolution = Image.open(fp).size
        
        self.normalfont = cv.InitFont(cv.CV_FONT_HERSHEY_SIMPLEX, 1, 1, 0, 1, 8)
        self.boldfont = cv.InitFont(cv.CV_FONT_HERSHEY_SIMPLEX, 1, 1, 0, 3, 8)
        self.font = None

    def __getFileTime__(self, fname):
        '''
        Return the time of most recent content modification of the file fname
        '''
        fileTime = os.stat(fname)[-2]
        return time.asctime(time.localtime(fileTime))


    def __populateList__(self, start, end, step):
        '''
        Populate the file list
        '''
        
        fileList = []
        fileListTmp = os.listdir(self.path)

        for fileName in fileListTmp:
            if '.tif' in fileName or '.jpg' in fileName:
                fileList.append(fileName)

        fileList.sort()
        return fileList[start:end:step]


    def getImage(self, timestamp=False):
        '''
        Returns frame
        
        timestamp   False   (Default) Does not add timestamp
                    True              Add timestamp to the image
        '''
        n = self.currentFrame
        fp = os.path.join(self.path, self.fileList[n])

        self.currentFrame += 1

        try:
            im = cv.LoadImage(fp) #using cv to open the file
            
        except:
            print 'error with image %s' % fp
            raise

        if self.scale:
            newsize = cv.CreateMat(self.out_resolution[0], self.out_resolution[1], cv.CV_8UC3)
            cv.Resize(im, newsize)

        if timestamp:
            text = self.__getFileTime__(fp)
            im = self.__addText__(im, text, imgType)
        
        return im
    
    def GetAverageImage(self, n = 50):
        '''
        FIX THIS: using running average from open cv instead of PIL
        Return an image that is the average of n frames equally distanced from each other
        '''
        tot_frames = len( self.fileList)
        step = tot_frames / n

        avg_list = self.fileList[::step]
        n = len(avg_list)
        
        x, y = self.resolution
        avg_array = np.zeros((y, x, 3))
        
        for i in range(n):
            fp = os.path.join(self.path, avg_list[i])
            avg_array += fromimage( Image.open(fp), flatten = False )

            
        return toimage(avg_array / len(avg_array))

    def getTotalFrames(self):
        '''
        Return the total number of frames
        '''
        return self.totalFrames
        
    def isLastFrame(self):
        '''
        Are we processing the last frame in the folder?
        '''

        if (self.currentFrame == self.totalFrames) and not self.loop:
            return True
        elif (self.currentFrame == self.totalFrames) and self.loop:
            self.currentFrame = 0
            return False
        else:
            return False        

    def setResolution(self, w, h):
        '''
        Changes the output resolution
        '''
        self.resolution = (w, h)
        self.scale = (self.resolution != self.in_resolution)

    def compressAllImages(self, compression=90, resolution=(960,720)):
        '''
        FIX THIS: is this needed?
        good only for virtual cams
        Load all images one by one and save them in a new folder 
        '''
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
            
class Monitor(object):
    """
        The main monitor class
    """

    def __init__(self):

        '''
        A Monitor contains a cam, which can be either virtual or real.
        Real CAMs are handled through opencv, frames through PIL.
        '''
        pass
        
    def __initialize(self):
        '''
        Initialize some internal variables
        Called internally after the capture source is set
        '''

        self.grabMovie = False
        self.ROIS = []
        self.points_to_track = []
        self.firstFrame = True
        self.tracking = True

        self.use_average = False
        self.calculating_average = False
        self.imageCount = 0
        

    def __drawROI(self, img, ROI, color=None):
        '''
        Draw ROI on img using given coordinates
        ROI is a tuple of 4 tuples ( (x1, y1), (x2, y2), (x3, y3), (x4, y4) )
        and does not have to be necessarily a rectangle
        '''

        if not color: color = (255,255,255)
        width = 1
        line_type = cv.CV_AA


        cv.Line(img, ROI[0], ROI[1], color, width, line_type, 0)
        cv.Line(img, ROI[1], ROI[2], color, width, line_type, 0)
        cv.Line(img, ROI[2], ROI[3], color, width, line_type, 0)
        cv.Line(img, ROI[3], ROI[0], color, width, line_type, 0)

        return img

    def __drawCross(self, img, pt, color=None):
        '''
        Draw a cross around a point pt
        '''
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
        '''
        Return only the asked channel R,G or B
        '''

        cn = 'RGB'.find( channel.upper() )
        
        channels = [None, None, None]
        cv.Split(img, channels[0], channels[1], channels[2], None)
        return channels[cn]

    def __absCoord__(self, fly_n, ROI):
        '''
        FIX THIS
        Transform coordinates of a point whithin a ROI from relative to absolute
        '''
        pass
        
        
    def __distance(self, x1, y1, x2, y2):
        '''
        Calculate the distance between two cartesian points
        '''
        return sqrt((x2-x1)**2 + (y2-y1)**2)

    def __angle(self, pt1, pt2, pt0):
        '''
        Return the angle between three points
        '''
        dx1 = pt1[0] - pt0[0]
        dy1 = pt1[1] - pt0[1]
        dx2 = pt2[0] - pt0[0]
        dy2 = pt2[1] - pt0[1]
        return (dx1*dx2 + dy1*dy2)/sqrt((dx1*dx1 + dy1*dy1)*(dx2*dx2 + dy2*dy2) + 1e-10)

    def CaptureFromCAM(self, devnum=0, resolution=(640,480)):
        '''
        '''
        self.resolution = resolution
        self.isVirtualCam = False
        self.cam = realCam(devnum=devnum)
        self.cam.setResolution(*resolution)
        self.numberOfFrames = 0
        self.__initialize()
        
    def CaptureFromMovie(self, camera, resolution=None):
        '''
        
        virtual_camera = {  
            'path' : '/path/to/file.avi',
            'start': None,
            'step' : None,
            'end'  : None,
            'loop' : False
        }

        '''
        self.isVirtualCam = True
        self.cam = virtualCamMovie(path=camera['path'], 
                                   step=camera['step'],
                                   start = camera['start'],
                                   end = camera['end'],
                                   loop = camera['loop'],
                                   resolution = resolution)
                                   
        self.resolution = self.cam.getResolution()
        self.numberOfFrames = self.cam.getTotalFrames()
        self.__initialize()
        
    def CaptureFromFrames(self, camera, resolution=None):
        '''
        
        virtual_camera = {  
            'path' : '/path/to/file.avi',
            'start': None,
            'step' : None,
            'end'  : None,
            'loop' : False
        }

        '''
        self.isVirtualCam = True
        self.cam = virtualCamFrame(path=camera['path'], step=camera['step'], start = camera['start'], end = camera['end'], loop = camera['loop'], resolution = resolution)
        self.resolution = self.cam.getResolution()
        self.numberOfFrames = self.cam.getTotalFrames()
        self.__initialize()
    
    def isLastFrame(self):
        '''
        Proxy to isLastFrame()
        Handled by camera
        '''
        return self.cam.isLastFrame()


    def saveMovie(self, filename, fps=24, codec='FMP4'):
        '''
        Determines whether all the frames grabbed through getImage will also 
        be saved as movie.
        
        filename                           the full path to the file to be written
        fps             24   (Default)     number of frames per second
        codec           FMP4 (Default)     codec to be used
        
        http://stackoverflow.com/questions/5426637/writing-video-with-opencv-python-mac
        '''
        fourcc = cv.CV_FOURCC([c for c in codec])
        
        self.writer = cv.CreateVideoWriter(filename, fourcc, fps, self.resolution, 1)
        self.grabMovie = True


    def saveSnapshot(self, *args, **kwargs):
        '''
        proxy to saveSnapshot
        '''
        self.cam.saveSnapshot(*args, **kwargs)
    
    def SetLoop(self,loop):
        '''
        Set Loop on or off.
        Will work only in virtual cam mode and not realCam
        Return current loopmode
        '''
        if self.isVirtualCam:
            self.cam.loop = loop
            return self.cam.loop
        else:
            return False
    
    def addROI(self, ROI, n_flies=1):
        '''
        Add the coords for a new ROI and the number of flies we want to track in that area
        selection       (x1, y1, x2, y2)    A four point selection
        n_flies         1    (Default)      Number of flies to be tracked in that area
        '''
        
        self.ROIS.append(ROI)
        self.points_to_track.append(n_flies)

    def getROI(self, n):
        '''
        Returns the coordinates of the nth crop area
        '''
        if n > len(self.ROIS):
            coords = []
        else:
            coords = self.ROIS[n]
        return coords

    def delROI(self, n):
        '''
        removes the nth crop area from the list
        if n -1, remove all
        '''
        if n >= 0:
            self.ROIS.pop(n)
        elif n < 0:
            self.ROIS = []
        
    def saveROIS(self, filename):
        '''
        Save the current crop data to a file
        '''
        cf = open(filename, 'w')
        cPickle.dump(self.ROIS, cf)
        cPickle.dump(self.points_to_track, cf)

        cf.close()
        
    def loadROIS(self, filename):
        '''
        Load the crop data from a file
        '''
        try:
            cf = open(filename, 'r')
            self.ROIS = cPickle.load(cf)
            self.points_to_track = cPickle.load(cf)
            cf.close()
            return True
        except:
            return False

    def resizeROIS(self, origSize, newSize):
        '''
        Resize the mask to new size so that it would properly fit
        resized images
        '''
        ox, oy = origSize
        nx, ny = newSize
        xp = float(ox) / nx
        yp = float(oy) / ny
        
        for i, ROI in enumerate(self.ROIS):
            nROI = []
            for pt in ROI:
                nROI.append ( (pt[0]*xp, pt[1]*yp) )
            self.ROIS[i] = ROI

    def isPointInROI(self, pt):
        '''
        Check if a given point falls whithin one of the ROI
        Returns the ROI number or else returns -1
        '''
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
        '''
        translate ROI (list containing for points a tuples)
        into Rect (list containing two points as tuples)
        '''
        nROI = []
        for ROI in self.ROIS:
            (x1, y1), (x2, y2), (x3, y3), (x4, y4) = ROI
            lx = min([x1,x2,x3,x4])
            rx = max([x1,x2,x3,x4])
            uy = min([y1,y2,y3,y4])
            ly = max([y1,y2,y3,y4])
            nROI. append ( ( (lx,uy), (rx, ly) ) )
            
        return nROI

    def autoMask(self, pt1, pt2):
        '''
        EXPERIMENTAL
        This is experimental
        For now it works only with one kind of arena
        '''
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
            nROI.append ( ( (x,y), (x,y1), (x1,y1), (x1,y) ))
        
        self.ROIS = nROI
    
    def findOuterFrame(self, img, thresh=50):
        '''
        EXPERIMENTAL
        Find the greater square 
        '''
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
                            print 'current # of squares found %d' % len(squares)
                    contour = contour.h_next()
         
        return squares    
         
    def GetNumberOfVials(self):
        '''
        Return how many ROIs area we are analizing
        '''
        return len(self.ROIS)
        
    def GetImage(self, drawROIs = False, selection=None, crosses=None, timestamp=False):
        '''
        GetImage(self, drawROIs = False, selection=None, timestamp=0)
        
        drawROIs       False        (Default)   Will draw all ROIs to the image
                       True        
        
        selection      (x1,y1,x2,y2)            A four point selection to be drawn
        
        crosses        (x,y),(x1,y1)            A list of tuples containing single point coordinates
        
        timestamp      True                     Will add a timestamp to the bottom right corner
                       False        (Default)   
        
        Returns the last collected image
        '''

        self.imageCount += 1
        frame = self.cam.getImage(timestamp)

        if self.tracking: frame = self.doTrack(frame)

                
        if drawROIs and self.ROIS:
            for ROI in self.ROIS:
                frame = self.__drawROI(frame, ROI)

        if selection:
            frame = self.__drawROI(frame, selection, color=(0,0,255))
            
        if crosses:
            for pt in crosses:
                frame = self.__drawCross (frame, pt, color=(0,0,255))

        if self.grabMovie: cv.WriteFrame(self.writer, frame)
        
        return frame

    def doTrack(self, frame):
        '''
        Track flies in ROIS using findContour algorhytm or opencv
        Each frame is compared against the moving average
        
        '''

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
            cv.RunningAvg(frame, self.moving_average, 0.040, None) #0.020
            
            
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


        for ROI in self.ROIStoRect():
            (x1,y1), (x2,y2) = ROI
            cv.SetImageROI(grey_image, (x1,y1,x2-x1,y2-y1))
            cv.SetImageROI(frame, (x1,y1,x2-x1,y2-y1))
            
            # Calculate movements
            storage = cv.CreateMemStorage(0)
            contour = cv.FindContours(grey_image, storage, cv.CV_RETR_CCOMP, cv.CV_CHAIN_APPROX_SIMPLE)

            points = []
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
                    fly = ( pt1[0]+(pt2[0]-pt1[0])/2, pt1[1]+(pt2[1]-pt1[1])/2 )
                    area = (pt2[0]-pt1[0])*(pt2[1]-pt1[1])
                    
                    frame = self.__drawCross(frame, fly)

            cv.ResetImageROI(grey_image)
            cv.ResetImageROI(frame)

            #cv.Rectangle(frame, ROI[0], ROI[1], cv.CV_RGB(0,255,0), 1)

        return frame



