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
from pvg_common import pvg_config, acquireThread, DEFAULT_CONFIG, options, NO_SERIAL_PORT
from accessories.sleepdeprivator import sleepdeprivator

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
        self.parent = parent

      
        colLabels = ['Monitor', 'Source', 'Mask', 'Output', 'Track type', 'Track', 'sleepDeprivator']
        tracktypes = ['DISTANCE','VBS','XY_COORDS']
        
        self.monitors = {}
        
        ###################################################

        #self.FBconfig = FileBrowseButton(self, -1, labelText='Pick file', size=(300,-1))
        
        WebcamsList = [ 'Camera %02d' % (int(w) +1) for w in range( options.GetOption("Webcams") ) ]
        mon_num = options.GetOption("Monitors")
        monitorsData = options.getMonitorsData()

        mainSizer = wx.BoxSizer(wx.VERTICAL)
        gridSizer = wx.FlexGridSizer (cols=len(colLabels), vgap=5, hgap=5)  #wx.BoxSizer(wx.VERTICAL)


        font = wx.Font(12, wx.SWISS, wx.NORMAL, wx.BOLD)
        for key in colLabels:
            text = wx.StaticText(self, -1, key )
            text.SetFont(font)
            gridSizer.Add(text, 0, wx.ALL|wx.ALIGN_CENTER, 5)
            

        
        #for mn in monitorsData:
        for mn in range(1, mon_num+1):
            
            if not options.HasMonitor(mn): options.SetMonitor(mn)
            md = options.GetMonitor(mn)
            
            try:
                _, source = os.path.split( md['source'] )
            except:
                source = 'Camera %02d' % ( md['source'] )
            
            _, mf = os.path.split(md['mask_file'])
            df = 'Monitor%02d.txt' % (mn)
            track = ( md['track'] == True )
            
            ls = wx.BoxSizer (wx.HORIZONTAL)
            gridSizer.Add(wx.StaticText(self, -1, "Monitor %s" % mn ), 0, wx.ALL|wx.ALIGN_CENTER, 5)

            gridSizer.Add(comboFileBrowser(self, wx.ID_ANY, size=(-1,-1), dialogTitle = "Choose an Input video file", startDirectory = options.GetOption("Data_Folder"), value = source, choices=WebcamsList, fileMask = "Video File (*.*)|*.*", browsevalue="Browse for video...", changeCallback = partial(self.__onChangeValue, [mn, "source"])), 0, wx.ALL|wx.ALIGN_CENTER, 5 )

            gridSizer.Add(comboFileBrowser(self, wx.ID_ANY, size=(-1,-1), dialogTitle = "Choose a Mask file", startDirectory = options.GetOption("Mask_Folder"), value = mf, fileMask = "pySolo mask file (*.msk)|*.msk", browsevalue="Browse for mask...", changeCallback = partial(self.__onChangeValue, [mn, "mask_file"])), 0, wx.ALL|wx.ALIGN_CENTER, 5 )

            gridSizer.Add(comboFileBrowser(self, wx.ID_ANY, size=(-1,-1), dialogTitle = "Choose the output file", startDirectory = options.GetOption("Data_Folder"), value = df, fileMask = "Output File (*.txt)|*.txt", browsevalue="Browse for output...", changeCallback = partial(self.__onChangeValue, [mn, "outputfile"])), 0, wx.ALL|wx.ALIGN_CENTER, 5 )


            ttcb = wx.ComboBox(self, -1, size=(-1,-1), value=md['track_type'], choices=tracktypes, style=wx.CB_DROPDOWN | wx.CB_READONLY | wx.CB_SORT)
            ttcb.Bind (wx.EVT_COMBOBOX, partial(self.__onChangeValue, [mn, "track_type"]))
            gridSizer.Add(ttcb , 0, wx.ALL|wx.ALIGN_CENTER, 5)

            chk = wx.CheckBox(self, -1, '', (10, 10))
            chk.SetValue(md['track'])
            chk.Bind(wx.EVT_CHECKBOX, partial(self.__onChangeValue, [mn, "track"]))
            gridSizer.Add(chk, 0, wx.ALL|wx.ALIGN_CENTER, 5)
            
            SERIAL_PORTS = sleepdeprivator.listSerialPorts()
            serialSD = wx.ComboBox(self, -1, size=(-1,-1), value=md['serial_port'], choices=SERIAL_PORTS, style=wx.CB_DROPDOWN | wx.CB_READONLY | wx.CB_SORT)
            serialSD.Bind (wx.EVT_COMBOBOX, partial(self.__onChangeValue, [mn, "serial_port"]))
            gridSizer.Add(serialSD , 0, wx.ALL|wx.ALIGN_CENTER, 5)
        
        btnSizer = wx.BoxSizer(wx.HORIZONTAL)
        conf_btnSizer = wx.StaticBoxSizer(wx.StaticBox(self, wx.ID_ANY, 'Configuration'), wx.HORIZONTAL)
        acq_btnSizer = wx.StaticBoxSizer(wx.StaticBox(self, wx.ID_ANY, 'Acquisition'), wx.HORIZONTAL)
        

        self.saveOptionsBtn = wx.Button(self, wx.ID_ANY, 'Save')
        self.saveOptionsBtn.Enable(False)
        self.Bind(wx.EVT_BUTTON, self.onSave, self.saveOptionsBtn)
        conf_btnSizer.Add (self.saveOptionsBtn, 0, wx.ALL, 5) 
        
        self.startBtn = wx.Button(self, wx.ID_ANY, 'Start')
        self.stopBtn = wx.Button(self, wx.ID_ANY, 'Stop')
        self.startBtn.Enable(True)
        self.stopBtn.Enable(False)
        self.Bind(wx.EVT_BUTTON, self.onStop, self.stopBtn)
        self.Bind(wx.EVT_BUTTON, self.onStart, self.startBtn)
        acq_btnSizer.Add (self.startBtn, 0, wx.ALL, 5) 
        acq_btnSizer.Add (self.stopBtn, 0, wx.ALL, 5)

        btnSizer.Add(conf_btnSizer, 0, wx.ALL, 5) 
        btnSizer.Add(acq_btnSizer, 0, wx.ALL, 5) 
        
        #mainSizer.Add(self.FBconfig, 0, wx.EXPAND|wx.ALL, 5) 
        mainSizer.Add(gridSizer, 1, wx.EXPAND, 0)
        mainSizer.Add(btnSizer, 0, wx.ALL, 5)
        self.SetSizer(mainSizer) 

    def __onChangeValue(self, target, event=None):
        """
        """
        self.saveOptionsBtn.Enable(True)
        self.startBtn.Enable(False)
        
        et = event.GetEventType()
        if et == 10020:
            value = event.GetString()
            if "Camera " in value:
                value = int(value.split(" ")[1])
            
        elif et == 10009:
            value = event.IsChecked()
        
        section = "Monitor%s" % target[0]
        keyname = target[1]
        options.setValue(section, keyname, value)
        
        
    def onStart(self, event=None):
        """
        """
        self.acquiring = True
        self.stopBtn.Enable(self.acquiring)
        self.startBtn.Enable(not self.acquiring)
        c = 0

        resolution = options.GetOption("Resolution")
        data_folder = options.GetOption("Data_Folder")
        monitorsData = options.getMonitorsData()
        
        for mn in monitorsData:
            m = monitorsData[mn]
            if m['track']:
                
                m_tt = ['DISTANCE','VBS','XY_COORDS'].index(m['track_type'])
                if type(m['source']) == int:
                    m_source = int(m['source']) - 1
                else:
                    m_source = m['source']
                
                self.monitors[mn] = ( acquireThread(mn, m_source, resolution, m['mask_file'], m['track'], m_tt , data_folder) )
                
                self.monitors[mn].mon.SDserialPort = m['serial_port']
                self.monitors[mn].mon.inactivity_threshold = m['inactivity_threshold'] or None

                self.monitors[mn].doTrack()

                c+=1
            
        #self.parent.sb.SetStatusText('Tracking %s Monitors' % c)
    
    def onStop(self, event):
        """
        """
        self.acquiring = False
        self.stopBtn.Enable(False)
        self.startBtn.Enable(True)
        
        for mon in self.monitors:
            self.monitors[mon].halt()
            
        self.parent.sb.SetStatusText('All tracking is now stopped')
        
    def onSave(self, event):
        """
        """
        options.Save()
        self.saveOptionsBtn.Enable(False)
        self.startBtn.Enable(True)
        
class acquireFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        kwargs["size"] = (980, 600)

        wx.Frame.__init__(self, *args, **kwargs)

        self.sb = wx.StatusBar(self, wx.ID_ANY)
        self.SetStatusBar(self.sb)

        self.acq_panel =  pvg_AcquirePanel(self)
        
    def Start(self):
        """
        """
        self.acq_panel.onStart()



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


    
