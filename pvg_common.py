#!/usr/bin/env python2
# -*- coding: utf-8 -*-
#
#       pvg_common.py
#       
#       Copyright 2011 Giorgio Gilestro <gg@bio-ggilestr>
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
from configobj import ConfigObj


class pvg_config():
    '''
    Handles program configuration
    Uses ConfigParser to store and retrieve
    '''
    def __init__(self, filename='config.cfg', temporary=False):
        
        self.filename = filename
        self.filename_temp = '%s~' % self.filename
        
        self.config = None
        self.defaultOptions = { "Monitors" : 9, 
                                "Webcams"  : 1,
                                "ThumbnailSize" : (320, 240),
                                "FullSize" : (800, 600)
                               }

        self.monitorProperties = ['sourceType', 'source', 'track', 'maskfile']
        self.Read(temporary)

    def Read(self, temporary=False):
        '''
        read the configuration file. Initiate one if does not exist
        
        temporary       True                Read the temporary file instead
                        False  (Default)     Read the actual file
        '''

        if temporary: filename = self.filename_temp
        else: filename = self.filename        
        
        if os.path.exists(filename):
            self.config = ConfigObj(filename)
        else:
            self.Save(temporary, newfile=True)

                               
    def Save(self, temporary=False, newfile=False):
        '''
        '''
        if temporary: filename = self.filename_temp
        else: filename = self.filename
            
        if newfile:
            self.config = ConfigObj(filename)
            self.config['Options'] = {}
            
            for key in self.defaultOptions:
                self.config['Options'][key] = self.defaultOptions[key]

        self.config.write()

        if not temporary: self.Save(temporary=True)


    def SetValue(self, section, key, value):
        '''
        '''
        if not self.config.has_key(section):
            self.config[section]={}
        
        self.config[section][key] = value
        
        
    def GetValue(self, section, key):
        '''
        '''
        r = self.config[section][key]
        
        if type(r) == type([]) and len(r) == 2: #tuple
            r = tuple([int(i) for i in r])
        
        else:
            try:
                r = int(r)
            except:
                pass
            
        return r
                

    def GetOption(self, key):
        '''
        '''
        return self.GetValue('Options', key)
        
    def SetMonitor(self, monitor, *args):
        '''
        '''
        mn = 'Monitor%s' % monitor
        for v, vn in zip( args, self.monitorProperties ):
            self.SetValue(mn, vn, v)
    
    def GetMonitor(self, monitor):
        '''
        '''
        mn = 'Monitor%s' % monitor
        md = []
        for vn in self.monitorProperties:
            md.append ( self.GetValue(mn, vn) )
        return md
        
class previewPanel(wx.Panel):
    '''
    A panel showing the video images. 
    Used for thumbnails
    '''
    def __init__(self, parent, size):

        wx.Panel.__init__(self, parent, wx.ID_ANY)
        
        self.parent = parent 

        self.size = size
        self.SetMinSize(self.size)
        fps = 15 ; self.interval = 1000/fps # fps determines refresh interval in ms

        self.SetBackgroundColour('#A9A9A9')

        self.sourceType = 0 
        self.source = ''
        self.mon = None
        self.track = False


        self.recording = False
        self.isPlaying = False

        self.allowEditing = True
        self.dragging = None        # Set to True while dragging
        self.startpoints = None     # Set to (x,y) when mouse starts drag
        self.track_window = None    # Set to rect when the mouse drag finishes
        self.selection = None
        self.selROI = -1
        self.polyPoints = []
        
        self.Bind( wx.EVT_LEFT_DOWN, self.onLeftDown )
        self.Bind( wx.EVT_LEFT_UP, self.onLeftUp )
        self.Bind( wx.EVT_LEFT_DCLICK, self.AddPoint )
        self.Bind( wx.EVT_MOTION, self.onMotion )
        self.Bind( wx.EVT_RIGHT_DOWN, self.ClearLast )
        self.Bind( wx.EVT_MIDDLE_DOWN, self.SaveCurrentSelection )

    def ClearAll(self, event=None):
        '''
        Clear all ROIs
        '''
        self.fsPanel.mon.delROI(-1)

    def ClearLast(self, event=None):
        '''
        Cancel current drawing
        '''
       
        if self.allowEditing:
            self.selection = None
            self.polyPoints = []
            
            if self.selROI >= 0:
                self.mon.delROI(self.selROI)
                self.selROI = -1

    def SaveCurrentSelection(self, event=None):
        '''
        save current selection
        '''
        if self.allowEditing:
            self.mon.addROI(self.selection, 1)
            self.selection = None
            self.polyPoints = []
        
    def AddPoint(self, event=None):
        '''
        Add point
        '''
        
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
        '''
        '''
        
        if self.allowEditing:
            x = event.GetX()
            y = event.GetY()
            r = self.mon.isPointInROI ( (x,y) )

            if r < 0:
                self.startpoints = (x, y)
            else:
                self.selection = self.mon.getROI(r)
                self.selROI = r
        
    def onLeftUp(self, event=None):
        '''
        '''
        if self.allowEditing:
            self.dragging = None
            self.track_window = self.selection
            
            if len(self.polyPoints) == 4:
                self.selection = self.polyPoints
                self.polyPoints = []
            
    def onMotion(self, event=None):
        '''
        '''
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

    def AutoMask(self, event=None):
        '''
        '''
        pt1, pt2 = self.polyPoints[0], self.polyPoints[1]
        self.mon.autoMask(pt1, pt2)
         

    def setMonitor(self, camera, resolution, srcType):
        '''
        '''
        
        self.mon = pv.Monitor()
        
        if srcType == 0:
            self.mon.CaptureFromCAM ( devnum=camera, resolution=resolution)
        elif srcType == 1:
            self.mon.CaptureFromMovie (camera, resolution=resolution)
        elif srcType == 2:
            self.mon.CaptureFromFrames (camera, resolution=resolution)
        
        frame_big = self.mon.GetImage() 
        
        #resize
        frame = cv.CreateMat(self.size[1], self.size[0], cv.CV_8UC3)
        cv.Resize(frame_big, frame)
        
        #convert colors before transforming to RGB
        cv.CvtColor(frame, frame, cv.CV_BGR2RGB)
        self.bmp = wx.BitmapFromBuffer(self.size[0], self.size[1], frame.tostring())

        self.Bind(wx.EVT_PAINT, self.onPaint)

        self.playTimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.onNextFrame)

    def paintImg(self, img):
        '''
        '''

        frame = cv.CreateMat(self.size[1], self.size[0], cv.CV_8UC3)
        cv.Resize(img, frame)

        if frame:
            cv.CvtColor(frame, frame, cv.CV_BGR2RGB)
            self.bmp.CopyFromBuffer(frame.tostring())
            self.Refresh()

    def onPaint(self, evt):
        '''
        '''
        if self.bmp:
            dc = wx.BufferedPaintDC(self)
            self.PrepareDC(dc)
            dc.DrawBitmap(self.bmp, 0, 0, True)
        evt.Skip()

    def onNextFrame(self, evt):
        '''
        '''

        self.paintImg( self.mon.GetImage(drawROIs = True, selection=self.selection, crosses=self.polyPoints) )
        if evt: evt.Skip()
      
    def Play(self, status=True):
        '''
        '''

        self.isPlaying = status
        if status:
            self.playTimer.Start(self.interval)
        else:
            self.playTimer.Stop()
            
    def Stop(self):
        '''
        '''
        self.Play(False)

    def hasMonitor(self):
        '''
        '''
        return (self.mon != None)

#################

options = pvg_config()
