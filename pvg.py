#!/usr/bin/env python
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


import wx, os

from pvg_options import optionsFrame

from pvg_acquire import pvg_AcquirePanel as panelOne
from pvg_panel_two import panelLiveView
from pvg_common import options, DEFAULT_CONFIG

from pysolovideo import pySoloVideoVersion

class mainNotebook(wx.Notebook):
    """
    The main notebook containing all the panels for data displaying and analysis
    """
    def __init__(self, *args, **kwds):
        # begin wxGlade: propertiesNotebook.__init__
        kwds["style"] = wx.NB_LEFT
        wx.Notebook.__init__(self, *args, **kwds)
        
        self.panelOne = panelOne(self)
        self.AddPage(self.panelOne, "Monitors sheet")

        self.panelTwo = panelLiveView(self)
        self.AddPage(self.panelTwo, "Live View")
        
        self.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGING, self.OnPageChanging)
        
        self.Layout()
        
    def OnPageChanging(self, event):
        """
        """
        #self.panelOne.StopPlaying()
        self.panelTwo.StopPlaying()
        
class mainFrame(wx.Frame):
    """
    The main frame of the application
    """
    def __init__(self, *args, **kwds):

        kwds["style"] = wx.DEFAULT_FRAME_STYLE
        wx.Frame.__init__(self, *args, **kwds)
      
        self.__menubar__()
        self.__set_properties()
        self.__do_layout()

    def __do_layout(self):
        #Add Notebook
        self.videoNotebook = mainNotebook(self, -1)
        
        mainSizer = wx.BoxSizer(wx.HORIZONTAL)
        mainSizer.Add(self.videoNotebook, 1, wx.EXPAND, 0)
        self.SetSizer(mainSizer)


    def __set_properties(self):
        # begin wxGlade: mainFrame.__set_properties
        self.SetTitle("pySoloVideo")
        x,y = options.GetOption("Resolution")
        self.SetSize((x*1.8,y*1.4))
        
    def __menubar__(self):
        
        #Gives new IDs to the menu voices in the menubar
        ID_FILE_OPEN = wx.NewId()
        ID_FILE_SAVE = wx.NewId()
        ID_FILE_SAVE_AS = wx.NewId()
        #ID_FILE_CLOSE =  wx.NewId()
        ID_FILE_EXIT =  wx.NewId()
        ID_HELP_ABOUT =  wx.NewId()
        ID_OPTIONS_SET =  wx.NewId()

        filemenu =  wx.Menu()
        filemenu. Append(ID_FILE_OPEN, '&Open File', 'Open a file')
        #filemenu. Append(ID_FILE_SAVE, '&Save File', 'Save current file')
        filemenu. Append(ID_FILE_SAVE_AS, '&Save as...', 'Save current data in a new file')
        #filemenu. Append(ID_FILE_CLOSE, '&Close File', 'Close')
        filemenu. AppendSeparator()
        filemenu. Append(ID_FILE_EXIT, 'E&xit Program', 'Exit')

        optmenu =  wx.Menu()
        optmenu. Append(ID_OPTIONS_SET, 'Confi&gure', 'View and change settings')

        helpmenu =  wx.Menu()
        helpmenu. Append(ID_HELP_ABOUT, 'Abou&t')

        #Create the MenuBar
        menubar =  wx.MenuBar(style = wx.SIMPLE_BORDER)

        #Populate the MenuBar
        menubar. Append(filemenu, '&File')
        menubar. Append(optmenu, '&Options')
        menubar. Append(helpmenu, '&Help')

        #and create the menubar
        self.SetMenuBar(menubar)        

        wx.EVT_MENU(self, ID_FILE_OPEN, self.onFileOpen)
        wx.EVT_MENU(self, ID_FILE_SAVE, self.onFileSave)
        wx.EVT_MENU(self, ID_FILE_SAVE_AS, self.onFileSaveAs)
        #wx.EVT_MENU(self, ID_FILE_CLOSE, self.onFileClose)
        wx.EVT_MENU(self, ID_FILE_EXIT, self.onFileExit)
        wx.EVT_MENU(self, ID_OPTIONS_SET, self.onConfigure)
        wx.EVT_MENU(self, ID_HELP_ABOUT, self.onAbout)
        
    def onAbout(self, event):
        """
        Shows the about dialog
        """
        about = 'pySolo-Video - v %s\n' % pySoloVideoVersion
        about += 'by Giorgio F. Gilestro\n'
        about += 'Visit http://www.pysolo.net for more information'
        
        dlg = wx.MessageDialog(self, about, 'About', wx.OK | wx.ICON_INFORMATION)
        dlg.ShowModal()
        dlg.Destroy()

        
    def onFileSave(self, event):
        """
        """
        options.Save()
        
    def onFileSaveAs(self, event):
        """
        """
        filename = DEFAULT_CONFIG
        wildcard = "pySolo Video config file (*.cfg)|*.cfg"
        
        dlg = wx.FileDialog(
            self, message="Save file as ...", defaultDir=os.getcwd(), 
            defaultFile=filename, wildcard=wildcard, style=wx.SAVE
            )

        #dlg.SetFilterIndex(2)

        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            options.Save(filename=path)
            
        dlg.Destroy()
        
    def onFileOpen(self, event):
        """
        """
        wildcard = "pySolo Video config file (*.cfg)|*.cfg"
        
        dlg = wx.FileDialog(
            self, message="Choose a file",
            defaultDir=os.getcwd(),
            defaultFile="",
            wildcard=wildcard,
            style=wx.OPEN | wx.CHANGE_DIR
            )

        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            options.New(path)
        
        dlg.Destroy()

    def onFileExit(self, event):
        """
        """
        self.Close()
    
    def onConfigure(self, event):
        """
        """
        frame_opt = optionsFrame(self, -1, '')
        frame_opt.Show()
    
    
    
if __name__ == "__main__":
    
    app = wx.App(False)
    frame_1 = mainFrame(None, -1, "")
    app.SetTopWindow(frame_1)
    frame_1.Show()
    app.MainLoop()
