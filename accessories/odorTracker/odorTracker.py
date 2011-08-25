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


class odorTracker():
    def __init__(self, filename):
        """
        """
        self.a = None
        self.fig = None

        self.filename = filename
        self.fromFile(self.filename)
        
    def fromFile(self, filename):
        """
        """
        coords = []
        try:
            fh = open(filename, 'r')
            rawfile = fh.read().split('\n')

            for line in rawfile:
                coords.append( line.split('\t')[8:] )

            fh.close()

            while [] in coords:
                coords.remove([])
            
            flies = len (coords[0])
            frames = len (coords)
            
            self.a = np.zeros( (frames, flies, 2) )

            for n, line in enumerate(coords):
                cs = [ ( float (c.split(',')[0] ), float (c.split(',')[1]) ) for c in line  ]
                self.a[n] = np.array(cs)
            
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
        
    def __saveFigure(self, filename=None, append=''):
        """
        """
        if not filename:
            filename = self.filename
        
        filename = os.path.splitext(filename)[0]+append+'.png'
        
        self.fig.set_size_inches(18.5,10.5)
        plt.savefig(filename,dpi=100)
            
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

        self.__saveFigure(append='-dist')

    def plotFlyPath(self, fly):
        """
        """
        self.__makeFigure()


        x = self.a[:,fly,0]
        #coords = self.a[:,fly]

        ax = self.fig.add_subplot(111)
        
        ax.xaxis.set_visible(False)
        ax.yaxis.set_visible(False)

        ax.plot( x,np.arange(len(x)), 'o-', color='#736F6E')

        self.__saveFigure(append='-fly%02d' % fly)
        
        
    def plotAllpath(self):
        """
        """
        flies = self.a.shape[1] 
        cols = 4
        rows = flies / 4
        self.__makeFigure()

        for fly in range( flies ):

            x = self.a[:,fly,0]
            #coords = self.a[:,fly]

            ax = self.fig.add_subplot(cols, rows, fly+1)
            
            ax.xaxis.set_visible(False)
            ax.yaxis.set_visible(False)

            ax.plot( x,np.arange(len(x)), 'o-', color='#736F6E')

        #self.__showFigure()
        self.__saveFigure(append='-path')

    

if __name__ == '__main__':
    
    ot = None
    parser = optparse.OptionParser(usage='%prog [options] [argument]', version='%prog version 0.1')
    parser.add_option('-i', '--input', dest='source', metavar="SOURCE", help="File to be processed")
    parser.add_option('--distribution', action="store_true", default=False, dest='distribution', help="Show a histogram of distribution bins")
    parser.add_option('--path', action="store_true", default=False, dest='path', help="Show the path of all the flies")

    (options, args) = parser.parse_args()

    if options.source and ( options.distribution or options.path ):
        ot = odorTracker(options.source)

    else:
        parser.print_help()    
        
    if ot and options.distribution:
        ot.distribute(10)
    
    if ot and options.path:
        ot.plotAllpath()

