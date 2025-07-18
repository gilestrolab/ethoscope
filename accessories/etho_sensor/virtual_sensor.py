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
from http.server import BaseHTTPRequestHandler, HTTPServer
import socket
import random
import json
import urllib.request
import urllib.error
import time
import os
import threading

from optparse import OptionParser

MAC_ADDRESS = ':'.join('%02x'%random.randint(0,255) for x in range(6))
PORT = 8001
DEFAULT_JSONFILE = "config_sensor.json"

# Global config variable - will be loaded after parsing command line arguments
config = None

# Global weather fetcher - will be initialized if zipcode is provided
weather_fetcher = None

class WeatherDataFetcher:
    """
    Fetches real weather data from OpenWeatherMap API (free tier)
    
    To use this feature:
    1. Sign up for free at https://openweathermap.org/api
    2. Get your API key
    3. Set environment variable: export OPENWEATHER_API_KEY=your_key_here
    4. Or pass API key via --api-key argument
    
    For European locations, use:
    - City names: "London,GB", "Paris,FR", "Berlin,DE", "Rome,IT"
    - Coordinates: "51.5074,-0.1278" (lat,lon for London)
    - City IDs: "2643743" (London's OpenWeatherMap city ID)
    """
    
    def __init__(self, location, api_key=None):
        self.location = location
        self.api_key = api_key or os.environ.get('OPENWEATHER_API_KEY')
        self.last_fetch_time = 0
        self.cache_duration = 600  # Cache for 10 minutes
        self.cached_data = None
        
        if not self.api_key:
            print("Warning: No OpenWeather API key provided. Using dummy data.")
            print("To get real weather data:")
            print("1. Sign up for free at: https://openweathermap.org/api")
            print("2. Get your API key from the dashboard")
            print("3. Set environment variable: export OPENWEATHER_API_KEY=your_key_here")
            print("4. Or use command line: --api-key your_key_here")
        else:
            print(f"Weather API initialized for location: {location}")
            # Test the API key immediately
            print("Testing API key...")
            test_data = self.fetch_weather_data()
            if test_data and 'temperature' in test_data and self.api_key:
                print(f"✓ API key valid! Current conditions: {test_data['temperature']:.1f}°C, {test_data['humidity']:.0f}% humidity")
            elif not self.api_key:
                print("✗ API key test failed - falling back to dummy data")
    
    def fetch_weather_data(self):
        """Fetch weather data with caching to avoid API rate limits (max once per 10 minutes)"""
        current_time = time.time()
        
        # Return cached data if still fresh (within 10 minutes)
        if (self.cached_data and 
            current_time - self.last_fetch_time < self.cache_duration):
            return self.cached_data
        
        if not self.api_key:
            # Return dummy data if no API key
            return {
                'temperature': 20.0 + random.uniform(-5, 10),
                'humidity': 50.0 + random.uniform(-20, 30),
                'pressure': 1013.25 + random.uniform(-50, 50),
                'light': random.randint(10000, 65000)
            }
        
        try:
            # OpenWeatherMap API URL - support multiple formats
            if ',' in self.location and len(self.location.split(',')) == 2:
                # Check if it's lat,lon coordinates
                try:
                    lat, lon = self.location.split(',')
                    float(lat)  # Test if it's numeric
                    float(lon)
                    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={self.api_key}&units=metric"
                except ValueError:
                    # It's city,country format
                    url = f"https://api.openweathermap.org/data/2.5/weather?q={self.location}&appid={self.api_key}&units=metric"
            elif self.location.isdigit():
                # City ID format
                url = f"https://api.openweathermap.org/data/2.5/weather?id={self.location}&appid={self.api_key}&units=metric"
            else:
                # City name or other query format
                url = f"https://api.openweathermap.org/data/2.5/weather?q={self.location}&appid={self.api_key}&units=metric"
            
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode())
            
            # Extract relevant data
            weather_data = {
                'temperature': data['main']['temp'],
                'humidity': data['main']['humidity'],
                'pressure': data['main']['pressure'],
                'light': self._calculate_light_from_weather(data)
            }
            
            # Cache the data
            self.cached_data = weather_data
            self.last_fetch_time = current_time
            
            return weather_data
            
        except urllib.error.HTTPError as e:
            if e.code == 401:
                print(f"Weather API Error: Invalid or missing API key (HTTP 401)")
                print("To get real weather data:")
                print("1. Sign up for free at: https://openweathermap.org/api")
                print("2. Get your API key from the dashboard")
                print("3. Use: export OPENWEATHER_API_KEY=your_key_here")
                print("4. Or use: --api-key your_key_here")
                print("Using dummy data for now...")
                # Disable further API calls by clearing the key
                self.api_key = None
            else:
                print(f"Weather API Error: HTTP {e.code} - {e.reason}")
            
            # Return last cached data or dummy data
            return self.cached_data or {
                'temperature': 20.0 + random.uniform(-5, 10),
                'humidity': 50.0 + random.uniform(-20, 30),
                'pressure': 1013.25 + random.uniform(-50, 50),
                'light': random.randint(10000, 65000)
            }
        except urllib.error.URLError as e:
            print(f"Network error fetching weather data: {e}")
            # Return last cached data or dummy data
            return self.cached_data or {
                'temperature': 20.0 + random.uniform(-5, 10),
                'humidity': 50.0 + random.uniform(-20, 30),
                'pressure': 1013.25 + random.uniform(-50, 50),
                'light': random.randint(10000, 65000)
            }
        except (KeyError, json.JSONDecodeError) as e:
            print(f"Error parsing weather data: {e}")
            return self.cached_data or {
                'temperature': 20.0,
                'humidity': 50.0,
                'pressure': 1013.25,
                'light': 30000
            }
    
    def _calculate_light_from_weather(self, weather_data):
        """Estimate light levels based on weather conditions and time"""
        try:
            # Get current conditions
            weather_condition = weather_data['weather'][0]['main'].lower()
            clouds = weather_data.get('clouds', {}).get('all', 0)  # Cloud coverage %
            
            # Base light level (assuming daylight, will be adjusted)
            base_light = 50000
            
            # Adjust for weather conditions
            if 'clear' in weather_condition:
                light_factor = 1.0
            elif 'cloud' in weather_condition:
                light_factor = 1.0 - (clouds / 100) * 0.7  # Reduce light by cloud coverage
            elif any(cond in weather_condition for cond in ['rain', 'drizzle']):
                light_factor = 0.3
            elif 'thunderstorm' in weather_condition:
                light_factor = 0.2
            elif any(cond in weather_condition for cond in ['snow', 'mist', 'fog']):
                light_factor = 0.4
            else:
                light_factor = 0.6
            
            # Simple time-based adjustment (this is very approximate)
            import datetime
            current_hour = datetime.datetime.now().hour
            if 6 <= current_hour <= 18:  # Rough daylight hours
                time_factor = 1.0
            elif current_hour in [5, 6, 18, 19]:  # Dawn/dusk
                time_factor = 0.3
            else:  # Night
                time_factor = 0.05
            
            calculated_light = int(base_light * light_factor * time_factor)
            return max(calculated_light, 100)  # Minimum light level
            
        except (KeyError, TypeError):
            # Fallback to random value if calculation fails
            return random.randint(10000, 50000)

