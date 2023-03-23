__author__ = 'quentin'

from threading import Thread
import os
import time
import collections
import logging

import urllib.request, urllib.error, urllib.parse
import json
import usb
import serial

def connectedUSB(optional_file='/etc/modules.json'):
    """
    Returns a dictionary of connected USB devices from a known selection

    Known devices:
    #Arduino Micro
    Bus 001 Device 005: ID 2341:8037 Arduino SA Arduino Micro

    #Arduino Nano Every
    Bus 001 Device 006: ID 2341:0058 Arduino SA Arduino Nano Every

    #Lynxmotion SSC-32U
    Bus 001 Device 008: ID 0403:6001 Future Technology Devices International, Ltd FT232 Serial (UART) IC
    """

    
    # Hardwired interactors
    known = {
                'arduino_nano' : {'name' : 'Arduino Nano', 'family' : 'arduino', 'model' : 'nano', 'used_for' : ['optomotor', 'mAGO'], 'id' : ['2341:0058'] },
                'arduino_micro' : {'name' : 'Arduino Micro', 'family' : 'arduino', 'model' : 'micro', 'used_for' : ['optomotor', 'mAGO'], 'id' : ['2341:8037'] },
                'arduino_uno' : {'name' : 'Arduino UNO', 'family' : 'arduino', 'model' : 'uno', 'used_for' : [], 'id' : ['2341:0043'] },
                'arduino_leonardo' : {'name' : 'Arduino Leonardo', 'family' : 'arduino', 'model' : 'leonardo', 'used_for' : [], 'id' : ['2341:8036'] },
                'wemos_D1' : {'name' : 'Wemos D1', 'family' : 'ESP8266', 'model' : 'D1', 'used_for' : [], 'id' : ['1a86:7523'], 'aka' : 'CH340' },
                'lynxmotion_ssc32u' : {'name' : 'LynxMotion SSC-32U', 'family' : 'LynxMotion', 'model' : 'SSC-32U', 'used_for' : ['servo', 'AGO'], 'id' : ['0403:6001'], 'aka' : 'FT232'},
                'noUSB' : {'name' : 'python-usb not loaded', 'id' : ['0000:0000']} #in case pyUSB cannot be loaded
            }

    # potential user-specified interactors
    if os.path.exists(optional_file):
        with open (optional_file, 'r') as optional_modules_file:
            known.update ( json.load (optional_modules_file) )

    try: #needed for compatibility with older images
        import usb 
        devices = ['%s:%s' % ('{:x}'.format(dev.idVendor).zfill(4), '{:x}'.format(dev.idProduct).zfill(4) ) for dev in usb.core.find(find_all=True)]
    except:
        devices = ['0000:0000']

    # matchmaking
    found = {}
    for dev in known:
        for detected in devices: 
            if detected in known[dev]['id']:
                found[dev] = known[dev]

    return known, found       




class HardwareConnection(Thread):
    def __init__(self, interface_class, *args, **kwargs):
        """
        A class to build a connection to arbitrary hardware.
        It implements an instance of a :class:`~ethoscope.hardware.interfaces.interfaces.BaseInterface` which it uses to send instructions, asynchronously and  on demand.

        :param interface_class: the class to use a an interface to hardware (derives from :class:`~ethoscope.hardware.interfaces.interfaces.BaseInterface`)
        :type interface_class: class
        :param args: list of arguments passed the the hardware interface
        :param kwargs: list of keyword arguments passed the the hardware interface
        """
        self._interface_class = interface_class
        self._interface_args = args
        self._interface_kwargs = kwargs

        self._interface = interface_class(*args, **kwargs)
        self._instructions = collections.deque()
        self._connection_open = True
        super(HardwareConnection, self).__init__()
        self.start()
        
    def run(self):
        """
        Infinite loop that send instructions to the hardware interface
        Do not call directly, used the ``start()`` method instead.
        """
        while self._connection_open:
            time.sleep(.1)
            while len(self._instructions) > 0 and self._connection_open:
                instruc = self._instructions.popleft()
                try:
                    ret = self._interface.send(**instruc)
                except:
                    logging.error("Could not send the following instruction to the module. Instruction: %s" % instruc)

    def send_instruction(self, instruction=None):
        """
        Stage an instruction to be sent to the hardware interface.
        Instructions will be parsed sequentially, but asynchronously from the main thread execution.
        :param instruction: a dictionary of keyword arguments ,matching those of ``interface_class.send()``.
        :type instruction: dict()
        """
        if instruction is None:
            instruction = {}
        if not isinstance(instruction, dict):
            raise Exception("instructions should be dictionaries")
        self._instructions.append(instruction)

    def stop(self, error=None):
        self._connection_open = False
        
    def __del__(self):
        self.stop()

    def __getstate__(self):
        return {
                "interface_class": self._interface_class,
                "interface_args": self._interface_args,
                "interface_kwargs": self._interface_kwargs}

    def __setstate__(self, state):
        kwargs = state["interface_kwargs"]
        kwargs["do_warm_up"] = False
        self.__init__(state["interface_class"],
                      *state["interface_args"], **kwargs)


