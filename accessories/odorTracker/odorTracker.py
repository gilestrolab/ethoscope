#!/usr/bin/env python2
# -*- coding: utf-8 -*-
#
#       odorTracker.py
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
#
#
#       All this would problably more readable as collection of functions rather than
#       as class



import numpy as np
import optparse
import os
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.mlab as mlab

COLORS = dict ({
                'Blue': '#0066cc', 
                'Brown': '#660000', 
                'Pink': '#ff99cc', 
                'Blue Marine': '#466086', 
                'Light Grey': '#999999', 
                'Purple': '#990099', 
                'Light Pink': '#ffcc99', 
                'Grey': '#666666', 
                'Yellow': '#ffcc00', 
                'Olive Green': '#989e67', 
                'Dark Orange': '#ff8040', 
                'Bright Yellow': '#ffff00', 
                'Green': '#33cc33', 
                'Light Yellow': '#ffff99', 
                'Light Green': '#ccff99', 
                'Dark Purple': '#663366', 
                'Light Blue': '#99ccff', 
                'Dark Grey': '#333333', 
                'Red': '#cc0033', 
                'Dark Green': '#336633'
                    })

COLS = 4
GRAY_BAND = 0.2
LEGEND="/mnt/nas/Videos/Lab_Members/Chin_Yee_Shim/legend.txt"