class hwsensor():
    '''
    the hardware sensor
    '''
    def __init__(self):
        pass
    
    @property
    def getTemperature(self):
        if weather_fetcher:
            return weather_fetcher.fetch_weather_data()['temperature']
        return 20.0 + random.uniform(-5, 10)

    @property
    def getHumidity(self):
        if weather_fetcher:
            return weather_fetcher.fetch_weather_data()['humidity']
        return 50.0 + random.uniform(-20, 30)

    @property
    def getPressure(self):
        if weather_fetcher:
            return weather_fetcher.fetch_weather_data()['pressure']
        return 1013.25 + random.uniform(-50, 50)

    @property
    def getLight(self):
        if weather_fetcher:
            return weather_fetcher.fetch_weather_data()['light']
        return random.randint(10000, 65000)
        

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


class SensorHTTPHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for sensor endpoints"""
    
    def log_message(self, format, *args):
        """Override to reduce logging noise"""
        pass
    
    def do_GET(self):
        """Handle GET requests"""
        if self.path == '/id':
            self.send_json_response({"id": MAC_ADDRESS})
        elif self.path == '/':
            self.send_sensor_data()
        else:
            self.send_error(404, "Not Found")
    
    def do_POST(self):
        """Handle POST requests"""
        if self.path == '/set':
            self.handle_settings_update()
        else:
            self.send_error(404, "Not Found")
    
    def send_json_response(self, data):
        """Send JSON response"""
        response = json.dumps(data)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response)))
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))
    
    def send_sensor_data(self):
        """Send current sensor data"""
        host_header = self.headers.get('host', f"{socket.gethostname()}:{PORT}")
        
        data = {
            "id": MAC_ADDRESS,
            "ip": host_header,
            "name": config['sensor_name'], 
            "location": config['location'],
            "temperature": hws.getTemperature,
            "humidity": hws.getHumidity,
            "pressure": hws.getPressure,
            "light": hws.getLight
        }
        self.send_json_response(data)
    
    def handle_settings_update(self):
        """Handle settings update via POST"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            
            # Parse "location=place&sensor_name=name" format
            for entry in post_data.split("&"):
                if '=' in entry:
                    key, value = entry.split("=", 1)
                    config[key] = value
            
            print("Updated config:", config)
            
            # Save to config file (using the global config file path)
            with open(DEFAULT_JSONFILE, 'w') as f:
                json.dump(config, f, indent=2)
            
            self.send_json_response({"DATA": "OK"})
            
        except Exception as e:
            print(f"Error updating settings: {e}")
            self.send_json_response({"DATA": "FAIL"})


