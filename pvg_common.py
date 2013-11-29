# -*- coding: utf-8 -*-
#
#       pvg_common.py
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


import wx
import os
import cv2
import pysolovideo as pv
import ConfigParser, threading
import numpy as np

DEFAULT_CONFIG = 'pysolo_video.cfg'

class myConfig():
    """
    Handles program configuration
    Uses ConfigParser to store and retrieve
    From gg's toolbox
    """
    def __init__(self, filename=None, temporary=False, defaultOptions=None):
        """
        filename    the name of the configuration file
        temporary   whether we are reading and storing values temporarily
        defaultOptions  a dict containing the defaultOptions
        """
        
        filename = filename or DEFAULT_CONFIG
        pDir = os.getcwd()
        if not os.access(pDir, os.W_OK): pDir = os.environ['HOME']

        self.filename = os.path.join (pDir, filename)
        self.filename_temp = '%s~' % self.filename
        
        self.config = None
        
        if defaultOptions != None: 
            self.defaultOptions = defaultOptions
        else:
            self.defaultOptions = { "option_1" : [0, "Description"],
                                    }
        
        self.Read(temporary)

    def New(self, filename):
        """
        """
        self.filename = filename
        self.Read()  

    def Read(self, temporary=False):
        """
        read the configuration file. Initiate one if does not exist
        
        temporary       True                Read the temporary file instead
                        False  (Default)     Read the actual file
        """

        if temporary: filename = self.filename_temp
        else: filename = self.filename        
        
        if os.path.exists(filename):
            self.config = ConfigParser.RawConfigParser()
            self.config.read(filename)   
            
        else:
            self.Save(temporary, newfile=True)

                               
    def Save(self, temporary=False, newfile=False, filename=None):
        """
        Save configuration to new file
        """
        
        if temporary and not filename: filename = self.filename_temp
        elif not temporary and not filename: filename = self.filename
       
        groups = set()
       
        if newfile:
            self.config = ConfigParser.RawConfigParser()
            for group in self.getOptionsGroups():
                self.config.add_section(group)
            
            for key in self.defaultOptions:
                group = self.defaultOptions[key][2]
                value = self.defaultOptions[key][0]
                self.config.set(group, key, value)

        with open(filename, 'wb') as configfile:
            self.config.write(configfile)
    
        if not temporary: self.Save(temporary=True)


    def setValue(self, section, key, value):
        """
        """
        
        if not self.config.has_section(section):
            self.config.add_section(section)
        
        self.config.set(section, key, value)
        
    def getValue(self, section, key):
        """
        get value from config file
        Does some sanity checking to return tuple, integer and strings 
        as required.
        """
        r = self.config.get(section, key)
        
        if type(r) == type(0) or type(r) == type(1.0): #native int and float
            return r
        elif type(r) == type(True): #native boolean
            return r
        elif type(r) == type(''):
            r = r.split(',')
        
        if len(r) == 2: #tuple
            r = tuple([int(i) for i in r]) # tuple
        
        elif len(r) < 2: #string or integer
            try:
                r = int(r[0]) #int as text
            except:
                r = r[0] #string
        
        if r == 'False' or r == 'True':
            r = (r == 'True') #bool
        
        return r
                

    def GetOption(self, key):
        """
        """
        section = self.defaultOptions[key][2]
        return self.getValue(section, key)
        
        
    def SetOption(self, key, value):
        """
        """
        section = self.defaultOptions[key][2]
        self.setValue(section, key, value)

    def getOptionDescription(self, key):
        """
        """
        return self.defaultOptions[key][1]    

    def getOptionsGroups(self):
        """
        """
        groups = set()
        for key in self.defaultOptions:
            groups.add (self.defaultOptions[key][2])
        return groups
        
    def getOptionsNames(self, section):
        """
        """
        opts = []
        for key in self.defaultOptions:
            group = self.defaultOptions[key][2]
            if group == section: opts.append(key)
        return opts

