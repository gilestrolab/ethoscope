#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  h264TOmp4.py
#  
#  Copyright 2020 Giorgio Gilestro <giorgio@gilest.ro>
#  
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#  
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#  
#  


from glob import glob
import os
from optparse import OptionParser


def process_video (folder, verbose=True):
    '''
    process video in folder
    '''
    
    #try:
    #move to folder
    os.chdir(folder)

    #prepare filenames
    with os.popen("ls *.h264 | head -n 1 | cut -d . -f 1") as cmd:
        prefix = "whole_%s" % cmd.read().rstrip()
    
    #calculate fps
    with os.popen("ls *.h264 | head -n 1 | cut -d _ -f 5 | cut -d @ -f 2") as cmd:
        fps = cmd.read().rstrip()
         
    tmp_file = "%s.tmp" % prefix
    filename = "%s.mp4" % prefix

    #merge files in one big chunk
    os.system( "cat *.h264  > %s" % tmp_file)
    
    os.system("ffmpeg -r %s -i %s -vcodec copy -y %s -loglevel panic" % ( fps, tmp_file, filename ) )
    
    os.system ("rm %s" % tmp_file)

    if verbose: print ("succesfully processed files in folder %s" % folder) 

    #except:
        
     #   return False


def list_ext (root_path, ext="mp4"):
    '''
    returns a list of folders that contains file with the given extension
    '''

    extension = "*.%s" % ext

    all_folders = [ x[0] for x in os.walk(root_path) ]
    have_mp4s = [p for p in all_folders if glob(os.path.join(p, extension))]
    
    return have_mp4s
    

def crawl (root_path):
    '''
    crawl all terminal folders in root_path
    '''

    all_folders = [ x[0] for x in os.walk(root_path) ]

    have_mp4s = [p for p in all_folders if glob(os.path.join(p, "*.mp4"))]
    terminal_folders = [p for p in all_folders if glob(os.path.join(p, "*.h264"))]
    
    for folder in terminal_folders:
        if folder not in have_mp4s:
            process_video (folder)
        


if __name__ == '__main__':
    
    parser = OptionParser()
    parser.add_option("-p", "--path", dest="path", default="/ethoscope_data/videos", help="The root path containing the videos to process")
    parser.add_option("-l", "--list", dest="list", default=False, help="Returns a list of folders containing mp4 files", action="store_true")

    (options, args) = parser.parse_args()
    option_dict = vars(options)
    
    if option_dict['list']:
        l = list_ext (option_dict['path'])
        
        print ("\n".join(l))
        print ("Found %s folders with mp4 files" % len(l))
        os.sys.exit()
    
    crawl( option_dict['path'] )
    
    
