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

__author__ = "Giorgio Gilestro <giorgio@gilest.ro>"
__version__ = "$Revision: 1.0 $"
__date__ = "$Date: 2011/08/16 21:57:19 $"
__copyright__ = "Copyright (c) 2011 Giorgio Gilestro"
__license__ = "Python"

import os, optparse
from pvg_common import pvg_config, DEFAULT_CONFIG, options
from accessories.sleepdeprivator import sleepdeprivator

import pysolovideo
import cv2

import threading
from time import sleep

import wx
from wx.lib.filebrowsebutton import FileBrowseButton
import wx.grid as gridlib

class partial: #AKA curry
    '''
    This functions allows calling another function upon event trigger and pass arguments to it
    ex buttonA.Bind (wx.EVT_BUTTON, partial(self.Print, 'Hello World!'))
    '''

    def __init__(self, fun, *args, **kwargs):
        self.fun = fun
        self.pending = args[:]
        self.kwargs = kwargs.copy()

    def __call__(self, *args, **kwargs):
        if kwargs and self.kwargs:
            kw = self.kwargs.copy()
            kw.update(kwargs)
        else:
            kw = kwargs or self.kwargs

        return self.fun(*(self.pending + args), **kw)

class comboFileBrowser(wx.ComboBox):
    def __init__(self, parent, id=-1,  pos=(-1,-1), size=(-1,-1), value="", choices=[], style=0, dialogTitle = "Choose a File", startDirectory = ".", fileMask = "*.*", browsevalue="Browse for file", changeCallback= None):
        
        choices = list(set([value] + choices ))
        choices.sort()
        self.fileMask = fileMask
        self.dialogTitle = dialogTitle
        self.startDirectory = startDirectory
        self.defaultFile = value
        self.browsevalue=browsevalue
        self.changeCallback = changeCallback
        
        wx.ComboBox.__init__(self, parent, id, value, pos, size, choices + [browsevalue], style=wx.CB_DROPDOWN | wx.CB_READONLY | wx.CB_SORT)
        self.Bind(wx.EVT_COMBOBOX, self.onItemChanged)
        
    def onItemChanged(self, event):
        """
        """
        if event.GetString() == self.browsevalue:
        
            dlg = wx.FileDialog(
                self, message=self.dialogTitle,
                defaultDir=self.startDirectory,
                defaultFile=self.defaultFile,
                wildcard=self.fileMask,
                style=wx.OPEN | wx.CHANGE_DIR
                )

            if dlg.ShowModal() == wx.ID_OK:
                path = dlg.GetPath()
                __, filename = os.path.split(path)
                self.Append(filename)
                self.SetValue(filename)
                event.SetString(path)
                #self.Command(event)
                
            
            dlg.Destroy()
            
        #event.SetValue(filename)
        self.changeCallback(event=event)
        
            

