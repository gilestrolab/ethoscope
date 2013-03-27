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

import numpy as np
import optparse, os
import matplotlib.pyplot as plt
import matplotlib.mlab as mlab

COLORS = dict ({'Blue': '#0066cc', 'Brown': '#660000', 'Pink': '#ff99cc', 'Blue Marine': '#466086', 'Light Grey': '#999999', 'Purple': '#990099', 'Light Pink': '#ffcc99', 'Grey': '#666666', 'Yellow': '#ffcc00', 'Olive Green': '#989e67', 'Dark Orange': '#ff8040', 'Bright Yellow': '#ffff00', 'Green': '#33cc33', 'Light Yellow': '#ffff99', 'Light Green': '#ccff99', 'Dark Purple': '#663366', 'Light Blue': '#99ccff', 'Dark Grey': '#333333', 'Red': '#cc0033', 'Dark Green': '#336633'})


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

        if os.path.isdir(source):
            pass
        
        self.midline = max(self.a[:,:,0].flatten())/2 # all x coordinates
        
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
            
            a = np.zeros( (frames, flies, 2) )

            #default orientation is with horizontal tubes
            #if tubes are vertical, we need to invert the coordinates
            
            for n, line in enumerate(coords):
                if horizontal:
                    cs = [ ( float (c.split(',')[0] ), float (c.split(',')[1]) ) for c in line  ]
                else:
                    cs = [ ( float (c.split(',')[1] ), float (c.split(',')[0]) ) for c in line  ]
                   
                a[n] = np.array(cs)
                
            return a
            
           
        except IOError:
            print "Error opening the file"

    def __makeFigure(self, clean=True):
        """
        """
        if not self.fig or clean:
            self.fig = plt.figure(figsize=(8,6), dpi=120)
            
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

    def plotOneFlyPath(self, fly):
        """
        plot path of a single fly - must specify fly number
        """
        self.__makeFigure()


        x = self.a[:,fly,0]
        #coords = self.a[:,fly]

        ax = self.fig.add_subplot(111)
        
        ax.xaxis.set_visible(False)
        ax.yaxis.set_visible(False)

        ax.plot( x,np.arange(len(x)), 'o-', color='#736F6E')

        self.output(append='-fly%02d' % fly)
        
        
    def plotAllpath(self, onecolor=False):
        """
        plot paths in the currently open figure and save it to file
        """
        flies = self.a.shape[1]
        cols = 4
        rows = np.ceil( flies / 4.0 )
        self.__makeFigure()

        for fly in range( flies ):

            x = np.ma.MaskedArray( self.a[:,fly,0] )
            #coords = self.a[:,fly]

            ax = self.fig.add_subplot(cols, rows, fly+1)
            
            ax.xaxis.set_visible(False)
            ax.yaxis.set_visible(False)

            if onecolor:
                ax.plot( x,np.arange(len(x)), 'o-', color=COLORS['Light Grey'])
            else:
                x.mask = (x < self.midline)
                ax.plot( x,np.arange(len(x)), 'o-', color=COLORS['Red'])
                x.mask = (x > self.midline)
                ax.plot( x,np.arange(len(x)), 'o-', color=COLORS['Light Blue'])
            
            ax.set_xlim((0, 500))

        self.output(append='-path')

    def plotStepsLength(self):
        """
        plot the lenght of each step
        """
        flies = self.a.shape[1] 
        cols = 4
        rows = np.ceil( flies / 4.0 )
        self.__makeFigure()

        for fly in range( flies ):

            x = self.a[:,fly,0] # only x coordinates
            
            is_left = ( x < self.midline )
            is_right = ( x>= self.midline )
            
            x1 = np.roll(x, -1)
            d = np.ma.MaskedArray( ((x1 - x)[:-1]) )# all the distances, step by step

            ax = self.fig.add_subplot(cols, rows, fly+1)
            
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
        
    def filterArtifacts(self, fly):
        """
        """
        pass



    def __listFiles(self, directory):
        """
        Returns a sorted list of txt files in the given directory
        """
        
        allfiles = os.listdir(directory)
        
        lf = [os.path.join(directory,f) for f in allfiles if os.path.splitext(f)[1] == '.txt']
        lf.sort()
        
        return lf


    def plotFlyPath(self, source, onecolor=False):
        """
        """
        
        fileList = self.__listFiles(source)
        n = len(fileList)
        
               #for sake of simplicity we use a list of arrays instead of a 3D array 
        a = [] #because number of frames are going to be different from one file to another
        
        for f in fileList:
            a.append ( self.__readFile(f) )

        #check that all array have the same number of flies
        allSameSize = len(set([sa.shape[1] for sa in a])) == 1
        assert allSameSize == True, "All files must contain the same number of flies in the mask"
        flies = a[0].shape[1]
        
        cols = 4
        rows = np.ceil( n / 4.0 )

        for fly in range( flies ):

            self.__makeFigure()

            for fn in range( n ):

                x = np.ma.MaskedArray( a[fn][:,fly,0] )
                #coords = self.a[:,fly]

                ax = self.fig.add_subplot(cols, rows, fn+1)
                
                ax.xaxis.set_visible(False)
                ax.yaxis.set_visible(False)

                if onecolor:
                    ax.plot( x,np.arange(len(x)), 'o-', color=COLORS['Light Grey'])
                else:
                    x.mask = (x < self.midline)
                    ax.plot( x,np.arange(len(x)), 'o-', color=COLORS['Red'])
                    x.mask = (x > self.midline)
                    ax.plot( x,np.arange(len(x)), 'o-', color=COLORS['Light Blue'])
                
                ax.set_xlim((0, 500))

            self.output(append='path-fly%02d' % (fly+1) )

    def plotFlySteps(self, source, onecolor=False):
        """
        """
        
        fileList = self.__listFiles(source)
        n = len(fileList)
        
               #for sake of simplicity we use a list of arrays instead of a 3D array 
        a = [] #because number of frames are going to be different from one file to another
        
        for f in fileList:
            a.append ( self.__readFile(f) )

        #check that all array have the same number of flies
        allSameSize = len(set([sa.shape[1] for sa in a])) == 1
        assert allSameSize == True, "All files must contain the same number of flies in the mask"
        flies = a[0].shape[1]
        
        cols = 4
        rows = np.ceil( n / 4.0 )

        for fly in range( flies ):

            self.__makeFigure()

            for fn in range( n ):

                x = a[fn][:,fly,0] # only x coordinates
                
                is_left = ( x < self.midline )
                is_right = ( x>= self.midline )
                
                x1 = np.roll(x, -1)
                d = np.ma.MaskedArray( ((x1 - x)[:-1]) )# all the distances, step by step

                ax = self.fig.add_subplot(cols, rows, fn+1)
                
                ax.xaxis.set_visible(False)
                ax.yaxis.set_visible(False)

                d.mask = is_left
                ax.plot( d, color=COLORS['Red'])

                d.mask = is_right
                ax.plot( d, color=COLORS['Light Blue'])


            self.output(append='steps-fly%02d' % (fly+1) )

    def writeFlyPlaceRatio(self):
        """
        """
        
        #all the flies belong to the same txt file, so the 3D array is ok
        
        flies = self.a.shape[1] #num of flies

        filename, __ = os.path.splitext(self.filename)
        filename = filename + '-position.csv'
        fullpath = os.path.join(self.directory, filename)    
        fh = open(fullpath, 'w')


        for fly in range( flies ):

            x = np.ma.MaskedArray( self.a[:,fly,0] )
            #coords = self.a[:,fly]

            # this counts the number of points (and hence of seconds) past on each side of the self.midline
            # return one value for each zone

            t = x.shape[0]
            a = int(t*1/3) 
            b = int(t*2/3)
            
            is_left_a = ( x[:a] < self.midline ).sum(); is_right_a = ( x[:a] >= self.midline ).sum()
            is_left_b = ( x[a:b] < self.midline ).sum(); is_right_b = ( x[a:b] >= self.midline ).sum()
            is_left_c = ( x[b:] < self.midline ).sum(); is_right_c = ( x[b:] >= self.midline ).sum()
            is_left = ( x < self.midline ).sum(); is_right = ( x >= self.midline ).sum()
            

            fh.write( "%02d,%02d,%02d,%02d,%02d,%02d,%02d,%02d,%02d\n" % (fly+1, 
                                        is_left_a, is_right_a,
                                        is_left_b, is_right_b,
                                        is_left_c, is_right_c,
                                        is_left, is_right)
                                        
                    )
                                            
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

