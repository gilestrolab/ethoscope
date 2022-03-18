#!/bin/env python

import fnmatch
import os

def make_index_file(path = '/ethoscope_data/results/'):

    index_file = os.path.join(path, "index.txt")
    
    matches = []
    for root, dirnames, filenames in os.walk(path):
        for filename in fnmatch.filter(filenames, '*.db'):
            matches.append( os.path.join(root, filename) )
            
    with open(index_file, "w") as ind:
        
        for db in matches:
            fp = os.path.relpath(db, path )
            fs = os.stat(fp).st_size
            ind.write('"%s", %s\n' % (fp, fs))

if __name__ == '__main__':
    make_index_file()
