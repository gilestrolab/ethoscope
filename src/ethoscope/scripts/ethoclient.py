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

COMM_PACKET_SIZE = 1024*16 # in bytes. This should be large because it has to account for possible raise error messages coming backs

def listenerIsAlive():
    '''
    Verifies the operational status of the listener service through a status command probe.
    
    Utilizes the send_command() function to execute a 'status' request. Captures operational
    exceptions to determine service availability.

    Returns:
        bool: True if the service responds successfully, False if any communication errors occur.
    '''
    try:
        r = send_command('status')
        return True
    except:
        return False

def send_command(action, data=None, host='127.0.0.1', port=5000, size=COMM_PACKET_SIZE):
    '''
    Executes remote command execution via TCP socket communication with a JSON protocol.
    
    Establishes a connection to the listener service, transmits structured commands, and retrieves
    responses. Manages socket lifecycle automatically and handles data serialization/deserialization.

    Args:
        action (str): Command identifier recognized by the remote service
        data (dict, optional): a dict to accompany the command in dictionary format
        host (str): IPv4 address of the target listener service
        port (int): TCP port number for service communication
        size (int): Maximum receive buffer size in bytes (must accommodate largest expected response)

    Returns:
        any: Deserialized response content from the service's JSON reply
        
    Raises:
        socket.error: On network communication failures
        json.JSONDecodeError: If malformed response data received
    '''

    message = {'command' : action,
               'data' : data }

              
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((host, port))
        s.sendall( json.dumps(message).encode('utf-8') )
        
        # Receive response in chunks until complete
        response = b''
        while True:
            chunk = s.recv(size)
            if not chunk:
                break
            response += chunk
            # Check if we have a complete JSON response
            try:
                json.loads(response.decode('utf-8', errors='ignore'))
                break  # Valid JSON received
            except json.JSONDecodeError:
                continue  # Keep receiving
        
        # Handle empty or invalid responses
        if not response:
            raise socket.error("Received empty response from server")
        
        # Decode bytes to string
        response_str = response.decode('utf-8', errors='ignore').strip()
        
        # Handle empty string after decoding
        if not response_str:
            raise socket.error("Received empty response after decoding")
        
        try:
            r = json.loads(response_str)
        except json.JSONDecodeError as e:
            # Log the problematic response for debugging
            print(f"Failed to parse JSON response: '{response_str[:100]}...' Error: {e}")
            raise json.JSONDecodeError(f"Invalid JSON response: {e}", response_str, e.pos)
    
    # Handle cases where response doesn't have expected structure
    if not isinstance(r, dict) or 'response' not in r:
        raise ValueError(f"Invalid response structure: {r}")
    
    return r['response']

if __name__ == '__main__':

    parser = OptionParser()
    parser.add_option("-s", "--server", dest="host", default='127.0.0.1', help="The IP of the ethoscope to be interrogated")
    parser.add_option("-c", "--command", dest="command", default='status', help="The command to be sent. Send help to receive a list of available commands.")
    parser.add_option("-d", "--data", dest="data", default='', help="dictionary with data to be sent")


    (options, args) = parser.parse_args()
    option_dict = vars(options)
   
    # Parse the data argument from JSON string to dict
    if option_dict['data']:
        try:
            data_dict = json.loads(option_dict['data'])
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON data: {e}")
            data_dict = None
    else:
        data_dict = None

    try:
        r = send_command(action=option_dict['command'], data=data_dict, host=option_dict['host'])
        print(r)
    except Exception as e:
        print(f"An error occurred: {e}")