class pvg_config(myConfig):
    """
    Inheriting from myConfig
    """
    def __init__(self, filename=None, temporary=False):

        #                   "VAR_Name" : [DEFAULT VALUE, "Description", "Group_name"]
        defaultOptions = { "Monitors" : [1, "Select the number of monitors connected to this machine", "General"],
                            "Webcams"  : [1, "Select the number of webcams connected to this machine", "General"],
                            "ThumbnailSize" : ['320, 240', "Specify the size for the thumbnail previews", "Recording"], 
                            "FullSize" : ['800, 600', "Specify the size for the actual acquisition from the webcams.\nMake sure your webcam supports this definition", "Recording"], 
                            "FPS_preview" : [5, "Refresh frequency (FPS) of the thumbnails during preview.\nSelect a low rate for slow computers", "Recording"],  
                            "FPS_recording" : [15, "Actual refresh rate (FPS) during acquisition and processing", "Recording"],
                            "Data_Folder" : ['.', "Folder where the final data are saved", "Folders"],
                            "Mask_Folder" : ['.', "Folder where the masks are found", "Folders"],
                           }

        self.monitorProperties = ['sourceType', 'source', 'track', 'maskfile', 'trackType', 'isSDMonitor']

        myConfig.__init__(self, filename, temporary, defaultOptions)

    def SetMonitor(self, monitor, *args):
        """
        """
        mn = 'Monitor%s' % monitor
        for v, vn in zip( args, self.monitorProperties ):
            self.setValue(mn, vn, v)
    
    def GetMonitor(self, monitor):
        """
        """
        mn = 'Monitor%s' % monitor
        md = []
        if self.config.has_section(mn):
            for vn in self.monitorProperties:
                md.append ( self.getValue(mn, vn) )
        return md

    def HasMonitor(self, monitor):
        """
        """
        mn = 'Monitor%s' % monitor
        return self.config.has_section(mn)

    def getMonitorsData(self):
        """
        return a list containing the monitors that we need to track 
        based on info found in configfile
        """
        monitors = {}
        
        ms = self.GetOption('Monitors')
        resolution = self.GetOption('FullSize')
        dataFolder = self.GetOption('Data_Folder')
        
        for mon in range(1,ms+1):
            if self.HasMonitor(mon):
                _,source,track,mask_file,track_type,isSDMonitor = self.GetMonitor(mon)
                monitors[mon] = {}
                monitors[mon]['source'] = source
                monitors[mon]['resolution'] = resolution
                monitors[mon]['mask_file'] = mask_file
                monitors[mon]['track_type'] = track_type
                monitors[mon]['dataFolder'] = dataFolder
                monitors[mon]['track'] = track
                monitors[mon]['isSDMonitor'] = isSDMonitor
            
        return monitors
        
        
class acquireObject():
    def __init__(self, monitor, source, resolution, mask_file, track, track_type, data_folder=None, output_file=None):
        """
        """
        self.monitor = monitor
        self.source = source
        self.keepGoing = False
        self.verbose = False
        self.track = track
        
        if not data_folder:
            data_folder = os.getcwd()
        
        if not output_file:
            output_file = os.path.join(data_folder, 'Monitor%02d.txt' % monitor)
        
        self.mon = pv.Monitor()
        self.mon.setSource(source, resolution)
        self.mon.setTracking(True, track_type, mask_file, output_file)
        
        if self.verbose: print ( "Setting monitor %s with source %s and mask %s. Output to %s " % (monitor, source, os.path.split(mask_file)[1], os.path.split(output_file)[1] ) )

    def run(self, kbdint=False):
        """
        """
        while self.keepGoing and not self.mon.isLastFrame():
            self.mon.GetImage()
                
    def start(self):
        """
        """
        self.keepGoing = True
        self.run()

    def halt(self):
        """
        """
        self.keepGoing = False
        if self.verbose: print ( "Stopping capture" )
        
    def debug(self):
        """
        """
        print self.mon.debug_info

    def snapshot(self):
        """
        """
        filename = "%s.jpg" % self.source
        frame = self.mon.GetImage()
        cv2.imwrite(filename, frame)

class acquireThread(threading.Thread):

    def __init__(self, monitor, source, resolution, mask_file, track, track_type, dataFolder):
        """
        """
        threading.Thread.__init__(self)
        self.monitor = monitor
        self.keepGoing = False
        self.verbose = False
        self.track = track
        outputFile = os.path.join(dataFolder, 'Monitor%02d.txt' % monitor)
        
        self.mon = pv.Monitor()
        self.mon.setSource(source, resolution)
        self.mon.setTracking(True, track_type, mask_file, outputFile)
        
        if self.verbose: print ( "Setting monitor %s with source %s and mask %s. Output to %s " % (monitor, source, os.path.split(mask_file)[1], os.path.split(outputFile)[1] ) )

    def run(self, kbdint=False):
        """
        """
        
        if kbdint:
        
            while self.keepGoing:
                try:
                    self.mon.GetImage()
                except KeyboardInterrupt:
                    self.halt()
                    
        else:
            while self.keepGoing:
                self.mon.GetImage()
                
    def doTrack(self):
        """
        """
        self.keepGoing = True
        self.start()

    def halt(self):
        """
        """
        self.keepGoing = False
        if self.verbose: print ( "Stopping capture" )



