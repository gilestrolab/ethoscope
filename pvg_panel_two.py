#!/usr/bin/env python2
# -*- coding: utf-8 -*-
#
#       untitled.py
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

import wx, os
from pvg_common import previewPanel, options

class fullSizePanel(previewPanel):
    '''
    A small preview Panel to be used as thumbnail
    '''
    
    def __init__(self, parent, size):
        previewPanel.__init__(self, parent, size)
        
        
class panelLiveView(wx.Panel):
    '''
    Panel Number 2
    Live view of selected camera
    '''
    def __init__(self, *args, **kwds):
        '''
        '''
        wx.Panel.__init__(self, *args, **kwds)

        self.monitor_number = options.GetOption("Monitors")
        self.fs_size = options.GetOption("FullSize")
        self.monitor_name = ''

        self.fsPanel = fullSizePanel(self, size=self.fs_size) 

        sizer_1 = wx.BoxSizer(wx.VERTICAL)
        sizer_2 = wx.BoxSizer(wx.HORIZONTAL)
        sizer_3 = wx.BoxSizer(wx.HORIZONTAL)
        sizer_4 = wx.BoxSizer(wx.VERTICAL)
        
        #Static box1: monitor input
        sb_1 = wx.StaticBox(self, -1, "Select Monitor")#, size=(250,-1))
        sbSizer_1 = wx.StaticBoxSizer (sb_1, wx.VERTICAL)
        self.MonitorList = ['Monitor %s' % (int(m) + 1) for m in range(self.monitor_number)]
        self.thumbnailNumber = wx.ComboBox(self, -1, size=(-1,-1) , choices=self.MonitorList, style=wx.CB_DROPDOWN | wx.CB_READONLY | wx.CB_SORT)
        self.Bind(wx.EVT_COMBOBOX, self.onChangeMonitor, self.thumbnailNumber)

        sbSizer_1.Add ( self.thumbnailNumber, 0, wx.ALIGN_CENTRE|wx.LEFT|wx.RIGHT|wx.TOP, 5 )

        #Static box2: mask parameters
        sb_2 = wx.StaticBox(self, -1, "Mask Editing")#, size=(250,-1))
        sbSizer_2 = wx.StaticBoxSizer (sb_2, wx.VERTICAL)
        fgSizer_1 = wx.FlexGridSizer( 0, 2, 0, 0 )
        
        self.btnClear = wx.Button( self, wx.ID_ANY, label="Clear All")
        self.Bind(wx.EVT_BUTTON, self.fsPanel.ClearAll, self.btnClear)

        self.btnClearLast = wx.Button( self, wx.ID_ANY, label="Clear selected")
        self.Bind(wx.EVT_BUTTON, self.fsPanel.ClearLast, self.btnClearLast)


        self.btnAutoFill = wx.Button( self, wx.ID_ANY, label="Auto Fill")
        self.Bind(wx.EVT_BUTTON, self.fsPanel.AutoMask, self.btnAutoFill)

        fgSizer_1.Add (self.btnClear)
        fgSizer_1.Add (self.btnClearLast)
        fgSizer_1.Add (self.btnAutoFill)
        
        sbSizer_2.Add (fgSizer_1)


        #Static box3: mask I/O
        sb_3 = wx.StaticBox(self, -1, "Mask File")#, size=(250,-1))
        sbSizer_3 = wx.StaticBoxSizer (sb_3, wx.VERTICAL)

        self.currentMaskTXT = wx.TextCtrl (self, -1, "No Mask Loaded", style=wx.TE_READONLY)

        btnSizer_1 = wx.BoxSizer(wx.HORIZONTAL)
        self.btnLoad = wx.Button( self, wx.ID_ANY, label="Load Mask")
        self.Bind(wx.EVT_BUTTON, self.onLoadMask, self.btnLoad)
        self.btnSave = wx.Button( self, wx.ID_ANY, label="Save Mask")
        self.Bind(wx.EVT_BUTTON, self.onSaveMask, self.btnSave)
        btnSizer_1.Add(self.btnLoad)
        btnSizer_1.Add(self.btnSave)

        sbSizer_3.Add ( self.currentMaskTXT, 0, wx.ALIGN_CENTRE|wx.LEFT|wx.RIGHT|wx.TOP|wx.EXPAND, 5 )
        sbSizer_3.Add (btnSizer_1, 0, wx.ALIGN_CENTRE|wx.LEFT|wx.RIGHT|wx.TOP, 5 )

        ##
        
        #Static box4: help
        sb_4 = wx.StaticBox(self, -1, "Help")
        sbSizer_4 = wx.StaticBoxSizer (sb_4, wx.VERTICAL)
        titleFont = wx.Font(10, wx.SWISS, wx.NORMAL, wx.BOLD)
        instr = [ ('Left mouse button - single click outside ROI', 'Start dragging ROI. ROI will be a perfect rectangle'),
                  ('Left mouse button - single click inside ROI', 'Select ROI. ROI turns red.'),
                  ('Left mouse button - double click', 'Select corner of ROI. Will close ROI after fourth selection'),
                  ('Middle mouse button - single click', 'Add currently selected ROI. ROI turns white.'),
                  ('Right mouse button - click', 'Remove selected currently selected ROI'),
                  ('Auto Fill', 'Will fill 32 ROIS (16x2) to fit under the last two\nselected points. To use select first upper left corner,\n then the lower right corner, then hit the Auto Fill Button.')
                  ]
                  
        for title, text in instr:
            t = wx.StaticText(self, -1, title); t.SetFont(titleFont)
            sbSizer_4.Add( t, 0, wx.ALL, 2 )
            sbSizer_4.Add(wx.StaticText(self, -1, text) , 0 , wx.ALL, 2 )
            sbSizer_4.Add ( (wx.StaticLine(self)), 0, wx.EXPAND|wx.TOP|wx.BOTTOM, 5 )
        
        sizer_4.Add(sbSizer_1, 0, wx.ALIGN_CENTRE|wx.LEFT|wx.RIGHT|wx.TOP|wx.EXPAND, 5 )
        sizer_4.Add(sbSizer_2, 0, wx.ALIGN_CENTRE|wx.LEFT|wx.RIGHT|wx.TOP|wx.EXPAND, 5 )
        sizer_4.Add(sbSizer_3, 0, wx.ALIGN_CENTRE|wx.LEFT|wx.RIGHT|wx.TOP|wx.EXPAND, 5 )
        sizer_4.Add(sbSizer_4, 0, wx.ALIGN_CENTRE|wx.LEFT|wx.RIGHT|wx.TOP|wx.EXPAND, 5 )

        
        sizer_3.Add(self.fsPanel, 0, wx.LEFT|wx.TOP, 20 )
        sizer_3.Add(sizer_4, 0, wx.ALIGN_RIGHT|wx.LEFT|wx.RIGHT|wx.TOP, 5 )

        sizer_1.Add(sizer_3, 0, wx.ALIGN_CENTRE|wx.LEFT|wx.RIGHT|wx.TOP, 5 )
        sizer_1.Add(sizer_2, 0, wx.ALIGN_CENTRE|wx.LEFT|wx.RIGHT|wx.TOP, 5 )

        
        self.SetSizer(sizer_1) 

    def onChangeMonitor(self, event):
        '''
        '''
        
        if self.fsPanel.isPlaying: self.fsPanel.Stop()
        
        sel = self.monitor_name = event.GetString()
        m = self.monitor_number = self.MonitorList.index(sel)
        
        n_cams = options.GetOption("Webcams")
        WebcamsList = [ 'Webcam %s' % (int(w) +1) for w in range( n_cams ) ]
        
        md = options.GetMonitor(self.monitor_number)
        
        if md:
            self.fsPanel.sourceType, self.fsPanel.source, self.fsPanel.track, self.mask_file = md
        else:
            self.fsPanel.sourceType, self.fsPanel.source, self.fsPanel.track, self.mask_file = [0, '', False, '']
        
        
        if self.fsPanel.sourceType > 0:
            camera = {  
                'path' : self.fsPanel.source,
                'start': None,
                'step' : None,
                'end'  : None,
                'loop' : False
            }
        else:
            camera = WebcamsList.index(self.fsPanel.source)
        
        #if not self.fsPanel.hasMonitor():
        self.fsPanel.setMonitor(camera, self.fs_size , self.fsPanel.sourceType)
        
        if self.fsPanel.hasMonitor(): self.fsPanel.Play()
            
        if self.mask_file:
            self.fsPanel.mon.loadROIS(self.mask_file)
        
        self.currentMaskTXT.SetValue(os.path.split(self.mask_file)[1] or '')

    def onSaveMask(self, event):
        '''
        Save ROIs to File
        '''
        
        filename = '%s.msk' % self.monitor_name
        wildcard = "pySolo mask file (*.msk)|*.msk|"
        
        dlg = wx.FileDialog(
            self, message="Save file as ...", defaultDir=os.getcwd(), 
            defaultFile=filename, wildcard=wildcard, style=wx.SAVE
            )

        #dlg.SetFilterIndex(2)

        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self.fsPanel.mon.saveROIS(path)
            self.currentMaskTXT.SetValue(os.path.split(path)[1])
        
        dlg.Destroy()

    def onLoadMask(self, event):
        '''
        Load Mask from file
        '''
        
        wildcard = "pySolo mask file (*.msk)|*.msk|"
        
        dlg = wx.FileDialog(
            self, message="Choose a file",
            defaultDir=os.getcwd(),
            defaultFile="",
            wildcard=wildcard,
            style=wx.OPEN | wx.CHANGE_DIR
            )

        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self.fsPanel.mon.loadROIS(path)
            self.currentMaskTXT.SetValue(os.path.split(path)[1])
        
        dlg.Destroy()
       

