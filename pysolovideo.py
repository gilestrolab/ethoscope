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
"""Version 1.4

Each Monitor has a camera that can be: realCam || VirtualCamMovies || VirtualCamFrames
The class Monitor is handling the motion detection and data processing while the class Cam only handles
IO of image sources

Algorithm for motion analysis:

    Versions <1.0
    PIL through kmeans (vector quantization)
    http://en.wikipedia.org/wiki/Vector_quantization
    http://stackoverflow.com/questions/3923906/kmeans-in-opencv-python-interface
    
    Version 1.0
    Blob detection through CV
    Annoying mem leak associated to CV
    #http://opencv-users.1802565.n2.nabble.com/Why-is-cvClearMemStorage-not-exposed-through-the-Python-interface-td7229752.html
    
    Version 1.2
    Now all the video processing is handled through CV2, including contour detection
    
    Version 1.3
    Classes Arena and Monitor fuse. Class ROImask is born
    
    
Current Data format
    #0 rowline
    #1 date
    #2 time
    #3 monitor is active (1)
    #4 average frames per seconds (FPS)
    #5 tracktype (0,1,2)
    #6 is a monitor with sleep deprivation capabilities? (n/a)
    #7 monitor number, not yet implemented (n/a)
    #8 unused 
    #9 is light on or off (n/a)
    #10 actual activity (normally 32 datapoints)
    
"""


import os, datetime, time
import cPickle, json, sys
from calendar import month_abbr

import cv2
import numpy as np

import io, socket, struct
try:
    import picamera
except:
    print "no support for picamera"

import threading

from accessories.sleepdeprivator import sleepdeprivator


pySoloVideoVersion ='dev' #will be 1.4

FLY_FIRST_POSITION = (-1,-1)
FLY_NOT_DETECTED = None
PERIOD = 60 #in seconds
ACTIVITY_PERIOD = 1440 #buffer of activity, in minutes
NO_SERIAL_PORT = "NO SD"

MONITORS = []

class runningAvgComparison():
    """
    This is a class that stores a running average
    and a running STD
    For each value that is used to update,
    it returns also information on whether it is an outlier
    """
    
    def __init__(self):
        """
        """
        self.__tot_sum = 0
        self.__n = 0
        self.__sq_diff = 0
    
        
    def update(self, value, outlier=2):
        """
        Take a running value and returns:
        mean        the running mean
        std         the running standard deviation
        distance    how distant is the value from the mean
        outside     a boolean value of whether the value is outside 2 SD
        """

        self.__tot_sum += value
        self.__n += 1
        
        mean = self.__tot_sum / self.__n
        self.__sq_diff += np.square(value - mean)
        
        std = np.sqrt(self.__sq_diff / self.__n) or 1
        distance = (value - mean) / std
        outside = distance >= outlier
        
        return mean, std, distance, outside


class Cam:
    """
    Functions and properties inherited by all cams
    """
    
    def saveSnapshot(self, filename, quality=90, timestamp=False):
        """
        """
        frame, _ = self.getImage()
        cv2.imwrite(filename, frame)


    def close(self):
        """
        """
        return 0
        
    def getSerialNumber(self):
        """
        """
        return 0
        
    def getBlackFrame( self, resolution=(800,600) ):
        """
        """
        w, h = resolution
        blackframe = np.zeros( (w, h, 3), dtype = np.uint8)
        #blackframe = cv2.cvtColor(blackframe, cv2.GRAY2COLOR_BGR)
        cv2.putText(blackframe, "NO INPUT", (int(w/4), int(h/2)), cv2.FONT_HERSHEY_PLAIN, 2, (255,255,255), 1)
        return blackframe
    

class piCamera(Cam):
    """
    http://picamera.readthedocs.org/en/latest/api.html
    http://www.raspberrypi.org/picamera-pure-python-interface-for-camera-module/

    """
    def __init__(self, devnum=0, resolution=(800, 600), use_network=True):
        
        self.camera = 0
        self.resolution = resolution
        self.scale = False
        self.image_queue = self.getBlackFrame(resolution)
        
        if use_network:
            self.startNetworkStream()
        else:
            self.__initCamera()
        
    def __initCamera(self):
        """
        """
        self.camera = picamera.PiCamera()
        self.camera.resolution = self.resolution
        
    def startNetworkStream(self, port=8000):
        """
        """

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(('', port))
        print ("Live stream socket listening on port {p}...".format(p=port))
        self.pipe = None
        
        self.socket.listen(5)

        self.socket_thread_1 = threading.Thread(target=self.socket_listen)
        self.socket_thread_1.daemon=True
        self.socket_thread_2 = threading.Thread(target=self.socket_stream)
        self.socket_thread_2.daemon=True
        self.keepSocket = True
        
        self.socket_thread_1.start()
        self.socket_thread_2.start()
        
    def stopNetworkStream(self):
        """
        """
        self.keepSocket = False    
                
        
    def socket_listen(self):
        """
        """    

        while self.keepSocket:
            print "listening"
            try:
                self.remote, client_address = self.socket.accept()
                self.pipe = self.remote.makefile('wb',0)
                print "connected to client: " , client_address
            except:
                pass


    def socket_stream(self):
        """
        """
        
        while self.keepSocket:
            
            try:

                with picamera.PiCamera() as camera:
                    camera.resolution = self.resolution
                    # Start a preview and let the camera warm up for 2 seconds
                    camera.start_preview()
                    time.sleep(2)

                    # Note the start time and construct a stream to hold image data
                    # temporarily (we could write it directly to connection but in this
                    # case we want to find out the size of each capture first to keep
                    # our protocol simple)
                    stream = io.BytesIO()
                    for foo in camera.capture_continuous(stream, 'jpeg', use_video_port=True):

                        data = np.fromstring(stream.getvalue(), dtype=np.uint8)
                        # "Decode" the image from the array, preserving colour
                        image = cv2.imdecode(data, 1)
                        # Convert RGB to BGR
                        self.image_queue = image[:, :, ::-1]
                        
                        if self.pipe:
                            # Write the length of the capture to the stream and flush to
                            # ensure it actually gets sent
                            self.pipe.write(struct.pack('<L', stream.tell()))
                            self.pipe.flush()

                        # Rewind the stream
                        stream.seek(0)

                        if self.pipe:
                            # send the image data over the pipe
                            self.pipe.write(stream.read())

                        # Reset the stream for the next capture
                        stream.seek(0)
                        stream.truncate()

                # Write a length of zero to the pipe to signal we're done
                if self.pipe:
                    self.pipe.write(struct.pack('<L', 0))

                #finally:
                #    self.pipe.close()
                #    self.socket.close()

            except socket.error, e:
                print "Got Socket error", e
                self.remote.close()
                self.pipe = None

            except IOError, e:
                print "Got IOError: ", e
                self.pipe = None

    def close(self):
        """
        """
        if self.camera:
            self.camera.stop_preview()
            self.camera.close()

    def getFrameTime(self):
        """
        """
        return time.time() #current time epoch in secs.ms

    def setResolution(self, (x, y)):
        self.camera.resolution = (x, y)
        
    def getResolution(self):
        return self.camera.resolution

    def isLastFrame(self):
        """
        Added for compatibility with other cams
        """
        return False
    
    def hasSource(self):
        """
        Is the camera active?
        Return boolean
        """
        return self.camera != None

    def getImage(self):
        """
        """
        frame = self.image_queue 
        if self.scale:
            frame = cv2.resize( frame, self.resolution )
        
        return frame, self.getFrameTime()
    