class pvg_AcquirePanel(wx.Panel):
    def __init__(self, parent):
        
        wx.Panel.__init__(self, parent, wx.ID_ANY)

        self.loadMonitors()
        self.drawPanel()
        
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.updateTimes, self.timer)
        self.dopreview = False


        cv2.namedWindow("preview")
        
    def drawPanel(self):
        """
        """    
        ###################################################

        for child in self.GetChildren():
            child.Destroy()

        mon_num = options.GetOption("Monitors")
        num_cams = options.GetOption("Webcams")
        monitorsData = options.getMonitorsData()
 
        WebcamsList = [ 'Camera %02d' % (int(w) +1) for w in range( num_cams ) ]
        colLabels = ['Status', 'Monitor', 'Source', 'Mask', 'Output', 'Track type', 'Track', 'uptime', 'preview']
        tracktypes = ['DISTANCE','VBS','XY_COORDS']
 
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        gridSizer = wx.FlexGridSizer (cols=len(colLabels), vgap=5, hgap=5)  #wx.BoxSizer(wx.VERTICAL)

        #FIRST ROW
        for key in colLabels:
            text = wx.StaticText(self, -1, key )
            text.SetFont( wx.Font(12, wx.SWISS, wx.NORMAL, wx.BOLD) )
            gridSizer.Add(text, 0, wx.ALL|wx.ALIGN_CENTER, 5)
    
        self.status = []
        self.recordBTNS = []
        self.uptimeTXT = []

        #LOOP THROUGH
        for mn in range(1, mon_num+1):
            
            if not options.HasMonitor(mn): 
                options.SetMonitor(mn) #If monitor does not exist in options we create it
            
            md = options.GetMonitor(mn)
            
            try:
                _, source = os.path.split( md['source'] )
            except:
                source = 'Camera %02d' % ( md['source'] )
            
            _, mf = os.path.split(md['mask_file'])
            df = 'Monitor%02d.txt' % (mn)

            #ICON
            self.status.append( wx.StaticBitmap(self, -1, wx.EmptyBitmap(16,16)) )
            gridSizer.Add(self.status[-1], 0, wx.ALL|wx.ALIGN_CENTER, 5)
            self.changeIcon(mn)
            
            #TEXT
            gridSizer.Add(wx.StaticText(self, -1, "Monitor %s" % mn ), 0, wx.ALL|wx.ALIGN_CENTER, 5)

            #INPUT SOURCE
            gridSizer.Add(comboFileBrowser(self, wx.ID_ANY, size=(-1,-1), dialogTitle = "Choose an Input video file", startDirectory = options.GetOption("Data_Folder"), value = source, choices=WebcamsList, fileMask = "Video File (*.*)|*.*", browsevalue="Browse for video...", changeCallback = partial(self.onChangeDropDown, [mn, "source"])), 0, wx.ALL|wx.ALIGN_CENTER, 5 )
            
            #MASK FILE
            gridSizer.Add(comboFileBrowser(self, wx.ID_ANY, size=(-1,-1), dialogTitle = "Choose a Mask file", startDirectory = options.GetOption("Mask_Folder"), value = mf, fileMask = "pySolo mask file (*.msk)|*.msk", browsevalue="Browse for mask...", changeCallback = partial(self.onChangeDropDown, [mn, "mask_file"])), 0, wx.ALL|wx.ALIGN_CENTER, 5 )
            
            #OUTPUT FILE
            gridSizer.Add(comboFileBrowser(self, wx.ID_ANY, size=(-1,-1), dialogTitle = "Choose the output file", startDirectory = options.GetOption("Data_Folder"), value = md['outputfile'], fileMask = "Output File (*.txt)|*.txt", browsevalue="Browse for output...", changeCallback = partial(self.onChangeDropDown, [mn, "outputfile"])), 0, wx.ALL|wx.ALIGN_CENTER, 5 )

            #TRACKTYPE
            ttcb = wx.ComboBox(self, -1, size=(-1,-1), value=md['track_type'], choices=tracktypes, style=wx.CB_DROPDOWN | wx.CB_READONLY | wx.CB_SORT)
            ttcb.Bind (wx.EVT_COMBOBOX, partial(self.onChangeDropDown, [mn, "track_type"]))
            gridSizer.Add(ttcb , 0, wx.ALL|wx.ALIGN_CENTER, 5)
            
            #RECORD BUTTON
            self.recordBTNS.append ( wx.ToggleButton(self, wx.ID_ANY, 'Start') )
            self.recordBTNS[-1].Bind (wx.EVT_TOGGLEBUTTON, partial( self.onToggleRecording, mn))
            gridSizer.Add(self.recordBTNS[-1], 0, wx.ALL|wx.ALIGN_CENTER, 5)

            #UPTIME
            self.uptimeTXT.append(wx.TextCtrl(self, value="00:00:00", size=(140,-1)))
            gridSizer.Add(self.uptimeTXT[-1], 0, wx.ALL|wx.ALIGN_CENTER, 5)

            #VIEW BUTTON
            vb = wx.Button(self, wx.ID_ANY, 'View')
            vb.Bind(wx.EVT_BUTTON, partial( self.onViewMonitor, mn))
            gridSizer.Add(vb, 0, wx.ALL|wx.ALIGN_CENTER, 5)

        btnSizer = wx.BoxSizer(wx.HORIZONTAL)
        conf_btnSizer = wx.StaticBoxSizer(wx.StaticBox(self, wx.ID_ANY, 'Configuration'), wx.HORIZONTAL)
        acq_btnSizer = wx.StaticBoxSizer(wx.StaticBox(self, wx.ID_ANY, 'Acquisition'), wx.HORIZONTAL)

        self.saveOptionsBtn = wx.Button(self, wx.ID_ANY, 'Save')
        self.saveOptionsBtn.Enable(False)
        self.Bind(wx.EVT_BUTTON, self.onSave, self.saveOptionsBtn)
        conf_btnSizer.Add (self.saveOptionsBtn, 0, wx.ALL, 5) 
        
        self.startBtn = wx.Button(self, wx.ID_ANY, 'Start All')
        self.stopBtn = wx.Button(self, wx.ID_ANY, 'Stop All')
        self.startBtn.Enable(True)
        self.stopBtn.Enable(False)
        self.Bind(wx.EVT_BUTTON, self.onStopAll, self.stopBtn)
        self.Bind(wx.EVT_BUTTON, self.onStartAll, self.startBtn)
        acq_btnSizer.Add (self.startBtn, 0, wx.ALL, 5) 
        acq_btnSizer.Add (self.stopBtn, 0, wx.ALL, 5)

        btnSizer.Add(conf_btnSizer, 0, wx.ALL, 5) 
        btnSizer.Add(acq_btnSizer, 0, wx.ALL, 5) 
        
        #mainSizer.Add(self.FBconfig, 0, wx.EXPAND|wx.ALL, 5) 
        mainSizer.Add(gridSizer, 1, wx.EXPAND, 0)
        mainSizer.Add(btnSizer, 0, wx.ALL, 5)
        mainSizer.Layout()
        self.SetSizer(mainSizer)
        self.Refresh()

    def changeIcon(self, monitor):
        """
        """

        if monitor in self.active_monitors and self.active_monitors[monitor].hasSource():
            bmp = wx.ArtProvider.GetBitmap(wx.ART_TICK_MARK, wx.ART_MESSAGE_BOX, (16,16))
        else:
            bmp = wx.ArtProvider.GetBitmap(wx.ART_WARNING, wx.ART_MESSAGE_BOX, (16,16))
            
        self.status[monitor-1].SetBitmap(bmp)

    def onChangeCheckBox(self, target, event=None):
        """
        """
        self.saveOptionsBtn.Enable(True)
        self.startBtn.Enable(False)
            
        value = event.IsChecked()
        section = "Monitor%s" % target[0]
        keyname = target[1]
        options.setValue(section, keyname, value)
        
    def onChangeDropDown(self, target, event=None):
        """
        """
        self.saveOptionsBtn.Enable(True)
        self.startBtn.Enable(False)
            
        value = event.GetString()
        if "Camera " in value:
            value = int(value.split(" ")[1])
        
        section = "Monitor%s" % target[0]
        keyname = target[1]
        options.setValue(section, keyname, value)


    def onChangeValue(self, target, event=None):
        """
        """
        self.saveOptionsBtn.Enable(True)
        self.startBtn.Enable(False)
        
            
        if event.GetEventType() == wx.EVT_CHECKBOX.evtType:
            value = event.IsChecked()

        #if event.GetEventType() == wx.EVT_COMBOBOX.evtType:
        else:
            value = event.GetString()
            if "Camera " in value:
                value = int(value.split(" ")[1])

        
        section = "Monitor%s" % target[0]
        keyname = target[1]
        options.setValue(section, keyname, value)
        
        
    def loadMonitors(self):
        """
        """

        self.active_monitors = {}
        resolution = options.GetOption("Resolution")
        data_folder = options.GetOption("Data_Folder")
        monitorsData = options.getMonitorsData()
        
        for mn in monitorsData:
            m = monitorsData[mn]
               
            track_type = ['DISTANCE','VBS','XY_COORDS'].index(m['track_type'])
            
            if type(m['source']) == int:
                source = int(m['source']) - 1
            else:
                source = m['source']
                       
            output_file = m['outputfile'] or os.path.join(data_folder, 'Monitor%02d.txt' % mn)
            
            self.active_monitors[mn] = pysolovideo.Monitor()
            success = self.active_monitors[mn].setSource(source, resolution)
            if success:
                self.active_monitors[mn].setTracking(True, track_type, m['mask_file'], output_file)
                self.active_monitors[mn].SDserialPort = m['serial_port']
                self.active_monitors[mn].inactivity_threshold = m['inactivity_threshold'] or None
                #self.changeIcon(mn, 1)
            else:
                #self.changeIcon(mn, -1)
                pass

        pysolovideo.MONITORS = self.active_monitors


    def onStartAll(self, event=None):
        """
        """
        self.stopBtn.Enable(True)
        self.startBtn.Enable(False)
        
        for num, btn in enumerate(self.recordBTNS):
            recording = btn.GetValue()
            if not recording:
                self.onToggleRecording(num+1, force="start")
    
    def onStopAll(self, event):
        """
        """

        self.stopBtn.Enable(False)
        self.startBtn.Enable(True)
        
        for num, btn in enumerate(self.recordBTNS):
            recording = btn.GetValue()
            if recording: self.onToggleRecording(num+1, force="stop")

        
    def onSave(self, event):
        """
        """
        options.Save()
        self.drawPanel()
        self.saveOptionsBtn.Enable(False)
        self.startBtn.Enable(True)
        
    def onToggleRecording(self, monitor, event=None, force=None):
        """
        """
        if monitor in self.active_monitors:
            recording = self.recordBTNS[monitor-1].GetValue()

            if force == "start" or recording: 
                self.active_monitors[monitor].startTracking()
                self.recordBTNS[monitor-1].SetLabelText('Stop')
                self.recordBTNS[monitor-1].SetValue(True)
                self.timer.Start(1000)
            elif force == "stop" or not recording:
                self.recordBTNS[monitor-1].SetLabelText('Start')
                self.active_monitors[monitor].stopTracking()
                self.recordBTNS[monitor-1].SetValue(False)
                self.timer.Stop()

    def onViewMonitor(self, monitor, event=None):
        """
        Called when we hit the "preview" button
        """
        self.dopreview = monitor
        #self.view_thread = threading.Thread(target=self.displayImage())
    
    def displayImage(self):
        """
        Show monitor image on preview window
        """

        #while self.dopreview:
        if self.dopreview:
            frame = self.active_monitors[self.dopreview].getImageFromQueue()
            if frame is not None:
                cv2.imshow("preview", frame)

        
    def updateTimes(self, event):
        """
        """
        for n in range (len(self.active_monitors)):
            if self.active_monitors[n+1].isTracking:
                t, r = self.active_monitors[n+1].getUptime()
                self.uptimeTXT[n].SetValue("%s (%s)" % (t, r))

        self.displayImage()
            

class acquireFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        kwargs["size"] = (980, 600)

        wx.Frame.__init__(self, *args, **kwargs)

        self.sb = wx.StatusBar(self, wx.ID_ANY)
        self.SetStatusBar(self.sb)

        self.acq_panel =  pvg_AcquirePanel(self)
        


if __name__ == '__main__':

    parser = optparse.OptionParser(usage='%prog [options] [argument]', version='%prog version 1.0')
    parser.add_option('-c', '--config', dest='config_file', metavar="CONFIG_FILE", help="The full path to the config file to open")
    parser.add_option('--acquire', action="store_true", default=False, dest='acquire', help="Start acquisition when the program starts")
    parser.add_option('--nogui', action="store_false", default=True, dest='showgui', help="Do not show the graphical interface")

    (cmd_opts, args) = parser.parse_args()

    
    app=wx.PySimpleApp(0)
    frame_acq = acquireFrame(None, -1, '')
    app.SetTopWindow(frame_acq)
    frame_acq.Show(cmd_opts.showgui)

    configfile = cmd_opts.config_file or DEFAULT_CONFIG

    
    app.MainLoop()


    