def startSensor():
    '''
    Start the virtual sensor with HTTP server
    '''
    # Initialize the virtual sensor (for zeroconf registration)
    sensor = virtualSensor()
    
    # Start HTTP server
    server = HTTPServer(('0.0.0.0', PORT), SensorHTTPHandler)
    print(f"Virtual sensor HTTP server starting on port {PORT}")
    print(f"Sensor endpoints:")
    print(f"  GET  http://localhost:{PORT}/     - Sensor data")
    print(f"  GET  http://localhost:{PORT}/id   - Sensor ID")
    print(f"  POST http://localhost:{PORT}/set  - Update settings")
    print("Press Ctrl+C to stop")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()
        server.server_close()


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
    parser.add_option("-n", "--name", dest="sensor_name", help="Sensor name (overrides config file)")
    parser.add_option("-L", "--location", dest="location", help="Sensor location (overrides config file)")
    parser.add_option("-c", "--conf", dest="config_file", default=DEFAULT_JSONFILE, help="Path to configuration file (default: config_sensor.json)")
    parser.add_option("-z", "--zipcode", dest="weather_location", help="Location for real weather data (e.g., 'London,GB', '51.5074,-0.1278', '2643743')")
    parser.add_option("-k", "--api-key", dest="api_key", help="OpenWeatherMap API key (or use OPENWEATHER_API_KEY env var)")
    parser.add_option("-s", "--save", dest="save_config", default=False, help="Save current arguments to config file", action="store_true")

    (options, args) = parser.parse_args()
    option_dict = vars(options)

    # Load configuration file
    try:
        config = json.load(open(option_dict["config_file"]))
    except:
        config = { 'sensor_name' : 'virtual-test-sensor',
                   'location' : 'Home_Office' }

    # Override config with command line arguments if provided
    if option_dict["sensor_name"]:
        config['sensor_name'] = option_dict["sensor_name"]
    if option_dict["location"]:
        config['location'] = option_dict["location"]
    if option_dict["weather_location"]:
        config['weather_location'] = option_dict["weather_location"]
    if option_dict["api_key"]:
        config['api_key'] = option_dict["api_key"]

    # Save configuration if --save flag is used
    if option_dict["save_config"]:
        try:
            with open(option_dict["config_file"], 'w') as f:
                json.dump(config, f, indent=2)
            print(f"Configuration saved to: {option_dict['config_file']}")
            print(f"Saved settings: {json.dumps(config, indent=2)}")
        except Exception as e:
            print(f"Error saving configuration: {e}")

    # Initialize weather fetcher if location provided
    if option_dict["weather_location"] or config.get('weather_location'):
        weather_location = option_dict["weather_location"] or config.get('weather_location')
        api_key = option_dict["api_key"] or config.get('api_key')
        
        weather_fetcher = WeatherDataFetcher(
            location=weather_location,
            api_key=api_key
        )
        print(f"Real weather data enabled for: {weather_location}")
        if not api_key and not os.environ.get('OPENWEATHER_API_KEY'):
            print("Note: No API key provided, using randomized dummy data")

    if option_dict["listener"]:
        startListener()
    else:
        startSensor()