class realCam(Cam):
    """
    a realCam class will handle a webcam connected to the system
    camera is handled through cv2
    """
    def __init__(self, devnum=0, resolution=(800, 600)):

        self.devnum=devnum
        self.resolution = resolution
        self.scale = False
        
        self.__initCamera()
        
    def __initCamera(self):
        """
        """
        self.camera = cv2.VideoCapture(self.devnum)
        self.setResolution (self.resolution)

    def getFrameTime(self):
        """
        """
        return time.time() #current time epoch in secs.ms

    def setResolution(self, (x, y)):
        """
        Set resolution of the camera we are acquiring from
        """
        x = int(x); y = int(y)
        self.resolution = (x, y)

        #http://stackoverflow.com/questions/11420748/setting-camera-parameters-in-opencv-python
        self.camera.set(cv2.cv.CV_CAP_PROP_FRAME_WIDTH, x)
        self.camera.set(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT, y)
        
        x1, y1 = self.getResolution()
        self.scale = ( (x, y) != (x1, y1) ) # if the camera does not support resolution, we need to scale the image
        
    def getResolution(self):
        """
        Return real resolution
        """
        x1 = self.camera.get(cv2.cv.CV_CAP_PROP_FRAME_WIDTH)
        y1 = self.camera.get(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT)
        return (int(x1), int(y1))
        

    def getImage( self ):
        """
        Returns frame, timestamp
        """
       
        if not self.camera:
            self.__initCamera()
        
        __, frame = self.camera.read()
        
        try:
            frame.shape > 0
        except:
            frame = self.getBlackFrame()
        
        if self.scale:
            frame = cv2.resize( frame, self.resolution )

        return frame, self.getFrameTime()

    def isLastFrame(self):
        """
        Added for compatibility with other cams
        """
        return False
        
    def close(self):
        """
        Closes the connection 
        http://stackoverflow.com/questions/15460706/opencv-cv2-in-python-videocapture-not-releasing-camera-after-deletion
        """
        print "attempting to close stream"

        self.camera.release
        self.camera = None
        
        
    def getSerialNumber(self):
        """
        Uses pyUSB
        http://stackoverflow.com/questions/8110310/simple-way-to-query-connected-usb-devices-info-in-python
        http://askubuntu.com/questions/49910/how-to-distinguish-between-identical-usb-to-serial-adapters
        """
        serial = 'NO_SERIAL'
        plat = os.sys.platform # linux, linux2, darwin, win32
        if "linux" in plat:
            try:
                addr = "/dev/video%s" % self.devnum
                o = os.popen ("udevadm info %s | grep ID_SERIAL_SHORT" % addr).read().strip()
                _ , serial = o.split("=")
            except:
                pass
            
        return serial
            
    def hasSource(self):
        """
        Is the camera active?
        Return boolean
        """
        return self.camera.isOpened()

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

        self.capture = cv2.VideoCapture(self.path)

        #finding the input resolution
        w = self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_WIDTH)
        h = self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT)
        
        self.in_resolution = (int(w), int(h))
        self.resolution = self.in_resolution

        # setting the output resolution
        self.setResolution(*resolution)

        self.totalFrames = self.getTotalFrames()
        if end < 1 or end > self.totalFrames: end = self.totalFrames
        self.lastFrame = end
       
       
    def getResolution(self):
        """
        Returns frame resolution as tuple (w,h)
        """
        x = self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_WIDTH)
        y = self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT)

        return (x,y)
        

    def getFrameTime(self, asString=None):
        """
        Return the time of the frame
        """
        
        frameTime = self.capture.get(cv2.cv.CV_CAP_PROP_POS_MSEC)
        
        if asString:
            frameTime = str( datetime.timedelta(seconds=frameTime / 100.0) )
            return '%s - %s/%s' % (frameTime, self.currentFrame, self.totalFrames) #time.asctime(time.localtime(fileTime))
        else:
            return frameTime / 1000.0 #returning seconds compatibility reasons
    
    def getImage(self):
        """
        Returns frame, timestamp
        """

        #cv2.SetCaptureProperty(self.capture, cv2.CV_CAP_PROP_POS_FRAMES, self.currentFrame)
        # this does not work properly. Image is very corrupted
        __, frame = self.capture.read()

        try:
            frame.shape > 0
        except:
            frame = self.getBlackFrame()
            
        
        self.currentFrame += self.step
            
        #elif self.currentFrame > self.lastFrame and not self.loop: return False

        if self.scale:
            frame = cv2.resize(frame, self.resolution)

        return frame, self.getFrameTime()
      
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
        return self.capture.get( cv2.cv.CV_CAP_PROP_FRAME_COUNT )

    def isLastFrame(self):
        """
        Are we processing the last frame in the movie?
        """
        
        if ( self.currentFrame >= self.totalFrames ) and not self.loop:
            return True
        elif ( self.currentFrame >= self.totalFrames ) and self.loop:
            self.currentFrame = self.start
            return False
        else:
            return False


    def hasSource(self):
        """
        Is the camera active?
        Return boolean
        """
        return self.capture.isOpened()

class virtualCamFrames(Cam):
    """
    A Virtual cam to be used to pick images from a folder rather than a webcam
    Images are handled through PIL
    """
    def __init__(self, path, resolution = None, step = None, start = None, end = None, loop = False):
        self.path = path
        self.fileList = self.__populateList__(start, end, step)
        self.totalFrames = len(self.fileList)

        self.currentFrame = 0
        self.last_time = None
        self.loop = False

        fp = os.path.join(self.path, self.fileList[0])
        
        frame = cv2.imread(fp,cv2.CV_LOAD_IMAGE_COLOR)
        self.in_resolution = frame.shape
        
        if not resolution: resolution = self.in_resolution
        self.resolution = resolution
        self.scale = (self.in_resolution != self.resolution)

    def getFrameTime(self, asString=None):
        """
        Return the time of most recent content modification of the file fname
        """
        n = self.currentFrame
        fname = os.path.join(self.path, self.fileList[n])

        manual = False
        if manual:
            return self.currentFrame
        
        if fname and asString:
            fileTime = os.stat(fname)[-2]
            return time.asctime(time.localtime(fileTime))
        elif fname and not asString:
            fileTime = os.stat(fname)[-2]
            return fileTime
            
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


    def getImage(self):
        """
        Returns frame, timestamp
        """
        n = self.currentFrame
        fp = os.path.join(self.path, self.fileList[n])

        self.currentFrame += 1

        try:
            frame = cv2.imread(fp,cv2.CV_LOAD_IMAGE_COLOR)
            
        except:
            print ( 'error with image %s' % fp )
            raise

        if self.scale:
            frame = cv2.resize(frame, self.resolution)

        self.last_time = self.getFrameTime()
    
        return frame, self.last_time
    
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
        
        
    def getResolution(self):
        """
        Return frame resolution
        TODO: DOES THIS WORK?
        """
        return self.resolution

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


    def hasSource(self):
        """
        Is the camera active?
        Return boolean
        """
        return self.fileList != []

