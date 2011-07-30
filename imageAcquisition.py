#!/usr/bin/env python

'''
Version 1.0
'''

from pysolo_video import *
import datetime as dt
import threading

class acquireThread(threading.Thread):
    '''
    start the acquisition thread
    mon_num is the webcam number attached to the system. If you have only one webcam, mon_num should be 0
    seconds is the interval in seconds for taking images. A good number is 5 seconds
    outPath is the root path where the files are saved. A folder corresponding to the day will be created inside
    resolution is the resolution at which images are taken and processed
    saveImages states whether you want to save a jpg copy of the images in the output folder
        saveImages = full will save every acquired image at specified settings
        saveImages = partial will save only one file per minute at 640x480, quality 70
        saveImages = never will not save anything
    quality is the quality at which images will be saved
    ZT0 indicates the start time of the relative day
    '''
    def __init__(self, mon_num, seconds, outPath, resolution, saveImages = 'partial', quality=90, ZT0='9:30'):
        '''
        '''
        threading.Thread.__init__(self)
        #common parameters
        self.interval = seconds
        self.outPath = outPath
        self.resolution = resolution
        self.monitor_number = mon_num

        self.start_h = int(ZT0.split(':')[0])
        self.start_m = int(ZT0.split(':')[1])

        #starts
        self.dayPath = self.createDayDir()
        self.mon1 = Monitor(self.monitor_number, self.resolution)
        
        #save files section
        self.saveImages = (saveImages == 'full')
        self.savePartial = (saveImages == 'partial')
        self.quality = quality
        self.online = False
        
        self.startTime = dt.datetime.today()
        self.lastSavePartial = dt.datetime.today()
        self.keepGoing = True
        

    def activateOnlineScoring(self, maskpath, threshold=75, resize_mask=((960,720), (960,720))):
        '''
        Initialize certain parameters that are used only for onlineScoring
        maskpath is the fullpath of the file to be used as mask
        threshold is the threshold value that will be used for the processing
        resize_mask specify the initial and final resolution for resizing an image. if identical, no resize will be applied
        '''
    
        self.online = True
        self.mask_name = maskpath
        self.resize_mask = resize_mask
    
        self.mon1.SetUseAverage(False)
        self.mon1.SetThreshold(threshold) #threshold value used to calculate position of the fly
        
        try:
            self.mon1.LoadCropFromFile(self.mask_name)
            print 'Successfully loaded mask %s' % self.mask_name
        except:
            print 'I tried to load mask %s but could not succeed. Does it exist?' % self.mask_name
        
        if self.resize_mask[0] != self.resize_mask[1]:
            print 'Resizing mask from %sx%s to %sx%s' % (self.resize_mask[0][0], self.resize_mask[0][1], self.resize_mask[1][0], self.resize_mask[1][1])
            self.mon1.resizeCrop(*resize_mask)
    
        self.number_of_flies = self.mon1.GetNumberOfVials()
        flies_per_vial = 1
        
        self.coords = [(0,0)] * self.number_of_flies 
        self.last_coords = [[(0,0)]] * self.number_of_flies
        self.frame_num = 0
        self.fpv = flies_per_vial -1
        
        self.outFileName = 'VideoMonitor_%02d.pvf' % self.monitor_number#'%s.pvf' % self.mask_name.split('.')[0]
        self.outFile = os.path.join(self.dayPath, self.outFileName)


    def __sleep__(self):
        '''
        called internally.
        more accurate than time.sleep()
        '''
        while (dt.datetime.today() - self.lastExecution).seconds < self.interval:
            pass

    def halt(self):
        '''
        will arrest the thread at the next useful cycle
        '''
        self.keepGoing = False
        
    def benchmark(self):
        '''
        just used to detect speed of the machine with current settings
        '''
        count = 0

        print 'Starting benchmark now. It will take exactly one minute'
        bench_start = dt.datetime.today()
        
        while self.keepGoing:
            self.lastExecution = dt.datetime.today()

            if self.saveImages:
                self.img = self.mon1.GetImage()
                self.saveImageAsFile()

            if self.online:
                self.onLineScoring()

            if self.savePartial:
                if (self.lastExecution - self.lastSavePartial).minutes >=1:
                    self.lastSavePartial = dt.datetime.today()
                    self.img = self.mon1.GetImage()
                    self.saveImageAsFile()

            #do benchmark here
            count += 1
            if (dt.datetime.today() - bench_start).seconds > 60:
                print 'We this settings, you could process %s images in 1 minute' % count
                bench_start = dt.datetime.today()
                count = 0
                break
         
        
        
    def run(self):
        '''
        will start the execution of the thread.
        do not call directly
        use start() instead
        '''

        while self.keepGoing:
            self.lastExecution = dt.datetime.today()

            if self.saveImages: 
                self.img = self.mon1.GetImage()
                self.saveImageAsFile()
                
            if self.online:
                self.onLineScoring()

            if self.savePartial and ((self.lastExecution - self.lastSavePartial).seconds >=60):
                self.lastSavePartial = dt.datetime.today()
                self.img = self.mon1.GetImage()
                self.saveImageAsFile()

            self.__sleep__()
            

    def getFilename(self, extension='.jpg'):
        '''
        Returns a proper filename, based on the time of the relative day
        '''
    
        now = datetime.datetime.today() - datetime.timedelta(hours=self.start_h, minutes=self.start_m)
        mo = str(now.month).zfill(2); dd = str(now.day).zfill(2)
    
        #time of the day
        hh = str(now.hour).zfill(2); mm = str(now.minute).zfill(2); ss = str(now.second).zfill(2)
    
        #crescent number
        min_day = int(hh)*60 + int(mm)
        nn = str(min_day).zfill(4)

        #create a new directory if we are at relative midnight
        if min_day == 0: self.dayPath = self.createDayDir()
    
        filename = '%02d-%s%s-%s-%s%s' % (self.monitor_number, mo, dd, nn, ss, extension)
        
        if extension:
            return os.path.join(self.dayPath, filename)
        else:
            return filename
            

    def createDayDir(self):
        '''
        Creates a new directory based on given date. The structure of the
        directory is outputPath/yyyy/mm/mmdd/
        '''
        now = datetime.datetime.today()
        zt = datetime.datetime(now.year, now.month, now.day, self.start_h, self.start_m)
        
        if now < zt: now = now - datetime.timedelta(days=1)
    
        dirFullPath = os.path.join (self.outPath,
                                    str(now.year),
                                    str(now.month).zfill(2),
                                    str(now.month).zfill(2) + str(now.day).zfill(2)
                                    )
    
        if not os.access(dirFullPath, os.F_OK): os.makedirs(dirFullPath)
        
        return str(dirFullPath)


        
    def saveImageAsFile(self):
        '''
        saveImageAsFile.
        all parameters are internal
        '''

        self.fname = self.getFilename(extension='.jpg')
        
        if self.savePartial:
            self.img.resize((640,480), Image.ANTIALIAS).save(self.fname, quality=70)
        else:
            self.img.save(self.fname, quality=self.quality)

    
    def onLineScoring(self):
        '''
        execute online scoring for the last image
        '''
        self.frame_num += 1
        line_name = self.getFilename(extension='')

        self.outFile = os.path.join(self.dayPath, self.outFileName)
        of = open(self.outFile, 'a')
        
        diff_img = self.mon1.GetDiffImg()

        for fly_n in range(self.number_of_flies):
            c = self.mon1.GetXYFly(fly_n, diff_img)
            if c == []: c = self.last_coords[fly_n]
            self.coords[fly_n] = c
            self.last_coords[fly_n] = c

        t = '%s\t' % line_name
        for fc in self.coords:
            t += '%s,%s\t' % (fc[self.fpv][0], fc[self.fpv][1])

        t += '\n'
        of.write(t)
        
        of.close()


if __name__ == '__main__':

    web_cam = 0 #if you have only 1 webcam this number is zero. 1 for the second, for the third and so on
    outPath = 'C:/sleepData/videoData' #this is the root path of where the files will be saved
    interval = 2 #between image comparisons, in seconds
    resolution = (960,720) #at which images are acquired and optionally stored if saveImages = 'full'
    mask_name = 'default.mask'#the mask that has to be used for online analysis. not needed for offline
    resize_mask = ((640,480), resolution) #specify whether the mask has to be resized. normally is not needed
    saveImages='partial' #this could be partial, full or never. check documentation
    ZT0='12:00' #this is the time when a new day starts for the flies
    doOnlineAnalysis = True #self explicative
    
    #initialize the camera
    a = acquireThread(web_cam, interval, outPath, resolution, saveImages=saveImages, ZT0=ZT0)
    if doOnlineAnalysis: a.activateOnlineScoring(mask_name, resize_mask = resize_mask)

    #for commandline use, use run
    #if you have more than one camera you must use start instead
    #a.benchmark()
    a.run()
    #a.start()

        

