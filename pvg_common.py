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


import wx, cv, os
import pysolovideo as pv
import ConfigParser

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
        
        filename = filename or 'config.cfg'
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
        """
        
        if temporary and not filename: filename = self.filename_temp
        elif not temporary and not filename: filename = self.filename
       
        if newfile:
            self.config = ConfigParser.RawConfigParser()
            self.config.add_section('Options')
            
            for key in self.defaultOptions:
                self.config.set('Options', key, self.defaultOptions[key][0])

        with open(filename, 'wb') as configfile:
            self.config.write(configfile)
    
        if not temporary: self.Save(temporary=True)


    def SetValue(self, section, key, value):
        """
        """
        
        if not self.config.has_section(section):
            self.config.add_section(section)
        
        self.config.set(section, key, value)
        
    def GetValue(self, section, key):
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
        return self.GetValue('Options', key)

class pvg_config(myConfig):
    """
    Inheriting from myConfig
    """
    def __init__(self, filename=None, temporary=False):

        
        defaultOptions = { "Monitors" : [9, "Select the number of monitors connected to this machine"],
                            "Webcams"  : [1, "Select the number of webcams connected to this machine"],
                            "ThumbnailSize" : ['320, 240', "Specify the size for the thumbnail previews"], 
                            "FullSize" : ['640, 480', "Specify the size for the actual acquisition from the webcams.\nMake sure your webcam supports this definition"], 
                            "FPS_preview" : [5, "Refresh frequency (FPS) of the thumbnails during preview.\nSelect a low rate for slow computers"],  
                            "FPS_recording" : [5, "Actual refresh rate (FPS) during acquisition and processing"],
                            "Data_Folder" : ['', "Folder where the final data are saved"]
                           }

        self.monitorProperties = ['sourceType', 'source', 'track', 'maskfile', 'trackType']

        myConfig.__init__(self, filename, temporary, defaultOptions)

    def SetMonitor(self, monitor, *args):
        """
        """
        mn = 'Monitor%s' % monitor
        for v, vn in zip( args, self.monitorProperties ):
            self.SetValue(mn, vn, v)
    
    def GetMonitor(self, monitor):
        """
        """
        mn = 'Monitor%s' % monitor
        md = []
        if self.config.has_section(mn):
            for vn in self.monitorProperties:
                md.append ( self.GetValue(mn, vn) )
        return md

    def HasMonitor(self, monitor):
        """
        """
        mn = 'Monitor%s' % monitor
        return self.config.has_section(mn)

        
class previewPanel(wx.Panel):
    """
    A panel showing the video images. 
    Used for thumbnails
    """
    def __init__(self, parent, size, keymode=True):

        wx.Panel.__init__(self, parent, wx.ID_ANY, style=wx.WANTS_CHARS)
        
        self.parent = parent

        self.size = size
        self.SetMinSize(self.size)
        fps = options.GetOption('FPS_preview') or 7
        self.interval = 1000/fps # fps determines refresh interval in ms

        self.SetBackgroundColour('#A9A9A9')

        self.sourceType = 0 
        self.source = ''
        self.mon = None
        self.track = False
        self.trackType = 1
        self.drawROI = True

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
        
        self.Bind( wx.EVT_LEFT_DOWN, self.onLeftDown )
        self.Bind( wx.EVT_LEFT_UP, self.onLeftUp )
        self.Bind( wx.EVT_LEFT_DCLICK, self.AddPoint )
        self.Bind( wx.EVT_MOTION, self.onMotion )
        self.Bind( wx.EVT_RIGHT_DOWN, self.ClearLast )
        self.Bind( wx.EVT_MIDDLE_DOWN, self.SaveCurrentSelection )
        
        if keymode: 
            self.Bind( wx.EVT_CHAR, self.onKeyPressed )
            self.SetFocus()

    def ClearAll(self, event=None):
        """
        Clear all ROIs
        """
        self.mon.delROI(-1)

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

    def onKeyPressed(self, event):
        """
        Regulates key pressing responses:
        a       create auto mask
        c       clear last ROI selected
        x       clear all
        g       start or stop movie grabbing
        j       add current selection
        s       save current mask
        """
        key = chr(event.GetKeyCode())
        
        if key == 'a': self.AutoMask()
        if key == 'c': self.ClearLast()
        if key == 'x': self.ClearAll()
        if key == 'g' and self.mon.writer: self.mon.grabMovie = not self.mon.grabMovie
        if key == 'j': self.SaveCurrentSelection()
        if key == 's': self.SaveMask()
        #if key == '': self.()
            

    def AutoMask(self, event=None):
        """
        """
        pt1, pt2 = self.polyPoints[0], self.polyPoints[1]
        self.mon.autoMask(pt1, pt2)
         

    def SaveMask(self, event=None):
        """
        """
        self.mon.saveROIS()

    def setMonitor(self, camera, resolution):
        """
        """
        
        self.mon = pv.Monitor()
        self.mon.setSource(camera, resolution)
        
        #frame_big = self.mon.GetImage() 
        
        #resize
        frame = cv.CreateMat(self.size[1], self.size[0], cv.CV_8UC3)
        #cv.Resize(frame_big, frame)
        
        #convert colors before transforming to RGB
        #cv.CvtColor(frame, frame, cv.CV_BGR2RGB)
        self.bmp = wx.BitmapFromBuffer(self.size[0], self.size[1], frame.tostring())

        self.Bind(wx.EVT_PAINT, self.onPaint)

        self.playTimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.onNextFrame)

    def paintImg(self, img):
        """
        """

        frame = cv.CreateMat(self.size[1], self.size[0], cv.CV_8UC3)
        cv.Resize(img, frame)

        cv.CvtColor(frame, frame, cv.CV_BGR2RGB)
        self.bmp.CopyFromBuffer(frame.tostring())
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

        self.paintImg( self.mon.GetImage(drawROIs = self.drawROI, selection=self.selection, crosses=self.polyPoints, timestamp=False) )
        if evt: evt.Skip()
      
    def Play(self, status=True, showROIs=True):
        """
        """
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

    def hasMonitor(self):
        """
        """
        return (self.mon != None)

#################

options = pvg_config('config.cfg')
