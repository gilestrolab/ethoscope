#!/usr/bin/env python2
# -*- coding: utf-8 -*-
#
#  DAMrealtime.py
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

import os, datetime, smtplib
from email.mime.text import MIMEText
from email.MIMEMultipart import MIMEMultipart
import numpy as np
import serial
from time import strptime


class DAMrealtime():
    def __init__(self, path, email=None):
        '''
        '''
        
        self.path = path
        
        if email:
            self.email_sender = email['sender']
            self.email_recipient = email['recipient']
            self.email_server = email['server']
            
            
        self.env = dict (min_temperature = 16,
                    max_temperature = 30,
                    min_humidity = 5,
                    max_humidity = 90,
                    min_day_light = 100,
                    max_night_light = 10,
                    dawn = '08:00',
                    dusk = '20:00'
                    )
                    
                    
                    

    def getDAMStatus(self, filename):
        '''
        scan given filename and return last recorded monitor status
        '''
        fh = open (filename, 'r')
        lastline = fh.read().split('\n')[-2]
        fh.close()
        
        value = lastline.split('\t')[3]
        
        return value
        

    def __listFiles(self, path, prefix):
        '''
        '''
        l = ''
        if not os.path.isfile(path):
                dirList=os.listdir(path)
                l = [os.path.join(path, f) for f in dirList if prefix in f]
        
        elif prefix in path:
                l = [path]
                
        return l



    def listDAMMonitors(self, prefix='Monitor'):
        '''
        list all monitor files in the specified path.
        prefix should match the file name
        filename        prefix

        Monitor01.txt   Monitor
        MON01.txt       MON
        '''
        
        return self.__listFiles(self.path, prefix)


    def alert(self, problems):
        '''
        problems is a list of tuples
        each tuple contains two values: the filename where the problem
        was detected, and the problem
        
        problems = [('Monitor1.txt','50')]
        
        '''
        
        now = datetime.datetime.now()
        message = 'At %s, found problems with the following monitors:\n' % now
        
        for (monitor, value) in problems:
            message += '%s\t%s\n' % (os.path.split(monitor)[1], value)


       
        msg = MIMEMultipart()
        msg['From'] = 'Fly Dam Alert service'
        msg['To'] =  self.email_recipient
        msg['Subject'] = 'flyDAM alert!'


        try:
            text = MIMEText(message, 'plain')
            msg.attach(text)

            s = smtplib.SMTP(self.email_server)
            s.sendmail( self.email_sender, self.email_recipient, msg.as_string() )
            s.quit()

            print msg.as_string()

        except smtplib.SMTPException:
           print "Error: unable to send email"



class SDrealtime(DAMrealtime):
    def __init__(self, *args, **kwargs):

        DAMrealtime.__init__(self, *args, **kwargs)

    def getAsleep(self, filename, interval=5):
        '''
        Scan the specified filename and return which one of the channels
        has not been moving for the past "interval" minutes
        Format of the DAM files is:
        1	09 Dec 11	19:02:19	1	0	1	0	0	0	?		[actual_activity]
        '''
        
        interval_for_dead = 60 #dead if they haven't moved in this time
        
        fh = open (filename, 'r')
        lastlines = fh.read().split('\n')[ - (2+interval_for_dead) : -2] 
        #here takes the last 60 lines; 
        #this equals the last 60 minutes for distance and vbc but not for positions of flies!
        fh.close()
        
        header = lastlines[0].split('\t')
        trackType = int(header[5])
        #isSDMonitor = int(header[6])
        #monitorNumber = int(header[7])

       
        if trackType == 0: #Actual Distance

                activity = np.array( [ line.split('\t')[10:] for line in lastlines ], dtype=np.int )
                dead_threshold = 50
                asleep_threshold = 10 * interval

                dead = ( activity.sum(axis=0) <= dead_threshold ) * 1
                asleep = ( activity[-interval:].sum(axis=0) <= asleep_threshold ) * 1
                awake = ( activity[-interval:].sum(axis=0) > asleep_threshold ) * 1
                sleepDep = asleep - dead

                
        elif trackType == 1: #Virtual Beam Crossing

                activity = np.array( [ line.split('\t')[10:] for line in lastlines ], dtype=np.int )
                dead_threshold = 50
                asleep_threshold = 10 * interval

                # dead because they didn't move for the past x mins
                dead = ( activity.sum(axis=0) <= dead_threshold ) * 1
                # didn't move in the past "interval"
                asleep = ( activity[-interval:].sum(axis=0) <= asleep_threshold ) * 1
                # did move in the past "interval"
                awake = ( activity[-interval:].sum(axis=0) > asleep_threshold ) * 1
                # asleep but not dead
                sleepDep = asleep - dead
                
        elif trackType == 2: # Position of flies
                sleepDep = 0
                os.sys.exit("FATAL ERROR. SD with position of flies is not yet implemented!")
        
        return sleepDep


        
    
    def deprive(self, fname, interval=5):
        '''
        check which flies are asleep and send command to arduino
        connected on serial port
        '''
        
        monitor = int ( filter(lambda x: x.isdigit(), os.path.split(fname)[1] ) )
        if monitor > 50 : monitor = monitor - 50
        
        flies = self.getAsleep(fname, interval)
        #cmd = ['M %02d %02d' % (monitor, channel+1) for (channel,sleeping) in enumerate(flies) if sleeping] 
        cmd = ['M %02d' % (channel+1) for (channel,sleeping) in enumerate(flies) if sleeping] 
        
        return '\n'.join(cmd)

            
class ENVrealtime(DAMrealtime):
    def __init__(self, *args, **kwargs):

        DAMrealtime.__init__(self, *args, **kwargs)
        self.flymon_path = os.path.join(path, 'flymons')

    def listEnvMonitors(self, prefix='flymon'):
        '''
        list all monitor files in the Environmental monitors path.
        prefix should match the file name
        filename        prefix
        '''
        return self.__listFiles(self.flymon_path, prefix)

    def hasEnvProblem(self, filename):
        '''
        1	09 Dec 11	19:02:19	m	t1	h1	l1	t2	bat
        '''
        fh = open (filename, 'r')
        lastline = fh.read().strip().split('\n')[-2]
        fh.close()
        
        count, date, time, mid, t1, h1, l1, t2, bat = lastline.split('\t')
        
        rec_time = strptime(date + ' ' + time, '%d %b %Y %H:%M:%S')
        dusk = strptime (self.env['dusk'], '%H:%M')
        dawn = strptime (self.env['dawn'], '%H:%M')
        
        
        isNight = rec_time.tm_hour > dusk.tm_hour and rec_time.tm_min > dusk.tm_min
        isDay = not isNight
        
        temperature_problem = float(t1) < self.env['min_temperature'] or float(t1) > self.env['max_temperature']
        humidity_problem = float(h1) < self.env['min_humidity'] or float(h1) > self.env['max_humidity']
        light_problem = isNight and int(l1) > self.env['max_night_light'] or isDay and int(l1) < self.env['min_day_light']
        
        if temperature_problem or humidity_problem or light_problem:
                return count, date, time, mid, t1, h1, l1, t2, bat
        else:
                return False