class cvPanel():
    """
    A panel showing the video images. 
    Fully based on CV and not WX
    """

    def __init__(self, source, resolution=None, window_title='video',track_type=None, mask_file=None, output_file=None, showROI=False,showpath=False, showtime=False):
        """
        """
    
        self.title = window_title
        self.resolution = resolution
        self.showROI = showROI
        self.timestamp = showtime
        self.showpath = showpath
        track = ( track_type > -1 )

        self.mon = pv.Monitor()
        self.mon.setSource(source, resolution)
        self.mon.setTracking(track, track_type, mask_file, output_file)
        
        cv2.namedWindow(self.title, cv2.CV_WINDOW_AUTOSIZE)

    def play(self):
        """
        """
        frame = self.mon.GetImage()    
        while not self.mon.isLastFrame():
            cv2.imshow( self.title, frame )
            frame = self.mon.GetImage(drawROIs = self.showROI, selection=None, crosses=None, timestamp=self.timestamp, draw_path=self.showpath)

            key = cv2.waitKey(20)
            if key > 0: # exit on ESC
                break
        
class previewPanel(wx.Panel):
    """
    A panel showing the video images. 
    Used for thumbnails
    """
    def __init__(self, parent, size, keymode=True, singleFrameMode=False, showtime=False):

        wx.Panel.__init__(self, parent, wx.ID_ANY, style=wx.WANTS_CHARS)
        
        self.parent = parent

        self.size = size
        self.SetMinSize(self.size)
        fps = options.GetOption('FPS_preview') or 25
        self.interval = 1000/fps # fps determines refresh interval in ms

        self.SetBackgroundColour('#A9A9A9')

        self.sourceType = 0 
        self.source = ''
        self.mon = None
        self.track = False
        self.isSDMonitor = False
        self.trackType = 1
        self.drawROI = True
        self.timestamp = showtime
        self.camera = None
        self.resolution = None

        self.recording = False
        self.isPlaying = False

        self.allowEditing = True
        self.dragging = None        # Set to True while dragging
        self.startpoints = None     # Set to (x,y) when mouse starts drag
        self.track_window = None    # Set to rect when the mouse drag finishes
        self.selection = None
        self.selROI = -1
        self.polyPoints = []
        self.keymode = keymode
        self.digitBuffer = ''
        
        self.ACTIONS = {
                        "a": [self.autoDivideMask, "Automatically create the mask"],
                        "c": [self.ClearLast, "Clear last selected area of interest"],
                        "t": [self.Calibrate, "Calibrate the mask after selecting two points distant 1cm from each other"],
                        "x": [self.ClearAll, "Clear all marked region of interest"],
                        "j": [self.SaveCurrentSelection, "Save last marked area of interest"],
                        "s": [self.SaveMask, "Save mask to file"],
                        "q": [self.Stop, "Close connection to camera"]
                        }
        
        self.singleFrameMode = singleFrameMode
        
        self.Bind( wx.EVT_LEFT_DOWN, self.onLeftDown )
        self.Bind( wx.EVT_LEFT_UP, self.onLeftUp )
        self.Bind( wx.EVT_LEFT_DCLICK, self.AddPoint )
        self.Bind( wx.EVT_MOTION, self.onMotion )
        self.Bind( wx.EVT_RIGHT_DOWN, self.ClearLast )
        self.Bind( wx.EVT_MIDDLE_DOWN, self.SaveCurrentSelection )
        



