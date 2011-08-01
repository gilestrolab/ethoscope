#!/usr/bin/env python2 
import wx, cv
import pysolovideo as pv
from pvg_common import previewPanel, pvg_config

class CvMovieFrame(wx.Frame):
    def __init__(self, parent, source, resolution, track, track_type, mask_file, outputFile ):
        wx.Frame.__init__(self, parent)
        self.displayPanel = previewPanel(self, size=resolution)

        self.displayPanel.setMonitor(source, resolution)
        self.displayPanel.mon.setTracking(track, track_type, mask_file, outputFile)
        self.displayPanel.Play()
        
        

if __name__=="__main__":
    
    options = pvg_config('config.cfg')

    resolution = (800, 600)
    source = 0 # or filename or dirname
    track = True
    mask_file = 'Monitor 2.msk'
    track_type = 0 # or 1

    outputFile = '' # or filename.txt to activate writing

    _,source,track,mask_file,track_type = options.GetMonitor(0)
      
    app = wx.App()
    f = CvMovieFrame(None, source, resolution, track, track_type, mask_file, outputFile )
    f.SetSize(resolution)

    f.Show()
    app.MainLoop()
