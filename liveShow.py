#!/usr/bin/env python2
import pysolo_video as pv
import cv
import sys

'''
Version 1.2

Show play window:                       opencv
Show controls of play window:           n/a
Realtime mask dragging and drawing:     n/a
'''

class offlineProcessor:
    '''
    FIX THIS
    '''
    def __init__(self,vc, mask_name, resize_mask=((960,720),(960,720)), crop_way=(0,0)):
        mon1 = Monitor(virtual_cam = vc )
        mon1.SetUseAverage(False)
        mon1.SetThreshold(75) #threshold value used to calculate position of the fly
        
        try:
            mon1.LoadCropFromFile(mask_name)
            print 'Successfully loaded mask %s' % mask_name
        except:
            print 'I tried to load mask %s but could not suceed. Does it exist?' % mask_name
        
        if resize_mask[0] != resize_mask[1]:
            print 'Resizing mask from %sx%s to %sx%s' % (resize_mask[0][0], resize_mask[0][1], resize_mask[1][0], resize_mask[1][1])
            mon1.resizeCrop(*resize_mask)

        number_of_flies = mon1.GetNumberOfVials()
        flies_per_vial = 1
        
        coords = [(0,0)] * number_of_flies 
        last_coords = [[(0,0)]] * number_of_flies
        frame_num = 0
        fpv = flies_per_vial -1
        
        outFile = '%s.pvf' % mask_name.split('.')[0]
        
        of = open(outFile, 'w')
        
        print 'Proceeding with the analysis of %s flies\nResults will be saved in file %s' % (number_of_flies, outFile)
        
        while not mon1.isLastFrame():

            frame_num +=1
            if frame_num % 100 == 0: print 'processed %s frames' % frame_num
            diff_img = mon1.GetDiffImg()

            for fly_n in range(number_of_flies):
                c = mon1.GetXYFly(fly_n, diff_img)
                if c == []: c = last_coords[fly_n]
                coords[fly_n] = c
                last_coords[fly_n] = c

            t = '%s\t' % frame_num
            for fc in coords:
                t += '%s,%s\t' % (fc[fpv][0], fc[fpv][1])

            t += '\n'
            of.write(t)
        
        of.close()

class playWindow:
    
    def __init__(self, mask_name, resize_mask, crop_way, windowName='playback', showTracking=True):
        '''
        Initialize constants and variables
        '''
        
        if  self.mon.LoadCropFromFile(mask_name): print ("Loading mask: %s" % mask_name)
        else: print ("A Mask with name %s has not been found and will be created. Use your mouse to do so.\n"
                     "Press any key when done to save the mask or Exit the window to abort without saving"
                      % mask_name )

        if resize_mask[0] != resize_mask[1]:
            print 'Resizing mask from %sx%s to %sx%s' % (resize_mask[0][0], resize_mask[0][1], resize_mask[1][0], resize_mask[1][1])
            self.mon.resizeCrop(*resize_mask)
        
        self.mon.SetUseAverage(False)
        self.mon.SetThreshold(75)
        self.showTracking = showTracking
        self.windowName = windowName
        
        self.createWindow()

    def createWindow(self):
        '''
        Create the playback Window
        '''

        cv.NamedWindow(self.windowName, cv.CV_WINDOW_AUTOSIZE)
        cv.SetMouseCallback( self.windowName, self.on_mouse)
        

    def Play(self):
        '''
        Show images in realtime and creates the mask
        '''

        self.drag_start = None      # Set to (x,y) when mouse starts drag
        self.track_window = None    # Set to rect when the mouse drag finishes

        while not self.mon.isLastFrame():

            c = cv.WaitKey(10) & 255

            if c == 115: #s
                self.mon.SaveCropToFile(mask_name)
                sys.exit(0)
            elif c == 113: #q
                sys.exit(0)

            if self.showTracking: ## Shows the image with the fly position
                self.mon.GetDiffImg(draw_crop = False, timestamp=True)
                im = self.mon.DrawXYAllFlies(use_diff = False, draw_crop = True)

            else: ## Shows the image without tracking the fly movement
                im = self.mon.GetImage(draw_crop = True, timestamp=True)
                #im = self.mon.GetDiffImg(draw_crop = False, timestamp=True)

            im_cv = cv.CreateImageHeader(im.size, cv.IPL_DEPTH_8U, 3)  # create empty RGB image
            cv.SetData(im_cv, im.tostring(), im.size[0]*3)
            #cv.CvtColor(im_cv, im_cv, cv.CV_RGB2BGR)
            
            cv.ShowImage(self.windowName, im_cv)

    def on_mouse(self, event, x, y, flags, param):
        '''
        Handle Mouse Events
        '''
        if event == cv.CV_EVENT_LBUTTONDOWN:
            self.drag_start = (x, y)
            
        elif event == cv.CV_EVENT_LBUTTONUP:
            self.drag_end = (x, y)
            self.mon.AddCropArea( (self.drag_start[0], self.drag_start[1], self.drag_end[0], self.drag_end[1]) )
            
            self.drag_start = None
            self.drag_end = None

            
        elif event == cv.CV_EVENT_MOUSEMOVE and self.drag_start:
            #img1 = cv.CloneImage(img)
            #cv.Rectangle(img1, self.drag_start, (x, y), (0, 0, 255), 1, 8, 0)
            #cv.ShowImage("img", img1)
            pass
            
            
class liveShow(playWindow):
    '''
    Will inherit from playWindow and show a camera in realTime 
    '''
    def __init__(self, camera_number, resolution, mask_name, resize_mask, crop_way, showTracking):

        self.mon = pv.Monitor( devnum=camera_number, resolution=resolution)
        windowName = 'live - %s' % camera_number
        playWindow.__init__(self, mask_name, resize_mask, crop_way, windowName, showTracking)
        #self.mon.saveMovie ('/home/gg/Desktop/street.avi')
        
        
class offlineShow(playWindow):
    '''
    Will inherit from playWindow and show recorded images in playback
    '''
    def __init__(self, virtual_camera, resolution, mask_name, resize_mask, crop_way, showTracking):

        self.mon = pv.Monitor( camera=virtual_camera, resolution=resolution )
        windowName = '%s' % virtual_camera['path']
        playWindow.__init__(self, mask_name, resize_mask, crop_way, windowName, showTracking)
    

if __name__ == '__main__':
    
    real_camera = 0 #set to 0 for the first webcam, 1 for the second and so on
    
    virtual_camera = {  
            'path' : '/home/gg/Dropbox/Work/Projects/biohacking/FlyEquipment/SleepVideo/video_images/video-IR-2.avi',
            'start': None,
            'step' : None,
            'end'  : None,
            'loop' : False
        }

    resolution = (800,600)
    mask_name = 'default.mask'
    resize_mask = ((800,600), resolution)
    showTracking = True
    
    #method to be used when adding new crop areas 
    #crop_way = (0,0) ## The new area is defined using the mouse and select a rectangle
    crop_way = (12,120) ## click in the middle of the area to draw a fixed size rectangle

    
    l = liveShow (real_camera, resolution, mask_name, resize_mask, crop_way, showTracking)
    #l = offlineShow (virtual_camera, resolution, mask_name, resize_mask, crop_way, showTracking)
    l.Play()