class SimpleSerialInterface(object):
    def __init__(self, port = None, baud = 115200, warmup = False):
        """
        Template class which is an abstract representation of a Serial hardware interface.
        It must define, in :func:`~ethoscope.hardware.interfaces.interfaces.BaseInterface.__init__`,
        how the interface is connected, and in :func:`~ethoscope.hardware.interfaces.interfaces.BaseInterface.send`,
        how information are communicated to the hardware. In addition, derived classes must implement a
        :func:`~ethoscope.hardware.interfaces.interfaces.BaseInterface._warm_up`, method, which defines optionnal instructions
        passed to the hardware upon first connection (that is useful to experimenters that want to manually check their settings).

        :param do_warm_up:
        """
        logging.info("Connecting to Serial port...")

        self._serial = None
        if port is None:
            self._port = self._find_port()
        else:
            self._port = port

        self._serial = serial.Serial(self._port, baud, timeout=2)
        time.sleep(2)
        #self._test_serial_connection()

        if warmup:
            self._warm_up()


    def _find_port(self):
        from serial.tools import list_ports
        import serial
        import os
        all_port_tuples = list_ports.comports()
        logging.info("listing serial ports")
        all_ports = set()
        for ap, _, _ in all_port_tuples:
            p = os.path.basename(ap)
            print(p)
            if p.startswith("ttyUSB") or p.startswith("ttyACM"):
                all_ports |= {ap}
                logging.info("\t%s", str(ap))

        if len(all_ports) == 0:
            logging.error("No valid port detected!. Possibly, device not plugged/detected.")
            raise NoValidPortError()

        elif len(all_ports) > 2:
            logging.info("Several port detected, using first one: %s", str(all_ports))
        return all_ports.pop()

    def __del__(self):
        if self._serial is not None:
            self._serial.close()
            #

    def _test_serial_connection(self):
        return

    def interrogate(self, test=False):
        """
        Try to interrogate the device to check what its capabilities are.
        Will work with all firmware for the new PCB and firmware newer than September 2020
        
        Ff test is True it will also attempt a test run using the information it just received.
        """
        self._serial.write(b"T\r\n")
        time.sleep(0.1)
        info = eval(self._serial.read_all())
        info['test'] = 'Not attempted'
        
        if test:
            try:
                logging.info("Sending Test command.")
                cmd = "%s\r\n" % info["test_button"]["command"]
                self._serial.write(cmd.encode())
                info['test'] = 'Success'
            except:
                    info['test'] = 'Failed'

        return info



    def _warm_up(self):
        raise NotImplementedError
        
    def send(self, **kwargs):
        """
        Method to request hardware interface to interact with the physical world.
        :param kwargs: keywords arguments
        """
        raise NotImplementedError


class DefaultInterface(SimpleSerialInterface):
    """
    Class that implements a dummy interface that does nothing. This can be used to keep software consistency when
    no hardware is to be used.
    """
    def _warm_up(self):
        pass
    def send(self, **kwargs):
        pass

class ScanException(Exception):
    pass

class EthoscopeSensor(object):
    """
    Class providing access to an ESP32 based WIFI ethoscope sensor
    """
    
    _sensor_values = {"temperature" : "FLOAT",
                      "humidity": "FLOAT",
                      "light": "INT",
                      "pressure" : "FLOAT"}


    def __init__(self, sensor_url):
        self._sensor_url = sensor_url
        self._last_read = 0
        self._update(True)

    def _get_json_from_url(self, url, timeout=5, post_data=None):
        try:
            if not url.startswith("http://"): url = "http://" + url
            req = urllib.request.Request(url, data=post_data, headers={'Content-Type': 'application/json'})
            f = urllib.request.urlopen(req, timeout=timeout)
            message = f.read()
            if not message:
                # logging.error("URL error whist scanning url: %s. No message back." % self._id_url)
                raise ScanException("No message back")
            try:
                resp = json.loads(message)
                return resp
            except ValueError:
                # logging.error("Could not parse response from %s as JSON object" % self._id_url)
                raise ScanException("Could not parse Json object")
        
        except urllib.error.HTTPError as e:
            raise ScanException("Error" + str(e.code))
            #return e
        
        except urllib.error.URLError as e:
            raise ScanException("Error" + str(e.reason))
            #return e
        
        except Exception as e:
            raise ScanException("Unexpected error" + str(e))

    def _update(self, force=False, freq=5):
        """
        Refresh sensor values
        It is usually a good idea not to interrogate the sensors too often
        to avoid overheating
        freq is the max interval in seconds
        """
        if (time.time() - self._last_read) > freq or force:
            self._sensor_data = self._get_json_from_url(self._sensor_url)
            self._last_read = time.time()

    def read_all(self):
        self._update()
        return tuple( [self._sensor_data[name] for name in self.sensor_properties] )

    @property
    def sensor_properties(self):
        self._update()
        return self._sensor_values.keys()

    @property
    def sensor_types(self):
        self._update()
        return self._sensor_values

    @property
    def temperature(self):
        self._update()
        return self._sensor_data["temperature"]

    @property
    def humidity(self):
        self._update()
        return self._sensor_data["humidity"]

    @property
    def light(self):
        self._update()
        return self._sensor_data["light"]

    @property
    def pressure(self):
        self._update()
        return self._sensor_data["pressure"]

