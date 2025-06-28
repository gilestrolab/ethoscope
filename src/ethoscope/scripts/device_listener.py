#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  device_listener.py
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
#  This ethoscope listener controls the most basic ethoscope functions:
#
#  - Start / stop tracking with given options
#  - Start / stop video recording with given options
# 
#  Every other action is controlled through the web server. 
#  Decoupling these two activities increases robustness
#  Essentially it allows us to restart the web process and the avahi component without affecting the ethoscope
#  When it is running


__author__ = 'giorgio'

import logging
import traceback
from optparse import OptionParser
from ethoscope.web_utils.control_thread import ControlThread
from ethoscope.web_utils.record import ControlThreadVideoRecording
from ethoscope.web_utils.helpers import get_machine_id, get_machine_name, get_git_version, was_interrupted, PERSISTENT_STATE, getModuleCapabilities

import json
import socket
import threading
import os

class commandingThread(threading.Thread):
    def __init__(self, ethoscope_info, host='', port=5000):
        self.host = host
        self.port = port
        self.size = 1024
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(5)

        self.ethoscope_info = ethoscope_info
        self.control =  ControlThread ( machine_id = ethoscope_info['MACHINE_ID'],
                           name = ethoscope_info['MACHINE_NAME'],
                           version = ethoscope_info['GIT_VERSION'], 
                           ethoscope_dir = ethoscope_info['ETHOSCOPE_DIR'],
                           data=None )

        self.running = True
        threading.Thread.__init__(self)

    def stop(self):
        self.running = False
        #makes a dummy connection
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect( (self.host, self.port))
        self.sock.close()

    def run(self):
        '''
        listen for new connections and processes them as they arrive
        '''

        while self.running:
            client, address = self.sock.accept()
            try:
                recv = client.recv(self.size)
                if recv:
                    message = json.loads (recv)
                    result = json.dumps( {
                                            'response' : self.action( message['command'], message['data'] ) 
                                          }).encode('utf-8')
                    client.send(result)
            except:
                pass
        
            client.close()

    def run_i(self):
        '''
        listen for new incoming clients
        creates a new subthread for each incoming client with a timeout of 60 seconds
        '''

        while True:
            client, address = self.sock.accept()
            client.settimeout(60)
            threading.Thread(target = self.listenToClient, args = (client,address)).start()

    def listenToClient(self, client, address):
        '''
        start listening for registered client
        '''

        while True:
            try:
                recv = client.recv(self.size)
                
                if recv:
                    message = json.loads (recv)
                    result = json.dumps( {
                                            'response' : self.action( message['command'], message['data'] ) 
                                          }).encode('utf-8')
                    client.send(result)
    
            except:
                client.close()
                return False


    def action(self, action, data=None):
        '''
        act on client's instructions
        '''
        
        if not data and action in ['start', 'start_record']:
            return 'This action requires JSON data'
        
        if action == 'help':
            return "Commands that do not require JSON info: help, info, status, stop, stream, remove, restart.\nCommands that do require JSON info: start, start_record."
        
        elif action == 'info':
            return self.control.info
        
        elif action == 'status':
            return self.control.info['status']
        
        elif action == 'start' and data:
            self.control = ControlThread ( machine_id = self.ethoscope_info['MACHINE_ID'],
                               name = self.ethoscope_info['MACHINE_NAME'],
                               version = self.ethoscope_info['GIT_VERSION'], 
                               ethoscope_dir = self.ethoscope_info['ETHOSCOPE_DIR'],
                               data = data )
            self.control.start()

            logging.info("Starting tracking")
            return "Starting tracking activity"

        elif action == 'stream':
            self.control = ControlThreadVideoRecording ( machine_id = self.ethoscope_info['MACHINE_ID'],
                               name = self.ethoscope_info['MACHINE_NAME'],
                               version = self.ethoscope_info['GIT_VERSION'], 
                               ethoscope_dir = self.ethoscope_info['ETHOSCOPE_DIR'],
                               data = {'recorder': {'name': 'Streamer', 'arguments': {}}} )

            self.control.start()
            return "Starting streaming activity"

        elif action == 'start_record' and data:
            self.control = ControlThreadVideoRecording ( machine_id = self.ethoscope_info['MACHINE_ID'],
                               name = self.ethoscope_info['MACHINE_NAME'],
                               version = self.ethoscope_info['GIT_VERSION'], 
                               ethoscope_dir = self.ethoscope_info['ETHOSCOPE_DIR'],
                               data = data )

            self.control.start()
            return "Starting recording or streaming activity"


        elif action == 'stop' and self.control.info['status'] in ['running', 'recording', 'streaming'] :
            logging.info("Stopping monitor")
            self.control.stop()
            logging.info("Joining monitor")
            self.control.join()
            logging.info("Monitor joined")
            logging.info("Monitor stopped")
            return "Stopping ethoscope activity"

        elif action == 'remove' and self.control.info['status'] not in ['running', 'recording', 'streaming']:
            logging.info("Removing persistent file.")
            try:
                if os.path.exists(PERSISTENT_STATE):
                    os.remove(PERSISTENT_STATE)
                    return "The persistent file was succesfully removed"
                else:
                    return "The persistent file does not exist"
            except:
                return "The persistent file exists but could not be removed"

        elif action == 'restart' and self.control.info['status'] not in ['running', 'recording', 'streaming']:
            logging.info("Restarting the ethoscope device service")
            with os.popen('systemctl restart ethoscope_device.service') as df:
                outcome = df.read()
                logging.info(outcome)
                return outcome

        elif action == 'test_module' and not data:
            logging.info("Sending the test command to the connected module")
            return getModuleCapabilities(test=True)

        elif action == 'test_module' and data:
            logging.info("Restarting the ethoscope device service")
            return getModuleCapabilities(command=data['command'])

        else:
            #raise Exception("No such command: %s. Available commands are info, status, start, stop, start_record, stream " % action)
            return 'This ethoscope action is not available.'


if __name__ == '__main__':

    parser = OptionParser()
    parser.add_option("-r", "--run", dest="run", default=False, help="Runs tracking directly", action="store_true")
    parser.add_option("-v", "--record-video", dest="record_video", default=False, help="Records video instead of tracking", action="store_true")
    parser.add_option("-j", "--json", dest="json", default=None, help="A JSON config file")
    parser.add_option("-e", "--results-dir", dest="results_dir", default="/ethoscope_data/results", help="Where temporary result files are stored")
    parser.add_option("-D", "--debug", dest="debug", default=False, help="Shows all logging messages", action="store_true")

    (options, args) = parser.parse_args()
    option_dict = vars(options)

    if option_dict["debug"]:
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        logging.info("Logging using DEBUG SETTINGS")

    if option_dict["json"]:
        with open(option_dict["json"]) as f:
            json_data = json.loads(f.read())
    else:
        json_data = {}


    ethoscope_info = { 'MACHINE_ID' : get_machine_id(),
      'MACHINE_NAME' : get_machine_name(),
      'GIT_VERSION' : get_git_version(),
      'ETHOSCOPE_UPLOAD' : '/ethoscope_data/upload',
      'ETHOSCOPE_DIR' : option_dict['results_dir'],
      'DATA' : json_data
    }

    ethoscope = commandingThread(ethoscope_info)
    ethoscope.start()
    logging.info ('Ethoscope controlling server started and listening')

    if option_dict["run"] or was_interrupted():
        
        if option_dict["record_video"]:
            ethoscope.action( 'start_record' )
        else:
            ethoscope.action( 'start' )
        