####### FUNCTIONS LINKED TO THE DRAWING OF THE ROIS #######

    def ClearAll(self, event=None):
        """
        Clear all ROIs
        """
        self.mon.delROI(-1)

    def CloneLast(self, event=None):
        """
        Clone the last drawn ROI and place it so that its center will
        be the point selected by the user
        """
        
        if self.allowEditing and self.mon.hasROI():
            self.selection = None
            self.polyPoints = []

            x = event.GetX()
            y = event.GetY()
            
            (x1,y1),(x2,y2),(x3,y3),(x4,y4) = self.mon.getROI(-1)
            
            mx1 = min(x1,x2,x3,x4) + (max(x1,x2,x3,x4) - min(x1,x2,x3,x4))/2
            my1 = min(y1,y2,y3,y4) + (max(y1,y2,y3,y4) - min(y1,y2,y3,y4))/2
            
            dx = x - mx1
            dy = y - my1
            
            self.selection = (x1+dx,y1+dy),(x2+dx,y2+dy),(x3+dx,y3+dy),(x4+dx,y4+dy)

            self.mon.addROI(self.selection, 1)
            self.selection = None
            self.polyPoints = []
            
            
    def ClearLast(self, event=None):
        """
        Cancel current drawing
        """
       
        if self.allowEditing:
            self.selection = None
            self.polyPoints = []
            
            if self.selROI >= 0:
                self.mon.delROI(self.selROI)
                self.selROI = -1

    def SaveCurrentSelection(self, event=None):
        """
        save current selection
        """
        if self.allowEditing and not self.selection:
            self.CloneLast(event)

        if self.allowEditing and self.selection:
            self.mon.addROI(self.selection, 1)
            self.selection = None
            self.polyPoints = []
            
           
        
    def AddPoint(self, event=None):
        """
        Add point
        """
        
        if self.allowEditing:
            if len(self.polyPoints) == 4:
                self.polyPoints = []
            
            #This is to avoid selecting a neigh. area when drawing point
            self.selection = None
            self.selROI = -1 
            
            x = event.GetX()
            y = event.GetY()
            self.polyPoints.append( (x,y) )

    
    def onLeftDown(self, event=None):
        """
        """
        
        if self.allowEditing and self.mon:
            x = event.GetX()
            y = event.GetY()
            r = self.mon.isPointInROI ( (x,y) )

            if r < 0:
                self.startpoints = (x, y)
            else:
                self.selection = self.mon.getROI(r)
                self.selROI = r
        
    def onLeftUp(self, event=None):
        """
        """
        if self.allowEditing:
            self.dragging = None
            self.track_window = self.selection
            
            if len(self.polyPoints) == 4:
                self.selection = self.polyPoints
                self.polyPoints = []
            
    def onMotion(self, event=None):
        """
        """
        if self.allowEditing:
            x = event.GetX()
            y = event.GetY()
            
            self.dragging = event.Dragging()
            
            if self.dragging:
                xmin = min(x, self.startpoints[0])
                ymin = min(y, self.startpoints[1])
                xmax = max(x, self.startpoints[0])
                ymax = max(y, self.startpoints[1])
                
                x1, y1, x2, y2  = (xmin, ymin, xmax, ymax)
                self.selection = (x1,y1), (x2,y1), (x2,y2), (x1, y2)

    def prinKeyEventsHelp(self, event=None):
        """
        """
        for key in self.ACTIONS:
            print "%s\t%s" % (key, self.ACTIONS[key][1])

    def onKeyPressed(self, event):
        """
        Regulates key pressing responses:
        """
        key = chr(event.GetKeyCode())
        
        if ( key >= '0' and key <= '9' ): #is digit
            self.digitBuffer = self.digitBuffer + key
        
        if key == "g" and self.mon.writer: self.mon.grabMovie = not self.mon.grabMovie

        if self.ACTIONS.has_key(key):
            self.ACTIONS[key][0]()
    
    def Calibrate(self, event=None):
        """
        """
        if len(self.polyPoints) > 2:
            print "You need only two points for calibration. I am going to use the first two"
            
        pt1, pt2 = self.polyPoints[0], self.polyPoints[1]
        r = self.mon.calibrate(pt1, pt2)
        self.polyPoints = []  
        
        print "%spixels = 1cm" % r

    def autoDivideMask(self, n=1):
        """
        Divide the currently selected ROI into n pieces
        if n=0, add one piece
        TODO: ADD CUSTOM FEATURES FOR MASK
        """

        vertical = True

        if self.digitBuffer: n = int(self.digitBuffer)
        self.digitBuffer = ''

        if self.allowEditing and self.selection:
            
            a = np.array(self.selection)
           
            if not vertical and n>1:
                lx = np.linspace(a[0][0],a[2][0],n+1) # new lower X values
                ly = np.linspace(a[0][1],a[2][1],n+1) # new lower Y values
                lv = np.append( lx.reshape(-1,1), ly.reshape(-1,1), 1).astype(np.int)
                
                ux = np.linspace(a[1][0],a[3][0],n+1) # new upper X values
                uy = np.linspace(a[1][1],a[3][1],n+1) # new upper Y values
                uv = np.append( ux.reshape(-1,1), uy.reshape(-1,1), 1).astype(np.int)
            
                for i in range(0,n):
                    self.selection = [ tuple(lv[i].tolist()), tuple(lv[i+1].tolist()), tuple(uv[i+1].tolist()), tuple(uv[i].tolist()) ]
                    self.mon.addROI( self.selection, 1)
            
                self.polyPoints = []
                self.selection = []

            if vertical and n>1:
                lx = np.linspace(a[0][0],a[1][0],n+1) # new left X values
                ly = np.linspace(a[0][1],a[1][1],n+1) # new left Y values
                lv = np.append( lx.reshape(-1,1), ly.reshape(-1,1), 1).astype(np.int)
                
                ux = np.linspace(a[2][0],a[3][0],n+1) # new right X values
                uy = np.linspace(a[2][1],a[3][1],n+1) # new right Y values
                uv = np.append( ux.reshape(-1,1), uy.reshape(-1,1), 1).astype(np.int)
            
                for i in range(0,n):
                    self.selection = [ tuple(lv[i].tolist()), tuple(lv[i+1].tolist()), tuple(uv[i+1].tolist()), tuple(uv[i].tolist()) ]
                    self.mon.addROI( self.selection, 1)
            
                self.polyPoints = []
                self.selection = []

            
    
    def AutoMask(self, event=None):
        """
        """
        pt1, pt2 = self.polyPoints[0], self.polyPoints[1]
        self.mon.autoMask(pt1, pt2)
        self.polyPoints = []

    def SaveMask(self, event=None):
        """
        """
        self.mon.saveROIS()


