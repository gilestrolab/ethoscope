#!/usr/bin/env python
import wx, cv, optparse
import pysolovideo as pv
from pvg_common import previewPanel, pvg_config

class CvMovieFrame(wx.Frame):
    def __init__(self, parent, source, resolution, track, track_type, mask_file, outputFile, showROIs, record ):
        wx.Frame.__init__(self, parent)
        self.displayPanel = previewPanel(self, size=resolution, keymode=True)
        self.SetSize(resolution)

        self.displayPanel.setMonitor(source, resolution)
        self.displayPanel.mon.setTracking(track, track_type, mask_file, outputFile)
       
        if record:
            self.displayPanel.mon.saveMovie('video_output.avi', fps=14, startOnKey=True)
        
        self.displayPanel.Play(showROIs=showROIs)
        self.Show()


if __name__=="__main__":

    parser = optparse.OptionParser(usage='%prog [options] [argument]>', version='%prog version 0.1')
    parser.add_option('-c', '--config', dest='configfile', metavar="CONFIGFILE", help="Config mode | Use specified CONFIGFILE")
    parser.add_option('-m', '--monitor', dest='monitor', metavar="MON", help="Config mode | Load monitor MON configfile")
    parser.add_option('-i', '--input', dest='source', metavar="SOURCE", help="File mode | Specify a source (camera number, file or folder)")
    parser.add_option('-k', '--mask', dest='mask_file', metavar="MASKFILE", help="File mode | Specify a maskfile to be used with file.")
    parser.add_option('-t', '--tracktype', dest='track_type', metavar="TT", help="File mode | Specify track type: 0, distance; 1, trikinetics; 2, coordinates")
    parser.add_option('-o', '--output', dest='outputFile', metavar="OUTFILE", help="All modes | Specify an output file where to store tracking results. A Mask must be loaded")
    parser.add_option('--showmask', action="store_true", default=False, dest='showROIs', help="Show the area limiting the ROIs")
    parser.add_option('--record', action="store_true", default=False, dest='record', help="Record the resulting video as avi file")
    
    (options, args) = parser.parse_args()

    if options.configfile and options.monitor:

        opts = pvg_config(options.configfile)
        mon = int(options.monitor)
        _,source,track,mask_file,track_type = opts.GetMonitor(mon)
        resolution = opts.GetOption('FullSize')
        outputFile = options.outputFile or ''
        
    elif options.source:
        
        resolution = (640, 480)
        source = options.source # integer or filename or dirname
        
        mask_file = options.mask_file
        track_type = options.track_type
        track = mask_file and track_type
        outputFile = options.outputFile

    else:
        parser.print_help()


    if (options.configfile and options.monitor) or options.source:

        app = wx.App()
        f = CvMovieFrame(None, source, resolution, track, track_type, mask_file, outputFile, options.showROIs, options.record )
        app.MainLoop()    
