__author__ = 'quentin'

from threading import Thread
import time
import collections

import urllib.request, urllib.error, urllib.parse
import json


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
                ret = self._interface.send(**instruc)

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


class BaseInterface(object):
    def __init__(self, do_warm_up = True):
        """
        Template class which is an abstract representation of an hardware interface.
        It must define, in :func:`~ethoscope.hardware.interfaces.interfaces.BaseInterface.__init__`,
        how the interface is connected, and in :func:`~ethoscope.hardware.interfaces.interfaces.BaseInterface.send`,
        how information are communicated to the hardware. In addition, derived classes must implement a
        :func:`~ethoscope.hardware.interfaces.interfaces.BaseInterface._warm_up`, method, which defines optionnal instructions
        passed to the hardware upon first connection (that is useful to experimenters that want to manually check their settings).

        :param do_warm_up:
        """
        if do_warm_up:
            self._warm_up()

    def _warm_up(self):
        raise NotImplementedError
    def send(self, **kwargs):
        """
        Method to request hardware interface to interact with the physical world.
        :param kwargs: keywords arguments
        """
        raise NotImplementedError


class DefaultInterface(BaseInterface):
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