class odorTracker():
    """
    """
    def __init__(self, source, save, show, horizontal=True):
        """
        source      a full path to a single file or a dir containing multiple files
        save        save the output as jpg files
        show        show figures with pyplot
        """
        self.a = None
        self.fig = None
        self.directory, self.filename = os.path.split(source)

        self.save = save
        self.show = show

        if os.path.isfile(source):
            self.a = self.__readFile(source, horizontal)
            self.description = self.__seekDescription(source)
            self.input_file = source

        if os.path.isdir(source):
            # TO DO IMPLEMENT DIR READING ?
            pass
        
        self.midline = max(self.a[:,:,0].flatten())/2 # all x coordinates
        
        self.midline_left = int(self.midline * (1. - GRAY_BAND/2))
        self.midline_right = int(self.midline * (1. + GRAY_BAND/2))

    def __seekDescription(self, filename):
        """
        """
        info = {}
        fn = os.path.split(filename)[1]
        f = os.path.splitext(fn)[0].upper()
        
        try:
            fh = open(LEGEND, 'r')
            fc = fh.read()
            rawfile = fc.split('\n')
            for line in rawfile[:-1]:
                if line:
                    fn, desc = line.split('\t')
                    info[fn.upper()] = desc.strip()
        except: 
            pass

        if f in info:
            return info[f]
        else:
            return ''
            
        
    def __readFile(self, filename, horizontal=True):
        """
        Read a single txt file with coordinates and return a bidimensional numpy array
        """
        coords = []
        try:
            fh = open(filename, 'r')
            rawfile = fh.read().split('\n')

            for line in rawfile:
                line = line.split('\t')[10:]
                while '0' in line:
                    line.remove('0')
                coords.append( line )

            fh.close()

            while [] in coords:
                coords.remove([])
            
            flies = len (coords[0])
            frames = len (coords)
            
            a = np.ma.MaskedArray(np.zeros( (frames, flies, 2) ))

            #default orientation is with horizontal tubes
            #if tubes are vertical, we need to invert the coordinates
            
            for n, line in enumerate(coords):
                if horizontal:
                    cs = [ ( float (c.split(',')[0] ), float (c.split(',')[1]) ) for c in line  ]
                else:
                    cs = [ ( float (c.split(',')[1] ), float (c.split(',')[0]) ) for c in line  ]
                   
                a[n] = np.array(cs)
                
            #return self.filterArtifacts( a ) # VERY primitive way of smoothing artifacts
            return a
            
           
        except IOError:
            print "Error opening the file"

    def __makeFigure(self, clean=True):
        """
        """
        font = {'family' : 'serif',
                'weight' : 'normal',
                'size'   : 12}

        mpl.rc('font', **font)
        
        if not self.fig or clean:
            self.fig = plt.figure(figsize=(8,6), dpi=120)
            title = "%s [ %s ]" % (self.filename, self.description)
            self.fig.suptitle(title, fontsize=20)
            
                      
    def __showFigure(self):
        """
        """
        plt.show()
        #self.fig.show()
        
    def __saveFigure(self, filename=None, append=None):
        """
        """
        figureExt = 'png'
        if append == None: append = ''
        if not filename: filename = self.filename

        if filename:
            filename, __ = os.path.splitext(filename)
        
        filename = filename + append + '.' + figureExt
        
        fullpath = os.path.join(self.directory, filename)    

        self.fig.set_size_inches(18.5,10.5)
        plt.savefig(fullpath,dpi=100)
        

    def __listFiles(self, directory, extension='.txt'):
        """
        Returns a sorted list of files in the given directory, 
        filtered  by given extension
        """
        
        allfiles = os.listdir(directory)
        extension = extension.upper()
        
        lf = [os.path.join(directory,f) for f in allfiles if os.path.splitext(f)[1].upper() == extension]
        lf.sort()
        
        return lf        


    def output(self, show=None, save=None, filename=None, append=None):
        """
        Show and or save the figure
        """
        if show == None: show = self.show
        if save == None: save = self.save
        
        if show:
            self.__showFigure()
        
        if save:
            self.__saveFigure(filename, append)
        
            
    def distribute(self, bins=50, fly=None):
        """
        """
        if fly != None:
            x = self.a[:,fly,0]
        else:
            x = self.a[:,:,0]
        
        x = x.mean(1)

        self.__makeFigure()
        
        ax = self.fig.add_subplot(111)
        
        #n, bs, patches = ax.hist(x, bins, normed=1, facecolor='#736F6E', alpha=0.75)
        n, bs, patches = ax.hist(x, bins, facecolor='#736F6E', alpha=0.75)
        ax.grid(True)
        ax.grid(True)
        #ax.x_label('Position'); ax.y_label('Frequency')

        self.output(append='-dist')

    def plotOneFlyPath(self, fly, onecolor=False):
        """
        plot path of a single fly - must specify fly number
        """
        self.__makeFigure()

        x = self.a[:,fly,0]

        ax = self.fig.add_subplot(111)
        
        ax.xaxis.set_visible(False)
        ax.yaxis.set_visible(False)

        if onecolor:
            ax.plot( x,np.arange(len(x)), 'o-', color=COLORS['Light Grey'])
        else:
            xl = np.ma.array( x, mask=(x < self.midline_left) )
            ax.plot( xl,np.arange(len(x)), 'o-', color=COLORS['Red'])
            
            #x.mask = (x > self.midline)
            xr = np.ma.array( x, mask=(x >= self.midline_right) )
            ax.plot( xr,np.arange(len(x)), 'o-', color=COLORS['Light Blue'])
            
        ax.set_xlim((0, self.midline*2))

        self.output(append='-fly%02d' % fly)


    def plotAllpath(self, onecolor=False):
        """
        plot paths in the currently open figure and save it to file
        """
        flies = self.a.shape[1]
        rows = np.ceil( flies / 4.0 )
        self.__makeFigure()

        dc = self.totalDistanceMoved()

        for fly in range( flies ):

            x = self.a[:,fly,0]
            y_max = x.shape[0]

            ax = self.fig.add_subplot(COLS, rows, fly+1)
            
            is_last_row = (flies - fly) < COLS
            ax.xaxis.set_visible(is_last_row)
            ax.yaxis.set_visible(False)

            if onecolor:
                ax.plot( x,np.arange(len(x)), 'o-', color=COLORS['Light Grey'])
            else:
                xl = np.ma.array( x, mask=(x < self.midline) )
                ax.plot( xl ,np.arange(len(x)), 'o-', color=COLORS['Red'])
                
                xr = np.ma.array( x, mask=(x >= self.midline) )
                ax.plot( xr, np.arange(len(x)), 'o-', color=COLORS['Light Blue'])
                
            
            rect1 = mpl.patches.Rectangle((self.midline_left,0), (self.midline_right-self.midline_left), y_max, color=COLORS['Light Grey'])
            ax.add_patch(rect1)
            
            # Info about distance traveled
            #total distance on each side
            d_left = dc[fly,0]
            d_right = dc[fly,1] 
            
            #percentages
            d_left_perc = d_left / (d_left + d_right) * 100
            d_right_perc = d_right / (d_left + d_right) * 100
            
            #join into strings
            text_1_left = "%.0f (%02d" % (d_left, d_left_perc) + "%)"
            text_1_right = "%.0f (%02d" % (d_right, d_right_perc) + "%)"

            #write to figure
            ax.text(0.0, 1.05, text_1_left, ha='left', va='center', transform=ax.transAxes)
            ax.text(1.0, 1.05, text_1_right, ha='right', va='center', transform=ax.transAxes)
            
            # Info about time spent
            #total time on each side
            t_left = ( x < self.midline_left ).sum()
            t_right = ( x >= self.midline_right ).sum()
            
            #percentages
            t_left_perc = t_left * 1.0 / (t_left + t_right) * 100
            t_right_perc = t_right * 1.0 / (t_left + t_right) * 100
            
            #join into strings
            text_2_left = "%.0f (%02d" % (t_left, t_left_perc) + "%)"
            text_2_right = "%.0f (%02d" % (t_right, t_right_perc) + "%)"
            
            ax.text(0.0, 1.15, text_2_left, ha='left', va='center', transform=ax.transAxes)
            ax.text(1.0, 1.15, text_2_right, ha='right', va='center', transform=ax.transAxes)
            
            ax.set_xlim((0, self.midline*2))
            ax.set_ylim((0, y_max))

        self.output(append='-path')

    def plotStepsLength(self):
        """
        plot the lenght of each step
        """
        flies = self.a.shape[1] 
        rows = np.ceil( flies / 4.0 )
        self.__makeFigure()

        for fly in range( flies ):

            x = self.a[:,fly,0] # only x coordinates
            
            is_left = ( x < self.midline_left )
            is_right = ( x>= self.midline_right )
            
            x1 = np.roll(x, -1)
            d = ((x1 - x)[:-1]) # all the distances, step by step

            ax = self.fig.add_subplot(COLS, rows, fly+1)
            
            ax.xaxis.set_visible(False)
            ax.yaxis.set_visible(False)

            d.mask = is_left
            ax.plot( d, color=COLORS['Red'])

            d.mask = is_right
            ax.plot( d, color=COLORS['Light Blue'])
            

        self.output(append='-steps')

    def getAverageStep(self, fly):
        """
        return m, e
        
        m   the average distance in pixel a fly makes during the recording 
        e   the standard deviation of m
        
        """
        
        x = self.a[:,fly,0] # only x coordinates
        x1 = np.roll(x, -1)
        d = np.abs((x1 - x)[:-1]) # all the distances, step by step
        m = np.mean(d)
        e = np.std(d)
        
        return m, e

    def writeSummary(self, filename=None):
        """
        """
        
        src, _ = os.path.splitext(self.filename) 
        tt, tt_perc = self.preferenceIndex()
        lv = tt_perc[:,0]
        
        values = ','.join(['%.1f' % v for v in lv if v > 0])
        n = (tt_perc > 0).sum(0)[0]
        avg = np.mean(lv[lv>0])
        std = np.std(lv[lv>0])
        
        string = '%s,%s,%.2f,%.2f,%s,%s\n' % (src.upper(), self.description, avg, std, n, values)

        if filename != None:
            
            fh = open(filename, "a")
            fh.write(string)
            fh.close()
        else:
            print string

    def preferenceIndex(self, distance_thresh=2000):
        """
        """
        tot_distance_moved = self.totalDistanceMoved().sum(axis=1)
        #mask out those who did not move enough
        m = tot_distance_moved < distance_thresh #1D mask
        mm = np.vstack((m.T, m.T)).T #2D mask
        
        tt = self.totalTimeOnSides()
        tt.mask = mm
        
        tt_perc = np.vstack( ( (tt[:,0] * 100.0 / tt.sum(axis=1)).T, (tt[:,1] * 100.0 / tt.sum(axis=1)).T ) ).T
        
        return tt, tt_perc
        
        
    
    def totalTimeOnSides(self, t1=0, t2=1.0):
        """
        """
        
        x = self.a[:,:,0]
    
        t = x.shape[0]
        t1 = int(t*t1)
        t2 = int(t*t2)
       
        is_left = ( x[t1:t2] < self.midline_left ).sum(axis=0); is_right = ( x[t1:t2] > self.midline_right ).sum(axis=0)        
        tt = np.vstack(([is_left.T],[is_right.T])).T

        return np.ma.array(tt)
        
    
    def totalDistanceMoved(self):
        """
        """
        x = self.a[:,:,0]
        x1 = np.roll(x, -1, axis=0)
        
        xl = np.ma.array( x, mask=(x < self.midline_left) )
        xr = np.ma.array( x, mask=(x > self.midline_right) )
        
        d = np.abs( (x1 - x) ) # all the distances, step by step
        dl = np.ma.array( d, mask=(x < self.midline_left) )
        dr = np.ma.array( d, mask=(x > self.midline_right) )
        
        m = np.mean(d[:-1], axis=0) # average distance

        sl = np.sum(dl[:-1], axis=0) # distances on left 
        sr = np.sum(dr[:-1], axis=0) # distances on right

        s = np.sum(d[:-1], axis=0) # all distances, same as sl+sr
        
        sc = np.vstack(([sr.T],[sl.T])).T #sl and sr into 2D
        
        return sc
        

 
    def filterArtifacts(self, a):
        """
        """
        
        x = a[:,:,0]
        x1 = np.roll(x, -1, axis=0)
        d = np.abs( (x1 - x) ) # all the distances, step by step
        m = np.mean(d[:-1], axis=0)
        e = np.std(d[:-1], axis=0)
        
        x_mask = ((d - m) > (2 * e)) # outlier if diff is greater than 2STD
        
        q,w=x_mask.shape
        xy_mask = np.zeros((q,w,2))
        xy_mask[:,:,0] = x_mask
        xy_mask[:,:,1] = x_mask
        return np.ma.array(a, mask = xy_mask)


    def writeFlyPlaceRatio(self):
        """
        """
        
        #all the flies belong to the same txt file, so the 3D array is ok
        
        flies = self.a.shape[1] #num of flies

        filename, __ = os.path.splitext(self.filename)
        filename = filename + '-position.csv'
        fullpath = os.path.join(self.directory, filename)    
        fh = open(fullpath, 'w')

        #is_left_a + is_left_b + is_left_c = self.totalTimeOnSides()
        times_1st_third = self.totalTimeOnSides(t1=0, t2=1/3)
        times_2nd_third = self.totalTimeOnSides(t1=1/3, t2=2/3)
        times_3rd_third = self.totalTimeOnSides(t1=2/3, t2=3/3)
        total_times = self.totalTimeOnSides()
        

        for fly in range( flies ):

            is_left_a, is_right_a = times_1st_third[fly]
            is_left_b, is_right_b = times_2nd_third[fly]
            is_left_c, is_right_c = times_3rd_third[fly]
            is_left, is_right = total_times[fly]

            line = "%02d,%02d,%02d,%02d,%02d,%02d,%02d,%02d,%02d\n" % (fly+1, 
                                        is_left_a, is_right_a,
                                        is_left_b, is_right_b,
                                        is_left_c, is_right_c,
                                        is_left, is_right)
            print line#fh.write(line)
                                        
                                            
        fh.close()
                                        
