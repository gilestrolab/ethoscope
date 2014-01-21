#!/usr/bin/env python2
# -*- coding: utf-8 -*-
#
#  sleepDeprivator.py
#  
#  Copyright 2012 Giorgio Gilestro <giorgio@gilest.ro>
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

from damrealtime import SDrealtime
from time import sleep
from datetime import datetime as dt

import os
import optparse

import serial 
from serial.tools import list_ports

__version__ = '0.3'

LAG = 5
BAUD = 57600
DEFAULT_PORT = '/dev/ttyACM0'

def ping(port=DEFAULT_PORT, baud=BAUD):
    """
    is the machine alive?
    """
    try:
        ser = serial.Serial(port, BAUD)
        sleep(2)
        ser.write("L\n")    
        r = ser.readline()
        return True
    except:
        return False

def checkNewVersion(port=DEFAULT_PORT, baud=BAUD):
    """
    """
    from urllib import urlopen
    
    r = ""
    current_version = 0
    ser = serial.Serial(port, BAUD)
    sleep(2)
    ser.flushInput()
    
    ser.write("L\n")
    sleep(2)
    r = ser.readline()
    current_version = r.split(": ")[1]
    #for i in r:
    #    if "Version" in i: current_version = i.split(": ")[1]
        
    webaddress = 'https://raw2.github.com/gilestrolab/fly-sleepdeprivator/master/control_software/sleepdeprivator.py'
    try:
        pg = urlopen(webaddress).read()
        ix = p.find("__version__ = '") + len("__version__= '")
        new_version = pg[ix:ix+3]
    except:
        new_version = '0.0'
      
    if new_version > current_version:
        print "A new version of the sleep deprivator firmware was found! Please update to %s" % new_version
    else:
        print "You are already running the latest version %s" % current_version

def start_automatic(port=DEFAULT_PORT, baud=BAUD, use_serial=True):
    """
    Sleep deprivation in automatic mode, without input from
    pySolo-Video
    """

    if use_serial:
        ser = serial.Serial(port, BAUD)
        sleep(2)
        ser.write("AUTO\n")
        print "Now running in auto mode"
    else:
        print ("AUTO\n")
        

def serialPorts():
    """
    Returns a generator for all available serial ports
    """
    if os.name == 'nt':
        # windows
        for i in range(256):
            try:
                s = serial.Serial(i)
                s.close()
                yield 'COM' + str(i + 1)
            except serial.SerialException:
                pass
    else:
        # unix
        for port in list_ports.comports():
            yield port[0]

def listSerialPorts():
    """
    """

    return list(serialPorts())

def start(path, use_serial=True, port=DEFAULT_PORT, baud=BAUD):
    """
    Sleep deprivation routine
    """

    if use_serial: 
        ser = serial.Serial(port, BAUD)
        sleep(2)

    r = SDrealtime(path=path)

    for fname in r.listDAMMonitors():
        command = r.deprive(fname)
        print command
        if command and use_serial:
            print '%s - Sent to Serial port %s' % (dt.now(), port)
            ser.write(command)
        else:
            print '%s - Nothing to send to serial port' % dt.now()

    if use_serial: ser.close()

def deprive(channels, use_serial=True, port=DEFAULT_PORT, baud=BAUD):
    """
    Deprive single channels
    """
    
    cmd = ""
    
    if use_serial: 
        ser = serial.Serial(port, BAUD)
        sleep(2)
    
    cmd = '\n'.join(['M %02d' % (c+1) for c in channels])

    print "sent command to port %s" % port
    print cmd

    
    if cmd and use_serial:
        ser.write(cmd)
        
    if use_serial: ser.close()        
    
    if not use_serial:
        print "Debug mode"
        print "I would have sent the following command: %s" % cmd

if __name__ == '__main__':


    usage =  '%prog [options] [argument]\n'
    version= '%prog version ' + str(__version__)

    parser = optparse.OptionParser(usage=usage, version=version )
    parser.add_option('-p', '--port', dest='port', metavar="/dev/ttyXXX", default=DEFAULT_PORT, help="Specifies the serial port to which the SD is connected. Default /dev/ttyACM0")
    parser.add_option('-d', '--d', dest='path', metavar="/path/to/data/", help="Specifies the path to the monitor to be sleep deprived. If a folder is given, all monitors inside will be sleep deprived.")
    parser.add_option('--simulate', action="store_false", default=True, dest='use_serial', help="Simulate action only")
    parser.add_option('--daemon', action="store_true", default=False, dest='daemon_mode', help="Run in daemon mode (continously every 5 minutes)")
    parser.add_option('--automatic', action="store_true", default=False, dest='automatic_mode', help="Activate automatic mode")
    parser.add_option('--checkVersion', action="store_true", default=False, dest='check_version', help="Check if a new version of the software is available. Internet connection needed.")
    parser.add_option('--listports', action="store_true", default=False, dest='list_ports', help="List all serial ports available in the system")

    (options, args) = parser.parse_args()

    if options.daemon_mode and options.path:
        print "Starting daemon mode"
        print "Running every %s minutes. Enter Ctrl-C to terminate." % LAG
        while True:
            start(options.path, options.use_serial, options.port)
            sleep(LAG*60)
    elif options.path and not options.daemon_mode and not options.automatic_mode:
        start(options.path, options.use_serial, options.port)
    elif options.automatic_mode:
        start_automatic(options.port, use_serial=options.use_serial)
    elif options.check_version:
        checkNewVersion(options.port)
    elif options.list_ports:
        print listSerialPorts()
    else:
        parser.print_help()