class ROImask():
    """
    This is the Class handling the info about the ROI Mask
    This classes adds and removes ROI, checks if a point is in ROI,
    load and saves ROIS to file
    
    No tracking here
   
    """
    def __init__(self, parent):
        self.monitor = parent
        
        self.ROIS = [] #Regions of interest
        self.beams = [] # beams: absolute coordinates
        self.ROAS = [] #Regions of Action
        self.points_to_track = []
        self.referencePoints = ((),())
        self.serial = None
        
        
    def relativeBeams(self):
        """
        Return the coordinates of the beam
        relative to the ROI to which they belong
        """
        
        newbeams = []
        
        for ROI, beam in zip(self.ROIS, self.beams):

                rx, ry = self.__ROItoRect(ROI)[0]
                (bx0, by0), (bx1, by1) = beam
                
                newbeams.append( ( (bx0-rx, by0-ry), (bx1-rx, by1-ry) ) )
                
        return newbeams

    def __ROItoRect(self, ROIcoords):
        """
        Used internally
        Converts a ROI (a tuple of four points coordinates) into
        a Rect (a tuple of two points coordinates)
        """
        (x1, y1), (x2, y2), (x3, y3), (x4, y4) = ROIcoords
        lx = min([x1,x2,x3,x4])
        rx = max([x1,x2,x3,x4])
        uy = min([y1,y2,y3,y4])
        ly = max([y1,y2,y3,y4])
        return ( (lx,uy), (rx, ly) )

    def __distance( self, (x1, y1), (x2, y2) ):
        """
        Calculate the distance between two cartesian points
        """
        return np.sqrt((x2-x1)**2 + (y2-y1)**2)
        
    def __getMidline (self, coords):
        """
        Return the position of each ROI's midline
        Will automatically determine the orientation of the vial
        """
        (x1,y1), (x2,y2) = self.__ROItoRect(coords)

        horizontal = abs(x2 - x1) > abs(y2 - y1)
        
        if horizontal:
            xm = x1 + (x2 - x1)/2
            return (xm, y1), (xm, y2) 
        else:
            ym = y1 + (y2 - y1)/2
            return (x1, ym), (x2, ym)
    
    def calibrate(self, p1, p2, cm=1):
        """
        The distance between p1 and p2 will be set to be X cm
        (default 1 cm)
        """
        cm = float(cm)
        dpx = self.__distance(p1, p2)
        
        self.ratio = dpx / cm  
        
        return self.ratio

    def pxToCm(self, distance_px):
        """
        Converts distance from pixels to cm
        """
        
        if self.ratio:
            return distance_px / self.ratio
        else:
            print "You need to calibrate the mask first!"
            return distance_px
            
    def addROI(self, coords, n_flies):
        """
        Add a new ROI to the arena
        """
        good_coords = (np.array(coords)>=0).all()
        
        if good_coords: 
            self.ROIS.append( coords )
            self.beams.append ( self.__getMidline (coords)  ) 
            self.points_to_track.append(n_flies)
        
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
            self.beams.pop(n)
            self.points_to_track.pop(n)

        elif n < 0:
            self.ROIS = []
            self.beams = []
            self.points_to_track = []
            self.referencePoints == ((),())
            
    def getROInumber(self):
        """
        Return the number of current active ROIS
        """
        return len(self.ROIS)
        
    def saveROIS(self, filename, serial=None):
        """
        Save the current crop data to a file
        """
        cf = open(filename, 'w')
        self.serial = serial
        jsonData = {'ROIS':self.ROIS, 'pointsToTrack':self.points_to_track,'referencePoints': self.referencePoints, 'serial':self.serial}
        json.dumps({self.ROIS, self.points_to_track, self.referencePoints, self.serial},cf)
        cf.close()

    def loadROIS(self, filename):
        """
        Load the crop data from a file
        """
        try:
            cf = open(filename, 'r')
            data = json.load(cf)
            self.ROIS = []
            tup=[]
            for t in data['ROIS']:
                for p in t:
                    p = tuple(p)
                    tup.append(p)
                self.ROIS.append(tuple(tup))
                tup=[]
            
            self.points_to_track = data['pointsToTrack']
            self.referencePoints = data['referencePoints']
            if self.referencePoints == "none":
                self.referencePoints = ((),())
            if data['serial']=='NO_SERIAL':
                self.serial = None
            else:
                self.serial = data['serial']
            cf.close()
            
            for coords in self.ROIS:
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

        def __point_in_poly(pt, poly):
            """
            Determine if a point is inside a given polygon or not
            Polygon is a list of (x,y) pairs. This fuction
            returns True or False.  The algorithm is called
            "Ray Casting Method".
            polygon = [(x,y),(x1,x2),...,(x10,y10)]
            http://pseentertainmentcorp.com/smf/index.php?topic=545.0
            Alternatively:
            http://opencv2.itseez.com/doc/tutorials/imgproc/shapedescriptors/point_polygon_test/point_polygon_test.html
            """
            x, y = pt
            
            n = len(poly)
            inside = False

            p1x,p1y = poly[0]
            for i in xrange(n+1):
                p2x,p2y = poly[i % n]
                if y > min(p1y,p2y):
                    if y <= max(p1y,p2y):
                        if x <= max(p1x,p2x):
                            if p1y != p2y:
                                xinters = (y-p1y)*(p2x-p1x)/(p2y-p1y)+p1x
                            if p1x == p2x or x <= xinters:
                                inside = not inside
                p1x,p1y = p2x,p2y

            return inside

        
        for ROI in self.ROIS:
            if __point_in_poly(pt, ROI):
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

    def autoMask(self, pt1, pt2):
        """
        EXPERIMENTAL, FIX THIS
        This is experimental
        For now it works only with one kind of arena
        Should be more flexible than this
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
        for v in xrange(rows):
            ROI[k] = (x, y), (x+l, y+d)
            ROI[k+1] = (x1-l, y) , (x1, y+d)
            k+=2
            y+=d
        
        nROI = []
        for R in ROI:
            (x, y), (x1, y1) = R
            self.addROI( ( (x,y), (x,y1), (x1,y1), (x1,y) ), 1)
            
        return vials
    
    def findOuterFrame(self, img, thresh=50):
        """
        EXPERIMENTAL
        Find the greater square 
        THIS NEED TO BE TRANSLATED TO CV2 - AT THE MOMENT IS NOT USED
        """
        
        def angle(pt1, pt2, pt0):
            """
            Return the angle between three points
            """
            dx1 = pt1[0] - pt0[0]
            dy1 = pt1[1] - pt0[1]
            dx2 = pt2[0] - pt0[0]
            dy2 = pt2[1] - pt0[1]
            return (dx1*dx2 + dy1*dy2)/np.sqrt((dx1*dx1 + dy1*dy1)*(dx2*dx2 + dy2*dy2) + 1e-10)
        
        
        N = 11
        sz = (img.width & -2, img.height & -2)
        storage = cv2.CreateMemStorage(0)
        timg = cv2.CloneImage(img)
        gray = cv2.CreateImage(sz, 8, 1)
        pyr = cv2.CreateImage((img.width/2, img.height/2), 8, 3)

        squares =[]
        # select the maximum ROI in the image
        # with the width and height divisible by 2
        subimage = cv2.GetSubRect(timg, (0, 0, sz[0], sz[1]))

        # down-scale and upscale the image to filter out the noise
        cv2.PyrDown(subimage, pyr, 7)
        cv2.PyrUp(pyr, subimage, 7)
        tgray = cv2.CreateImage(sz, 8, 1)
        # find squares in every color plane of the image
        for c in xrange(3):
            # extract the c-th color plane
            channels = [None, None, None]
            channels[c] = tgray
            cv2.Split(subimage, channels[0], channels[1], channels[2], None) 
            for l in xrange(N):
                # hack: use Canny instead of zero threshold level.
                # Canny helps to catch squares with gradient shading
                if(l == 0):
                    cv2.Canny(tgray, gray, 0, thresh, 5)
                    cv2.Dilate(gray, gray, None, 1)
                else:
                    # apply threshold if l!=0:
                    #     tgray(x, y) = gray(x, y) < (l+1)*255/N ? 255 : 0
                    cv2.Threshold(tgray, gray, (l+1)*255/N, 255, cv2.CV_THRESH_BINARY)

                # find contours and store them all as a list
                contours = cv2.FindContours(gray, storage, cv2.CV_RETR_LIST, cv2.CV_CHAIN_APPROX_SIMPLE)

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
                    result = cv2.ApproxPoly(contour, storage,
                        cv2.CV_POLY_APPROX_DP, cv2.ArcLength(contour) *0.02, 0)

                    # square contours should have 4 vertices after approximation
                    # relatively large area (to filter out noisy contours)
                    # and be convex.
                    # Note: absolute value of an area is used because
                    # area may be positive or negative - in accordance with the
                    # contour orientation
                    if(len(result) == 4 and 
                        abs(cv2.ContourArea(result)) > 500 and 
                        cv2.CheckContourConvexity(result)):
                        s = 0
                        for i in xrange(5):
                            # find minimum angle between joint
                            # edges (maximum of cosine)
                            if(i >= 2):
                                t = abs(angle(result[i%4], result[i-2], result[i-1]))
                                if s<t:
                                    s=t
                        # if cosines of all angles are small
                        # (all angles are ~90 degree) then write quandrange
                        # vertices to resultant sequence
                        if(s < 0.3):
                            pt = [result[i] for i in xrange(4)]
                            squares.append(pt)
                            print ('current # of squares found %d' % len(squares))
                    contour = contour.h_next()
         
        return squares    


    
class Monitor(object):
    """
    The main monitor class
    """

    def __init__(self):

        """
        A Monitor contains a cam, which can be either virtual or real.
        Everything is handled through openCV
        """
        
        self.grabMovie = False
        self.writer = None
        self.cam = None
        self.drawing = True
        self.isTracking = False

        self.referencePoints = None
        
        self.mask = ROImask(self)

        self.__last_time = 0
        self.__temp_FPS = 0 
        self.__processingFPS = 0
        self.__rowline = 0
        #self.__image_queue = Queue
        self.__image_queue = None # for one frame queue we don't need a real queue.
        
        # TO DO: NOT IMPLEMENTED YET
        self.ratio = 0 # used for mask calibration, px to cm
        
        self.trackType = 1
        self.minuteFPS = runningAvgComparison()
        
        self.SDserialPort = None
        self.inactivity_threshold = 7
        self.flyActivity = np.zeros ((0,ACTIVITY_PERIOD), dtype=np.int)
        
        # Buffer arrays
        # shape ( PERIOD (x,y )
        self.__fa = np.zeros( (PERIOD, 2), dtype=np.int )
        # shape ( flies, (x,y) ) Contains the coordinates of the last second (if fps > 1, average)
        self.fly_last_frame_buffer = np.zeros( (0, 2), dtype=np.int ) 
        # shape ( flies, PERIOD, (x,y) ) Contains the coordinates of the last minute (or period)
        self.fly_one_minute_buffer = np.zeros( (0, PERIOD, 2), dtype=np.int ) 
        
       
        self.__count_seconds = 0
        self.__n = 0
        self.outputFile = None
      
        self.fly_area = runningAvgComparison()
        self.fly_movement = runningAvgComparison()

        self.debug_info = {}


#######################################################        
        
        
#### DRAWING FUNCTION OF MONITOR ######################        
    
    def __distance( self, (x1, y1), (x2, y2) ):
        """
        Calculate the distance between two cartesian points
        """
        return np.sqrt((x2-x1)**2 + (y2-y1)**2)

    def __drawBeam(self, img, bm, color=None):
        """
        Draw the Beam using given coordinates
        """
        if not color: color = (100,100,200)
        width = 1
        line_type = cv2.CV_AA

        cv2.line(img, bm[0], bm[1], color, width, line_type, 0)

        return img

    def __drawDebugInfo(self, frame):
        """
        Add Debug information
        """

        textcolor = (255,255,255)
        x, y = 20,20
        height, width, _ = frame.shape

        for label, value in self.debug_info.iteritems():
            text = "%s: %s" % (label, value)
                
            (x1, y1), ymin = cv2.getTextSize(text, cv2.FONT_HERSHEY_PLAIN, 1, 1)
            y = height - ymin - 2
            cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_PLAIN, 1, textcolor, 1)
            height = height - y1*2
        
        return frame

    def __addTimeStamp(self, frame, timeStamp):
        """
        Add current time as stamp to the image
        """
        text = time.asctime( time.localtime(timeStamp) )
        textcolor = (255,255,255)
        (x1, _), ymin = cv2.getTextSize(text, cv2.FONT_HERSHEY_PLAIN, 1, 1)

        height, width, _ = frame.shape
        x = width - x1 - (width/64)
        y = height - ymin - 2

        cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_PLAIN, 1, textcolor, 1)
        
        return frame
        
    def __drawROI(self, frame, ROI, color=None, ROInum=None):
        """
        Draw ROI on img using given coordinates
        ROI is a tuple of 4 tuples ( (x1, y1), (x2, y2), (x3, y3), (x4, y4) )
        and does not have to be necessarily a rectangle
        """

        if not color: color = (255,255,255)
        width = 1
        line_type = cv2.CV_AA

        cv2.polylines(frame, np.array([ROI]), isClosed=1, color=color, thickness=1, lineType=line_type, shift=0)
        
        if ROInum is not None:
            x, y = ROI[0]
            textcolor = (255,255,255)
            text = "%02d" % ROInum
            cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_PLAIN, 1, textcolor, 1)

        return frame

    def __drawCross(self, frame, pt, color=None, text=None):
        """
        Draw a cross around a point pt
        """
        if pt is not None:
            if not color: color = (255,255,255)
            width = 1
            line_type = cv2.CV_AA
            
            x, y = pt
            a = (x, y-5)
            b = (x, y+5)
            c = (x-5, y)
            d = (x+5, y)
            
            cv2.line(frame, a, b, color, width, line_type, 0)
            cv2.line(frame, c, d, color, width, line_type, 0)
            
            if text: cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_PLAIN, 1, (255,255,255), 1)
        
        return frame
        
    def __drawLastSteps(self, frame, fly, steps=5, color=None):
        """
        Draw the last n (default 5) steps of the fly
        """

        if not color: color = (255,255,255)
        width = 1
        line_type = cv2.CV_AA

        points = self.getLastSteps(fly, steps)

        cv2.polylines(frame, [points], is_closed=0, color=color, thickness=1, lineType=line_type, shift=0)

        return frame
        

#######################################################        
        
#### VARIOUS FUNCTIONS ###############################        
        

    def __getChannel(self, img, channel='R'):
        """
        Return only the asked channel R,G or B
        """

        cn = 'RGB'.find( channel.upper() )
        
        channels = [None, None, None]
        cv2.split(img, channels[0], channels[1], channels[2], None)
        return channels[cn]

        
    def getUptime(self):
        """
        """
        delta = (datetime.datetime.now() - self.starttime)
        
        t = datetime.timedelta(seconds=delta.seconds)
        r = self.__rowline
        return t, r
        

    def trackingLoop(self, kbdint=False):
        """
        """
        #cv2.namedWindow("preview")
        
        while self.isTracking:
            #frame = self.GetImage(drawROIs = True, selection=None, crosses=None, timestamp=True, draw_path=False)
            frame = self.GetImage(drawROIs = True, selection=None, crosses=None, timestamp=True, draw_path=False)
            #cv2.imshow("preview", frame)
           

    def startTracking(self):
        self.track_thread = threading.Thread(target=self.trackingLoop)
        self.isTracking = True
        self.starttime = datetime.datetime.now()

        self.track_thread.start()
        
    def stopTracking(self):
        self.isTracking = False
        
        
#######################################################

#### CAM FUNCTION OF MONITOR ##########################       

    def __captureFromPICAM(self, resolution=(800,600), options=None):
        """
        Capture from raspberryPI camera
        """
        self.isVirtualCam = False
        
        self.cam = piCamera(resolution)

        self.source = 1000
        self.resolution = resolution
        self.numberOfFrames = 0
       
        return self.cam is not None
        

    def __captureFromCAM(self, devnum=0, resolution=(800,600), options=None):
        """
        Capture from an actual hardware camera
        """
        self.isVirtualCam = False
        
        try:
            self.cam = realCam(devnum=devnum)

            self.source = devnum
            self.resolution = resolution
            self.cam.setResolution(resolution)
            self.resolution = self.cam.getResolution()
            self.numberOfFrames = 0
       
        except:
            pass

        return self.cam is not None

       
    def __captureFromMovie(self, camera, resolution=None, options=None):
        """
        Capture from movie file
        """
        self.isVirtualCam = True
        self.source = camera
        
        if options:
            step = options['step']
            start = options['start']
            end = options['end']
            loop = options['loop']
        try:
            self.cam = virtualCamMovie(path=camera, resolution = resolution)
            self.resolution = self.cam.getResolution()
            self.numberOfFrames = self.cam.getTotalFrames()
        except:
            pass

        return self.cam is not None

        
    def __captureFromFrames(self, camera, resolution=None, options=None):
        """
        """
        self.isVirtualCam = True
        self.source = camera
        
        if options:
            step = options['step']
            start = options['start']
            end = options['end']
            loop = options['loop'] 

        try:
            self.cam = virtualCamFrames(path = camera, resolution = resolution)
            self.resolution = self.cam.getResolution()
            self.numberOfFrames = self.cam.getTotalFrames()
        except:
            pass

        return self.cam is not None

    
    def hasSource(self):
        """
        """
        if self.cam is not None:
            return self.cam.hasSource()
        else:
            return False
    
    def setSource(self, camera, resolution, options=None):
        """
        Set source intelligently
        """

        try:
            camera = int(camera)
        except:
            pass
            
        if type(camera) == int and camera == 1000:
            self.__captureFromPICAM(resolution, options)
        elif type(camera) == int:
            self.__captureFromCAM(camera, resolution, options)
        elif os.path.isfile(camera):
            self.__captureFromMovie(camera, resolution, options)
        elif os.path.isdir(camera):
            self.__captureFromFrames(camera, resolution, options)

        if self.hasSource():
            self.debug_info["source"] = camera
            self.debug_info["res"] = "%s,%s" % (resolution)
            self.debug_info["serial"] = self.cam.getSerialNumber()
        
        return self.hasSource()

    def close(self):
        """
        Closes stream
        """
        self.cam.close()
        self.isTracking = False
        
    def setTracking(self, track, trackType=0, mask_file='', outputFile=''):
        """
        Set the tracking parameters
        
        track       Boolean     Do we do tracking of flies?
        trackType   0           tracking using the virtual beam method
                    1 (Default) tracking calculating distance moved
        mask_file   text        the file used to load and store masks
        outputFile  text        the txt file where results will be saved
        """

        if trackType == None: trackType = 0
        if mask_file == None: mask_file = ''
        if outputFile == None: outputFile = ''

        self.track = track
        self.trackType = int(trackType)
        self.mask_file = mask_file
        self.outputFile = outputFile
        
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
        
        fourcc = cv2.cv.CV_FOURCC(*[c for c in codec]) # or -1
        self.writer = cv2.VideoWriter(filename, fourcc, fps ,self.resolution )
        self.grabMovie = not startOnKey

        #self.writer.release()

    def saveSnapshot(self, filename, quality=90, timestamp=False):
        """
        proxy to saveSnapshot
        """
        if self.__image_queue != None:
            cv2.imwrite(filename, self.__image_queue)
        else:
            self.cam.saveSnapshot(filename, quality, timestamp)

    
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


#######################################################        
        
        
#### ROI FUNCTION OF MONITOR - NOT NEEDED? ############    
   
    def updateFlyBuffers(self, n, new=False):
        """
        Every time we add a new ROI the array need to be ridimensioned
        """
        if not new:
            
            if n > 0:
                #these increase by one on the fly axis

                for i in xrange(n):
                    self.fly_last_frame_buffer = np.append( self.fly_last_frame_buffer, [FLY_FIRST_POSITION], axis=0) # ( flies, (x,y) )
                    self.fly_one_minute_buffer = np.append (self.fly_one_minute_buffer, [self.__fa.copy()], axis=0) # ( flies, PERIOD, (x,y) )
                    self.flyActivity = np.append (self.flyActivity, np.zeros ((1,ACTIVITY_PERIOD), dtype=np.int) , axis=0)
            if n < 0:

                for i in xrange(n):
                    self.fly_last_frame_buffer = np.delete( self.fly_last_frame_buffer, n, axis=0)
                    self.fly_one_minute_buffer = np.delete( self.fly_one_minute_buffer, n, axis=0)
                    self.flyActivity = np.delete (self.flyActivity, n,axis=0)
            
            if n == 0:
                self.fly_last_frame_buffer = np.zeros( (0, 2), dtype=np.int ) 
                self.fly_one_minute_buffer = np.zeros( (0, PERIOD, 2), dtype=np.int )
                self.flyActivity = np.zeros ((0,ACTIVITY_PERIOD), dtype=np.int)
        
        if new:
            self.updateFlyBuffers(0) # delete first
            self.updateFlyBuffers(n) # then repopulate
            
        self.debug_info["ROIs"] = self.mask.getROInumber()
        
    def getFliesDetected(self):
        """
        Returns how many flies are we actually detecting
        Ignores flies that never moved
        """
        c = (self.fly_last_frame_buffer != FLY_FIRST_POSITION)
        return c.all(axis=1).sum()
   
    def addROI(self, coords, n_flies=1):
        """
        Add the coords for a new ROI and the number of flies we want to track in that area
        selection       (pt1, pt2, pt3, pt4)    A four point selection
        n_flies         1    (Default)      Number of flies to be tracked in that area
        """
        
        self.mask.addROI(coords, n_flies)
        n = self.mask.getROInumber() - self.fly_last_frame_buffer.shape[0]
        self.updateFlyBuffers(n)
        
    def hasROI(self):
        '''
        Return true if at least a single roi is detected
        '''
        return self.mask.getROInumber() > 0

    def getROI(self, n):
        """
        Returns the coordinates of the nth crop area
        """
        return self.mask.getROI(n)

    def delROI(self, n):
        """
        removes the nth crop area from the list
        if n -1, remove all
        """
        self.mask.delROI(n)

        if n >= 0:
            self.updateFlyBuffers(-n)
        
        elif n == -1:
            self.updateFlyBuffers(0)

        
    def saveROIS(self, filename=None):
        """
        Save the current crop data to a file
        """
        if not filename: filename = self.mask_file
        self.mask.referencePoints = self.referencePoints
        self.mask.saveROIS( filename, self.cam.getSerialNumber() )
        
    def loadROIS(self, filename=None):
        """
        Load the crop data from a file
        """
        if not filename: filename = self.mask_file
        
        if self.mask.loadROIS(filename):
            nROI = self.mask.getROInumber()
            self.updateFlyBuffers(nROI, new=True)

            return True
        else:
            return False

    def resizeROIS(self, origSize, newSize):
        """
        Resize the mask to new size so that it would properly fit
        resized images
        """
        return self.mask.resizeROIS(origSize, newSize)

    def isPointInROI(self, pt):
        """
        Check if a given point falls whithin one of the ROI
        Returns the ROI number or else returns -1
        """
        return self.mask.isPointInROI(pt)

    def calibrate(self, pt1, pt2, cm=1):
        """
        Relays to arena calibrate
        """
        return self.mask.calibrate(pt1, pt2, cm)
        
        
    def autoMask(self, pt1, pt2):
        """
        """
        n = self.mask.autoMask(pt1, pt2)
        self.updateFlyBuffers(n)

#######################################################        
        
        
#### TRACKING FUNCTIONS OF MONITOR ####################

    def getLastSteps(self, fly, steps):
        """
        """
        c = self.__count_seconds
        return [(x,y) for [x,y] in self.fly_one_minute_buffer[fly][c-steps:c].tolist()] + [tuple(self.fly_last_frame_buffer[fly].flatten())]

    def addFlyCoords(self, count, fly_coords):
        """
        Add the provided coordinates to the existing list
        count   int     the fly number in the arena 
        fly     (x,y)   the coordinates to add 
        Called for every fly moving in every frame
        """

        previous_position = tuple(self.fly_last_frame_buffer[count])
        if fly_coords == FLY_NOT_DETECTED: fly_coords = previous_position

        is_first_movement = not ( fly_coords == FLY_FIRST_POSITION )
        distance = self.__distance( previous_position, fly_coords )
        
        avg, std, _, is_outside = self.fly_movement.update(distance, outlier=1)
        
        self.debug_info['FLY_DISTANCE_AVG'] = "%.1f" % avg
        self.debug_info['FLY_DISTANCE_STD'] = "%.1f" % std
        
        if is_outside and not is_first_movement:
            fly = previous_position
        
        # Does a running average for the coordinates of the fly at each frame to fly_one_second_buffer
        # This way the shape of fly_one_second_buffer is always (n, (x,y)) and once a second we just have to add the (x,y)
        # values to flyDataMin, whose shape is (n, 60, (x,y))
        # shape is (n+1, 2) where n is the number of ROIS.
        
        b = self.fly_last_frame_buffer[count]
        self.fly_last_frame_buffer[count] = np.append( b[b!=-1], fly_coords, axis=0).reshape(-1,2).mean(axis=0)
        
        return fly_coords, distance
        
    def compactSeconds(self, FPS, delta):
        """
        Compact the frames collected in the last second
        by averaging the value of the coordinates

        Called every second; flies treated at once
        FPS         current rate of frame per seconds
        delta       how much time has elapsed from the last "second"
        """

        avgFPS, _, _, _ = self.minuteFPS.update(FPS)
        self.fly_one_minute_buffer[:,self.__n] = self.fly_last_frame_buffer

        if self.__count_seconds + 1 >= PERIOD:
            self.writeActivity( fps = avgFPS )
            self.__count_seconds = 0
            self.__n = 0 

            for i in xrange(0,PERIOD):
                    self.fly_one_minute_buffer[:,i] = self.fly_last_frame_buffer
            
        #growing continously; this is the correct thing to do but we would have problems adding new row with new ROIs
        #self.fly_one_minute_buffer = np.append(self.fly_one_minute_buffer, self.fly_last_frame_buffer, axis=1)


        self.__count_seconds += delta
        self.__n += 1


    def isSDMon(self):
        """
        Make sure the monitor has sleepdeprivation capabilities
        """
        
        if (self.SDserialPort != NO_SERIAL_PORT) and self.SDserialPort:
            #return sleepdeprivator.ping(use_serial=False, port=self.SDserialPort)
            return True
        else:
            return False

    def isSD(self):
        """
        It's time for performing sleep deprivation
        """
        timetoSD = True
        
        #first check that the monitor is able to do SD
        return self.isSDMon() and timetoSD
        

    def writeActivity(self, fps=0, extend=True):
        """
        Write the activity to file
        Kind of motion depends on user settings
        
        Called every minute; flies treated at once
        1   09 Dec 11   19:02:19    1   0   1   0   0   0   ?       [actual_activity]
        """
        
        #Here we build the header
        dt = datetime.datetime.fromtimestamp( self.getFrameTime() )
       
        #0 rowline        # computed when writing to file
        #1 date
        date = '%02d %s %s' % (dt.day, month_abbr[dt.month], dt.year-2000)
        #2 time        # computed when writing to file
        #3 monitor is active
        active = '1'
        #4 average frames per seconds (FPS)
        damscan = int(round(fps))
        #5 tracktype # ['DISTANCE','VBS','XY_COORDS']
        tracktype = self.trackType
        #6 is a monitor with sleep deprivation capabilities?
        sleepDep = int(self.isSDMon())
        #7 monitor number, not yet implemented
        monitor = '0'
        #8 unused
        unused = 0
        #9 is light on or off
        light = '?'
        
        #10 actual activity (normally 32 datapoints)
        
        activity = []
        row = ''

        if self.trackType == 0: 
            activity = [self.calculateDistances(),]
        
        elif self.trackType == 1:
            activity = [self.calculateVBM(),]
        
        elif self.trackType == 2:
            activity = self.calculatePosition()
            
        if self.isSD():
            self.calculateImmobility()
            self.sleepDeprive(interval=5)

        # Expand the readings to 32 flies for compatibility reasons with trikinetics
        flies = len ( activity[0].split('\t') )
        if extend and flies < 32:
            extension = '\t' + '\t'.join(['0',] * (32-flies) )
        else:
            extension = ''

            
        for line in activity:
            tt = '%02d:%02d:%02d' % (dt.hour, dt.minute, dt.second)
            dt = dt + datetime.timedelta(seconds=1)

            self.__rowline +=1
            row_header = '%s\t'*10 % (self.__rowline, date, tt, active, damscan, tracktype, sleepDep, monitor, unused, light)
            row += row_header + line + extension + '\n'

        if self.outputFile:
            fh = open(self.outputFile, 'a')
            fh.write(row)
            fh.close()
            
    
    def calculateDistances(self):
        """
        Motion is calculated as distance in px per minutes
        """
        
        # shift by one second left flies, seconds, (x,y)
        fs = np.roll(self.fly_one_minute_buffer, -1, axis=1) 
        
        x = self.fly_one_minute_buffer[:,:,:1]
        y = self.fly_one_minute_buffer[:,:,1:]
        
        x1 = fs[:,:,:1]
        y1 = fs[:,:,1:]
        
        d = self.__distance((x,y),(x1,y1))
        #we sum everything BUT the last bit of information otherwise we have data duplication
        values = d[:,:-1,:].sum(axis=1).reshape(-1)
        
        activity = '\t'.join( ['%s' % int(v) for v in values] )
        return activity
            
            
    def calculateVBM(self):
        """
        Motion is calculated as virtual beam crossing
        Detects automatically beam orientation (vertical vs horizontal)
        """

        values = []

        for fd, md in zip(self.fly_one_minute_buffer, self.mask.relativeBeams()):

            (mx1, my1), (mx2, my2) = md
            horizontal = (mx1 == mx2)
            
            fs = np.roll(fd, -1, 0)
            
            x = fd[:,:1]; y = fd[:,1:] # THESE COORDINATES ARE RELATIVE TO THE ROI
            x1 = fs[:,:1]; y1 = fs[:,1:]

            if horizontal:
                crossed = (x < mx1 ) * ( x1 > mx1 ) + ( x > mx1) * ( x1 < mx1 )
            else:
                crossed = (y < my1 ) * ( y1 > my1 ) + ( y > my1) * ( y1 < my1 )
        
            values .append ( crossed.sum() )
        
        activity = '\t'.join( [str(v) for v in values] )
        
        return activity
            
    def calculatePosition(self, resolution=1):
        """
        Simply write out position of the fly at every time interval, as 
        decided by "resolution" (seconds)
        """
        
        activity = []
        rois = self.mask.getROInumber()
        
        a = self.fly_one_minute_buffer.transpose(1,0,2) # ( interval, n_flies, (x,y) )
        a = a.reshape(resolution, -1, rois, 2).mean(0)
        
        for fd in a:
            onerow = '\t'.join( ['%s,%s' % (x,y) for (x,y) in fd] )
            activity.append(onerow)
        
        return activity

    def calculateImmobility(self):
        """
        Check if the flies are asleep for longer than interval (minutes)
        Immobility is based on distance and flies are considered immobile if they have not moved
        for at least threshold (px) * interval during the last interval
        """
        
        #First calculate distance
        fs = np.roll(self.fly_one_minute_buffer, -1, axis=1) 
        x = self.fly_one_minute_buffer[:,:,:1]
        y = self.fly_one_minute_buffer[:,:,1:]
        x1 = fs[:,:,:1]
        y1 = fs[:,:,1:]
        d = self.__distance((x,y),(x1,y1))
        #we sum everything BUT the last bit of information otherwise we have data duplication
        values = d[:,:-1,:].sum(axis=1).reshape(-1)

        #Add the values for distance in the buffer array
        self.flyActivity = np.roll (self.flyActivity, -1, axis=1)
        self.flyActivity[:,-1] = values
        
    
    def sleepDeprive(self, interval=None, threshold=None):
        """
        returns a list of ROIs where flies have not moved during the last interval
        """
        
        if interval == None:
            interval =  self.inactivity_threshold

        if threshold == None and 'FLY_AREA_AVG' in self.debug_info:
            threshold = float (self.debug_info['FLY_AREA_AVG']) * interval
        else:
            threshold = 20 * interval
            
        asleep = self.flyActivity[:,interval:-1].sum(axis=1) < threshold
        ROIstomove = np.where( (asleep==True))[0].tolist()
        
        sleepdeprivator.deprive(ROIstomove, use_serial=True, port=self.SDserialPort)


    def processFlyMovements(self, time):
        """
        Decides what to do with the data
        Called every frame
        
        In the live stream we find the coordinates of the flies multiple time per second
        but we don't need so much information. This function will calculate how much time
        has elapsed from the last time we analysed a frame, calculate the FPS and store the 
        data in buffer that will get processed and saved to file
        """
        
        ct = time
        self.__temp_FPS += 1
        delta = ( ct - self.__last_time)

        if delta >= 1: # if one second has elapsed from last time we went down this IF
            self.__last_time = ct
            self.compactSeconds(self.__temp_FPS, delta) #average the coordinates and transfer from buffer to array
            self.__processingFPS = self.__temp_FPS; self.__temp_FPS = 0

            self.debug_info['FPS'] = self.__processingFPS
         
    def GetImage(self, drawROIs = False, selection=None, crosses=None, timestamp=False, draw_path=False):
        """
        GetImage(self, drawROIs = False, selection=None, timestamp=0)
        
        drawROIs       False        (Default)   Will draw all ROIs to the image
                       True        
        
        selection      (x1,y1,x2,y2)            A four point selection to be drawn
        
        crosses        (x,y),(x1,y1),...        A list of tuples containing single point coordinates
        
        timestamp      True                     Will add a timestamp to the bottom right corner
                       False        (Default)   
                       
        draw_path      True         (Default)   Draw the last steps of each fly to a path
                       False
        
        Returns the last collected image
        """

        ##self.imageCount += 1
        frame, time = self.cam.getImage()
        #print time
        
        # TRACKING RELATED
        if self.isTracking and self.mask.ROIS and frame.any(): 
            frame, positions = self.trackByContours(frame)
            
            # for each frame adds fly coordinates to all ROIS. Also do some filtering to remove false positives
            for (fly_number, fly_coords) in positions:
                
                fly_coords, distance = self.addFlyCoords(fly_number, fly_coords)
                
                if distance > 0:
                    cross_color = (255,255,255)
                else:
                    cross_color = (255,0,0)
                
                # draw position of the fly as cross with or without some verbose
                if fly_coords and self.drawing:
                    frame = self.__drawCross(frame, fly_coords, color=cross_color)
                    #frame = self.__drawCross(frame, fly_coords, text=str(fly_number+1)+str(fly_coords)) 
                
                if draw_path and self.drawing:
                    frame = self.__drawLastSteps(frame, fly_number, steps=5) # draw path of the fly
            
            self.processFlyMovements(time)      
            self.debug_info['DETECTED'] = self.getFliesDetected()

        
        # NOT TRACKING RELATED
        if self.referencePoints == None:
            self.referencePoints = self.findReferenceCircles(frame)
            self.debug_info['REF_POINTS'] = self.referencePoints

        if self.drawing and drawROIs and self.mask.ROIS: # draw ROIs
            ROInum = 0
            for ROI, beam in zip(self.mask.ROIS, self.mask.beams):
                ROInum += 1
                frame = self.__drawROI(frame, ROI, ROInum=ROInum)
                frame = self.__drawBeam(frame, beam)

        #Drawing the reference circles
        if self.drawing and drawROIs:
            
            if self.referencePoints != None :
                #The currently detected circle
                for i in self.referencePoints[0,:]:
                    x, y, r = i
                    cv2.circle(frame,(i[0],i[1]),i[2],(255,255,255),2)
                    frame = self.__drawCross (frame, (x,y), color=(0,0,255))
            
            #The circle in the mask
            if self.mask.referencePoints != ((),()) and self.mask.referencePoints != None:
                for i in self.mask.referencePoints[0,:]:
                    cv2.circle(frame,(i[0],i[1]),i[2],(0,255,0),1)  # draw the outer circle
                    cv2.circle(frame,(i[0],i[1]),2,(0,0,255),3)     # draw the center of the circle

        
        if self.drawing and selection:
            frame = self.__drawROI(frame, selection, color=(0,0,255)) # draw red selection
            
        if self.drawing and crosses:
            for pt in crosses:
                frame = self.__drawCross (frame, pt, color=(0,0,255)) # draw red crosses
            

        if self.drawing and timestamp: 
            frame = self.__drawDebugInfo(frame)
            frame = self.__addTimeStamp(frame, time)

        if self.grabMovie: 
            self.writer.write(frame)
            
        if self.grabMovie and self.isLastFrame():
            self.writer.release()
        
        #self.__image_queue.put(frame)
        self.__image_queue = frame
        return frame

    def getImageFromQueue(self):
        """
        """
        return self.__image_queue
        #return self.__image_queue.get()

    def trackByContours(self, frame, draw_path=True, fliesPerROI=1):
        """
        Track flies in ROIs using findContour algorithm in opencv
        Each frame is compared against the moving average
        take an opencv frame as input and return a frame as output with path, flies and mask drawn on it
        
        draw_path    True | False   draw_path of the fly
        fliesPerROI 1              limit number of flies to be tracked per ROI - not implemented yet
        """
        
        positions = []
        
        # Smooth to get rid of false positives
        # http://opencvpython.blogspot.in/2012/06/smoothing-techniques-in-opencv.html
        # https://github.com/abidrahmank/OpenCV2-Python/blob/master/Official_Tutorial_Python_Codes/3_imgproc/smoothing.py
        frame = cv2.blur(frame,(1,1))
        #frame = cv2.GaussianBlur(frame,(5,5) ,0)

        try:
            # update the moving average
            cv2.accumulateWeighted(frame, self.moving_average, 0.02)
        except:
            # it's our first frame: create the moving average
            self.moving_average = np.float32(frame)
        
        avg = cv2.convertScaleAbs(self.moving_average)

        # Minus the current frame from the moving average.
        difference = cv2.subtract(avg, frame)

        # Convert the image to grayscale.
        grey_image = cv2.cvtColor(difference, cv2.COLOR_BGR2GRAY)

        # Convert the image to black and white.
        ret, thresh = cv2.threshold(grey_image, 20, 255, cv2.THRESH_BINARY)

        # Dilate and erode to get proper blobs
        thresh = cv2.Canny(thresh, 0, 50, apertureSize=5)
        thresh = cv2.dilate(thresh, None)

        y,x,_ = frame.shape
        ROImsk = np.zeros( (y,x), np.uint8)

        # FOR DEBUGGING PURPOSES ONLY
        #draw_frame = cv2.cvtColor(grey_image, cv2.COLOR_GRAY2BGR)
        #draw_frame = difference
        #draw_frame = avg
        #draw_frame = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
        draw_frame = frame

        #ROImsk *= 0
        #if self.mask.getROInumber() :
        #    cv2.fillPoly( ROImsk, np.array(self.mask.ROIS), color=(255, 255, 255) )
        #    ROIwrk = thresh & ROImsk
        #    draw_frame = cv2.cvtColor(ROImsk, cv2.COLOR_GRAY2BGR)


        #track each ROI
        for fly_number, ROIrect in enumerate( self.mask.ROIStoRect() ):

            #Apply the mask to the grey image where tracking happens
            ROImsk *= 0
            realROI = self.mask.getROI(fly_number)
            cv2.fillPoly( ROImsk, np.array([realROI]), color=(255, 255, 255) )
            ROIwrk = thresh & ROImsk
            
            (x1,y1), (x2,y2) = ROIrect

            contours, hierarchy = cv2.findContours(ROIwrk[y1:y2, x1:x2] ,cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE, offset=(x1,y1))
            
            points = []
            fly_coords = FLY_NOT_DETECTED
           
            for nc, cnt in enumerate(contours[:fliesPerROI]): #limit to only n point per contours

                area = cv2.contourArea(cnt)
                avg, std, distance, is_outlier = self.fly_area.update(area)
                
                self.debug_info['FLY_AREA_AVG'] = "%.1f" % avg
                self.debug_info['FLY_AREA_STD'] = "%.1f" % std
                
                (x,y),radius = cv2.minEnclosingCircle(cnt)
                center = (int(x),int(y))
                radius = int(radius)
                
                # centroid
                #moments = cv2.moments(cnt)
                #if moments['m00'] != 0.0:
                    #cx = moments['m10']/moments['m00']
                    #cy = moments['m01']/moments['m00']
                    #center = (cx,cy)
                
                if not is_outlier: 
                    fly_coords = center

                if self.drawing and is_outlier:
                    cv2.circle(draw_frame, center, radius, (0,255,255), 1)
                elif self.drawing and not is_outlier:
                    cv2.circle(draw_frame, center, radius, (0,0,255), 1)

            #Store the positions of the flies in an array
            positions.append( (fly_number, fly_coords) )
        
        return draw_frame, positions

    def findReferenceCircles(self, frame):
        """
        Finds reference circles and return their coordinates as list of tuples
        """
        circles = None

        cframe = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cframe = cv2.medianBlur(cframe,5)
        circles = cv2.HoughCircles(cframe, cv2.cv.CV_HOUGH_GRADIENT, 1, 10, param1=100, param2=30, minRadius=5, maxRadius=20)
        
        if circles != None:
            circles = np.uint16(np.around(circles))

        return circles

        
