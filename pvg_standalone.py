import wx
import cv
import pysolovideo as pv
# Originally derived from:
# http://osdir.com/ml/wxpython-users/2010-11/msg00603.html

from pvg_common import previewPanel

class CvMovieFrame(wx.Frame):
    def __init__(self, parent, camera, resolution, srcType):
        wx.Frame.__init__(self, parent)
        self.displayPanel = previewPanel(self, size=resolution)
        
        self.displayPanel.setMonitor(camera, resolution, srcType)
        self.displayPanel.mon.track = True
        self.displayPanel.mon.loadROIS('Monitor 2.msk')

        self.displayPanel.Play()
        
        #im = self.displayPanel.mon.GetImage()
        #cv.SaveImage('/home/gg/Desktop/img2.jpg', im)
        #squares =  self.displayPanel.mon.findOuterFrame( im )
        #cv.PolyLine(im, squares, 1, cv.CV_RGB(0, 255, 0), 3, cv.CV_AA, 0)
        #self.displayPanel.paintImg(im)
        

if __name__=="__main__":
    
    srcType = 0
    
    if srcType == 0:
        camera = real_camera = 1 #set to 0 for the first webcam, 1 for the second and so on
    else:
        camera =  virtual_camera = {  
                                    'path' : '/home/gg/Dropbox/Work/Projects/biohacking/FlyEquipment/SleepVideo/video_images/video-IR-2.avi',
                                    'start': None,
                                    'step' : None,
                                    'end'  : None,
                                    'loop' : False
                                }

    resolution = (640, 480)
    showTracking = True

    app = wx.App()
    f = CvMovieFrame(None, camera, resolution, srcType)
    f.SetSize(resolution)
    f.Show()
    app.MainLoop()
