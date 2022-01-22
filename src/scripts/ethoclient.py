#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  ethoclient.py
#  
#  Copyright 2022 Giorgio F. Gilestro <gg@jenner>
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
#  This script can be used to interrogate and control the device_listener on any ethoscope
#  It can be used to start and stop tracking from the command line
#  Mostly useful as conceptual tool in real life

from optparse import OptionParser
import socket
import json


def send_command(action, data=None, host='127.0.0.1', port=5000, size=1024):
    '''
    interfaces with the listening server
    '''

    message = {'command' : action,
               'data' : data }

    try:
               
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
            s.sendall( json.dumps(message).encode('utf-8') )
            response = s.recv(size)
            r = json.loads( response )
        
        return r['response']

    except:
        return {}

if __name__ == '__main__':

    parser = OptionParser()
    parser.add_option("-s", "--server", dest="host", default='127.0.0.1', help="The IP of the ethoscope to be interrogated")
    parser.add_option("-c", "--command", dest="command", default='status', help="The command to be sent")
    parser.add_option("-d", "--data", dest="data", default='', help="dictionary with data to be sent")


    (options, args) = parser.parse_args()
    option_dict = vars(options)
   
    r = send_command( action = option_dict['command'], data = option_dict['data'], host = option_dict['host'] )
    print (r)
