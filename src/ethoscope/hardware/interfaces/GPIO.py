#!/bin/env python

from optparse import OptionParser
import threading
import time, os
import RPi.GPIO as GPIO
import logging
import json, ast

GPIO.setmode(GPIO.BOARD)

class GPIOButtons():
    
    _ALLOWED_GPIOS = [7,11,12,13,15,16,18,22,29,31,32,33,35,36,37,38,40]

    def __init__(self, commands):
        
        self.BTN = [ Button ( int(b), commands[b]) for b in commands if int(b) in self._ALLOWED_GPIOS  ]

        logging.info("Listening for buttons: %s. Press CTRL+C to exit." % ",".join([ str(B.channel) for B in self.BTN ]))
        
    def exit(self):
        GPIO.cleanup() # cleanup all GPIO
        for B in self.BTN: 
            B.stop()



class Button(threading.Thread):
    def __init__(self, channel, commands={ '0' : '', '5' : ''} ):
        threading.Thread.__init__(self)
        
        self._pressed = False
        self._listen = True

        self.actions = {}
        for t in commands:
            self.actions.update( { int(t) : commands[t]} )
        self.time_thresholds = sorted([int(k) for k in commands], reverse=True)

        self.channel = int(channel)
        GPIO.setup(self.channel, GPIO.IN, pull_up_down=GPIO.PUD_UP) # Button pin set as input
        
        self.deamon = True
        self.last_pressed = time.time()

        self.start()

    def action(self, command):
        '''
        '''
        logging.info("Executing external command: %s" % command)
        os.system(command)
        
    def stop(self):
        self._listen = False

    def run(self):
        while self._listen:
            if GPIO.input(self.channel): #button released
                if self._pressed == True:
                    self._pressed = False
                    
                    pt = time.time() - self.last_pressed
                    
                    for t in self.time_thresholds:
                        if pt >= t:
                            self.action(self.actions[t])
                            break
            
            else: #button pressed
                if self._pressed == False:
                    self._pressed = True
                    self.last_pressed = time.time()

def json_create(content = {}, filename="/etc/gpio.conf"):
    '''
    Shows how to create a json file that can be used to specify GPIOs and associated commands
    The top level values in the dictionary specify the GPIO number (BOARD format) and for each GPIO
    one can specify actions to take after a quick click (0) or after a pression lasting x seconds.
    '''
    
    if content == {}:
        content = { 33: {0: "systemctl restart ethoscope_device", 3: "reboot"},
                   37: {0: "ethoclient stop", 3 : "poweroff" } }
                   
    with open(filename, 'w') as fp:
        json.dump(content, fp)
        
    return content
        
def json_load(filename="/etc/gpio.conf"):
    '''
    '''
    with open(filename, 'r') as fp:
        content = json.load(fp)
        
    return content

if __name__ == '__main__':

    #The ethoscope PCB is connected on PINs 13,26 (BCM) or 33, 37 (BOARD) https://www.notion.so/giorgiogilestro/GPIO-PCB-9665d6c670e34f5eab229cf2d18c569d

    DEFAULT_JSON_FILE = "/etc/gpio.conf"

    parser = OptionParser()
    parser.add_option("-D", "--debug", dest="debug", default=True, help="Shows all logging messages", action="store_true")
    parser.add_option("-C", "--jsonfile", dest="commands", help="A JSON file describing which command to associate to each button", default=DEFAULT_JSON_FILE)
    parser.add_option("-S", "--jsonstring", dest="jsonstring", help="A JSON string describing which command to associate to each button")
    

    (options, args) = parser.parse_args()
    option_dict = vars(options)
        
    DEBUG = option_dict["debug"]
    if DEBUG:
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        logging.info("Logging using DEBUG SETTINGS")

    if option_dict["jsonstring"]:
        commands = ast.literal_eval(ast.literal_eval(json.dumps(option_dict["jsonstring"])))
    
    else:
        try:
            commands = json_load(option_dict["commands"])
        except:
            if not os.path.exists(DEFAULT_JSON_FILE):
                logging.error("A valid JSON file specifying the buttons to be used was not passed as an argument. Creating a default conf file in /etc/gpio.conf")
                try:
                    commands = json_create()
                except:
                    os.sys.exit("A valid JSON configuration file could not be created in %" % DEFAULT_JSON_FILE)
            else:
                os.sys.exit("Error loading JSON from the provided file: %" % option_dict["commands"])
                
    BTNs = GPIOButtons( commands )
    try:
        pass
    except KeyboardInterrupt: # If CTRL+C is pressed, exit cleanly:
        BTNs.exit()