###########################################################

######### REFRESH AND PAINTING OF THE PANEL ###############

        
    def setMonitor(self, camera, resolution=None):
        """
        """
        
        if not resolution: resolution = self.size
        
        self.camera = camera
        self.resolution = resolution

        self.mon = pv.Monitor()
        self.mon.setSource(self.camera, self.resolution)
        frame = self.mon.GetImage(drawROIs = self.drawROI, selection=self.selection, crosses=self.polyPoints, timestamp=self.timestamp)

        self.bmp = wx.BitmapFromBuffer(self.size[0], self.size[1], frame)

        self.Bind(wx.EVT_PAINT, self.onPaint)
        self.playTimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.onNextFrame)

        if self.keymode: 
            self.Bind( wx.EVT_CHAR, self.onKeyPressed )
            self.SetFocus()
        

    def paintImg(self, frame):
        """
        """
        if frame.any():
            height, width, _ = frame.shape
            
            #if resize:
                #frame = cv2.resize(frame, size)

            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            self.bmp.CopyFromBuffer(frame)
            self.Refresh()

    def onPaint(self, evt):
        """
        """
        if self.bmp:
            dc = wx.BufferedPaintDC(self)
            self.PrepareDC(dc)
            dc.DrawBitmap(self.bmp, 0, 0, True)
            
            
        evt.Skip()

    def onNextFrame(self, evt):
        """
        """
        
        frame = self.mon.GetImage(drawROIs = self.drawROI, selection=self.selection, crosses=self.polyPoints, timestamp=self.timestamp)
        self.paintImg( frame )
        if evt: evt.Skip()
      
    def Play(self, status=True, showROIs=True):
        """
        """

        if self.camera != None and self.resolution != None and not self.mon.hasSource():
            self.mon.setSource(self.camera, self.resolution)

        if self.mon:
            self.drawROI = showROIs
            self.isPlaying = status
            
            if status:
                self.playTimer.Start(self.interval)
            else:
                self.playTimer.Stop()
            
    def Stop(self):
        """
        """
        self.Play(False)
        self.mon.close()

    def hasMonitor(self):
        """
        """
        return (self.mon != None)

#################

options = pvg_config(DEFAULT_CONFIG)
