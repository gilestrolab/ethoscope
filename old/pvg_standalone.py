#!/usr/bin/env python
import wx
import optparse
import pysolovideo
from pvg_common import previewPanel, pvg_config, cvPanel
from os.path import splitext

##
## find . -fname "*.avi" | xargs python2 pvg_standalone.py -i {}
##

class wxMovieFrame(wx.Frame):
    def __init__(self, parent, source, resolution, track, track_type, mask_file, output_file, showROIs, showpath, showtime, record ):
        wx.Frame.__init__(self, parent)
        
       
        self.displayPanel = previewPanel(self, size=resolution, keymode=True, singleFrameMode=True)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add (self.displayPanel)
        #self.setSizer(sizer)
        
        #self.SetSize((-1, -1))
        self.SetTitle(source)
        
        monitor = pysolovideo.Monitor()
        monitor.setSource(source, resolution)
        self.displayPanel.setMonitor( monitor )
        self.displayPanel.mon.setTracking(track, track_type, mask_file, output_file)
        self.displayPanel.mon.isTracking = True
        self.displayPanel.timestamp = showtime
       
        if record:
            self.displayPanel.mon.saveMovie('video_output.avi', fps=14, startOnKey=True)
        
        self.displayPanel.prinKeyEventsHelp()
        self.displayPanel.Play(showROIs=showROIs)
        self.Show()


if __name__=="__main__":

    parser = optparse.OptionParser(usage='%prog [options] [argument]', version='%prog version 0.1')
    parser.add_option('-c', '--config', dest='configfile', metavar="CONFIGFILE", help="Config mode | Use specified CONFIGFILE")
    parser.add_option('-m', '--monitor', dest='monitor', metavar="MON", help="Config mode | Load monitor MON from configfile")
    parser.add_option('-i', '--input', dest='source', metavar="SOURCE", help="File mode | Specify a source (camera number, file or folder)")
    parser.add_option('-k', '--mask', dest='mask_file', metavar="MASKFILE", help="File mode | Specify a maskfile to be used with file.")
    parser.add_option('-t', '--tracktype', dest='track_type', metavar="TT", help="File mode | Specify track type: 0, distance; 1, trikinetics; 2, coordinates")
    parser.add_option('-o', '--output', dest='output_file', metavar="OUTFILE", help="All modes | Specify an output file where to store tracking results. A Mask must be loaded")
    parser.add_option('--showmask', action="store_true", default=False, dest='showROIs', help="Show the area limiting the ROIs")
    parser.add_option('--showpath', action="store_true", default=False, dest='showpath', help="Show the last steps of each fly as white line")
    parser.add_option('--showtime', action="store_true", default=False, dest='showtime', help="Show the frame timestamp")
    parser.add_option('--record', action="store_true", default=False, dest='record', help="Record the resulting video as avi file")
    parser.add_option('--trackonly', action="store_true", default=False, dest='trackonly', help="Does only the tracking, without showing the video")
    parser.add_option('--useCV', action="store_true", default=False, dest='use_cv', help="Show a preview using a CV window - experimental")
    parser.add_option('--snapshot', action="store_true", default=False, dest='snapshot', help="Save a snapshot to file")
    parser.add_option('--printinfo', action="store_true", default=False, dest='printinfo', help="Print some debug info about the camera")
    
    (options, args) = parser.parse_args()

    if options.configfile and options.monitor:

        opts = pvg_config(options.configfile)
        mon = int(options.monitor)
        _,source,track,mask_file,track_type,isSDMonitor = opts.GetMonitor(mon)
        resolution = opts.GetOption('FullSize')
        output_file = options.output_file or ''
        
    elif options.source:
        
        resolution = (800, 600)
        source = options.source # integer or filename or dirname
        track = options.mask_file and options.track_type
        mask_file = options.mask_file or splitext(options.source)[0]+'.msk'
        track_type = options.track_type
        output_file = options.output_file or splitext(options.source)[0]+'.txt'

    else:
        parser.print_help()


    if options.source and options.printinfo:
        m = pysolovideo.Monitor()
        m.setSource(source, resolution)
        print m.debug_info
        exit()

    if options.snapshot:
        m = pysolovideo.Monitor()
        m.setSource(source, resolution)
        filename = "%s.jpg" % source
        m.saveSnapshot(filename)
    
    elif options.use_cv:
        c = cvPanel (source, resolution, str(source), track_type, mask_file, output_file, options.showROIs, options.showpath, options.showtime )
        c.mon.isTracking = True
        if options.record: c.mon.saveMovie('video_output.avi')
        c.play()

    elif not options.trackonly and ((options.configfile and options.monitor) or options.source):

        app = wx.App()
        f = wxMovieFrame(None, source, resolution, track, track_type, mask_file, output_file, options.showROIs, options.showpath, options.showtime, options.record )
        app.MainLoop()
        
    elif options.trackonly and ((options.configfile and options.monitor) or options.source): #no X output needed
        
        m = pysolovideo.Monitor()
        m.setSource(source, resolution)
        m.setTracking(True, track_type, mask_file, output_file)
        if options.record: m.saveMovie('video_output.avi')
        print "Processing video %s without output. This may take sometime." % source
        m.startTracking()

