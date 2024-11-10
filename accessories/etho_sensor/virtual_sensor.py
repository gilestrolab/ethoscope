#!/bin/env python3

# This script simulates a virtual hardware sensor with its corresponding network service advertisements
# and a RESTful API server. 
# It uses the Zeroconf/mDNS protocol for service discovery on a local network and the Bottle framework
# for setting up HTTP endpoints. The virtual sensor can provide dummy data such as temperature, humidity,
# pressure, and light, and allows updating its configuration details such as sensor name and location
# through POST requests. 
#
# The script can operate in two modes: as a sensor or as a zeroconf service listener that lists the 
# sensors discovered on the network.


from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser
import bottle
import socket
import random
import json

from optparse import OptionParser

MAC_ADDRESS = ':'.join('%02x'%random.randint(0,255) for x in range(6))
PORT = 8001
JSONFILE = "config_sensor.json"

try:
    config = json.load( open( JSONFILE ) )
except:
    config = { 'sensor_name' : 'virtual-test-sensor',
               'location' : 'default' }

app = bottle.Bottle()

class hwsensor():
    '''
    the hardware sensor
    '''
    def __init__(self):
        pass
    
    @property
    def getTemperature(self):
        return 0

    @property
    def getHumidity(self):
        return 0

    @property
    def getPressure(self):
        return 0

    @property
    def getLight(self):
        return 0
        

class SensorListener():

    def remove_service(self, zeroconf, type, name):
        print("Service %s removed" % (name,))

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        print("Service %s added, service info: %s" % (name, info))
        print (info.port)


class virtualSensor():
 
    __net_suffix = "local"

    def __init__(self):
        """
        """
        self.hostname = socket.gethostname()
        self.address = socket.gethostbyname(self.hostname + "." + self.__net_suffix)
        self.port = PORT
        self.uid = "virtual_sensor_%s" % MAC_ADDRESS

        try:
            serviceInfo = ServiceInfo("_sensor._tcp.%s." % self.__net_suffix,
                            self.uid + "._sensor._tcp.%s." % self.__net_suffix,
                            addresses = [socket.inet_aton(self.address)],
                            port = PORT,
                            properties = {
                                'version': '0.0.1',
                                'id_page': '/id',
                                'settings' : '/set'
                            } )
        except:
            serviceInfo = ServiceInfo("_sensor._tcp.%s." % self.__net_suffix,
                            self.uid + "._sensor._tcp.%s." % self.__net_suffix,
                            address = socket.inet_aton(self.address),
                            port = PORT,
                            properties = {
                                'version': '0.0.1',
                                'id_page': '/id',
                                'settings' : '/set'
                            } )
            

                
        zeroconf = Zeroconf()
        zeroconf.register_service(serviceInfo)

hws = hwsensor()


@app.get('/id')
def name():
    return {"id": MAC_ADDRESS}

@app.get('/')
def getdata():
    '''
    {"id": "2C:F4:32:65:10:0E", "ip" : "192.168.43.27", "name" : "etho_sensor", "location" : "", "temperature" : "0.00", "humidity" : "0.00", "pressure" : "0.00", "light" : "54612"}
    '''
    
    data = { "id" : MAC_ADDRESS,
             "ip" : bottle.request.get_header('host'),
             "name" : config['sensor_name'], 
             "location" : config['location'],
             "temperature" : hws.getTemperature,
             "humidity" : hws.getHumidity,
             "pressure" : hws.getPressure,
             "light" : hws.getLight
             }
    bottle.response.content_type = 'application/json'
    return json.dumps(data)
    #return data

@app.post('/set')
def set():
    '''
    '''
    input_string = bottle.request.body.read().decode("utf-8")
    # "location=place&sensor_name=name"
    try:
        for entry in input_string.split("&"):
            key, value = entry.split("=")
            config[key] = value
            
            print (config)

        json.dump( config, open( JSONFILE, 'w' ) )

        return {"DATA" : "OK"}
    except:
    
        return {"DATA" : "FAIL"}


def startSensor():
    '''
    '''
    sensor = virtualSensor()
    bottle.run(app, host='0.0.0.0', port=PORT)


def startListener():
    '''
    '''
    zeroconf = Zeroconf()
    listener = SensorListener()
    browser = ServiceBrowser(zeroconf, "_sensor._tcp.local.", listener)
    try:
        input("Press enter to exit...\n\n")
    finally:
        zeroconf.close()

if __name__ == '__main__':

    parser = OptionParser()
    parser.add_option("-l", "--listener", dest="listener", default=False, help="Runs the listener instead of the sensor", action="store_true")

    (options, args) = parser.parse_args()
    option_dict = vars(options)

    if option_dict["listener"]:
        startListener()
    else:
        startSensor()