if __name__ == '__main__':
    
    ot = None
    parser = optparse.OptionParser(usage='%prog [options] [argument]', version='%prog version 0.1')
    parser.add_option('-i', '--input', dest='source', metavar="SOURCE", help="File to be processed")
    parser.add_option('--vertical', action="store_false", default=True, dest='horizontal', help="Revert x & y. Use if mask is vertical instead of horizontal")
    parser.add_option('--distribution', action="store_true", default=False, dest='distribution', help="Show a histogram of distribution bins")
    parser.add_option('--path', action="store_true", default=False, dest='path', help="Show the path of all the flies")
    parser.add_option('--steps', action="store_true", default=False, dest='steps', help="Show a measure of the length of each step")
    parser.add_option('--ratio', action="store_true", default=False, dest='ratio', help="Plot a measure of time spent on one side or the other")
    parser.add_option('--showOnly', action="store_true", default=False, dest='showOnly', help="Do not save figure, just show it")

    (options, args) = parser.parse_args()

    show = options.showOnly
    save = not show

    if options.source and ( options.distribution or options.path or options.steps or options.ratio ):
        ot = odorTracker(options.source, save, show, options.horizontal)

    else:
        parser.print_help()    
        
    if ot and options.distribution:
        ot.distribute(10)
    
    if ot and options.path:
        ot.plotAllpath()

    if ot and options.steps:
        ot.plotStepsLength()

    if ot and options.ratio:
        ot.writeFlyPlaceRatio()

