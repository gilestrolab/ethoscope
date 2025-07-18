import os
import json
from threading import RLock
from typing import Dict, Any

from ethoscope_node.utils.device_scanner import BaseDevice, DeviceScanner



class Sensor(BaseDevice):
    """Enhanced sensor device class with improved CSV handling."""
    
    SENSOR_FIELDS = ["Time", "Temperature", "Humidity", "Pressure", "Light"]
    
    def __init__(self, ip: str, port: int = 80, refresh_period: float = 5, 
                 results_dir: str = "", save_to_csv: bool = True):
                     
        self.save_to_csv = save_to_csv
        self._csv_lock = RLock()
        
        # Ensure CSV directory exists before calling parent
        if save_to_csv:
            os.makedirs(results_dir, exist_ok=True)
            
        super().__init__(ip, port, refresh_period, results_dir)
    
    def _setup_urls(self):
        """Setup sensor-specific URLs."""
        self._data_url = f"http://{self._ip}:{self._port}/"
        self._id_url = f"http://{self._ip}:{self._port}/id" 
        self._post_url = f"http://{self._ip}:{self._port}/set"
    
    def set(self, post_data: Dict[str, Any], use_json: bool = False) -> Any:
        """
        Set remote sensor variables.
        
        Args:
            post_data: Dictionary of key-value pairs to set
            use_json: Whether to send data as JSON
            
        Returns:
            Response from sensor
        """
        try:
            if use_json:
                data = json.dumps(post_data).encode('utf-8')
                return self._get_json(self._post_url, post_data=data)
            else:
                data = urllib.parse.urlencode(post_data).encode('utf-8')
                req = urllib.request.Request(self._post_url, data=data)
                
                with urllib.request.urlopen(req, timeout=self._timeout) as response:
                    result = response.read()
                
                self._update_info()
                return result
                
        except Exception as e:
            self._logger.error(f"Error setting sensor variables: {e}")
            raise
    
    def _update_info(self):
        """Update sensor information and save to CSV if enabled."""
        try:
            self._update_id()
            
            # Get sensor data
            resp = self._get_json(self._data_url)
            
            with self._lock:
                self._info.update(resp)
                self._update_device_status("online", trigger_source="system")
                self._info['last_seen'] = time.time()
            
            # Save to CSV if enabled
            if self.save_to_csv:
                self._save_to_csv()
                
        except ScanException:
            self._reset_info()
        except Exception as e:
            self._logger.error(f"Error updating sensor info: {e}")
            self._reset_info()
    
    def _save_to_csv(self):
        """Save sensor data to CSV file with thread safety."""
        try:
            with self._csv_lock:
                # Extract sensor data
                sensor_data = self._extract_sensor_data()
                filename = self._get_csv_filename(sensor_data['name'])
                
                # Check if file exists
                file_exists = os.path.isfile(filename)
                
                with open(filename, mode='a', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    
                    # Write header if new file
                    if not file_exists:
                        self._write_csv_header(csvfile, sensor_data)
                        writer.writerow(self.SENSOR_FIELDS)
                    
                    # Write data row
                    current_time = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    writer.writerow([
                        current_time,
                        sensor_data.get('temperature', 'N/A'),
                        sensor_data.get('humidity', 'N/A'), 
                        sensor_data.get('pressure', 'N/A'),
                        sensor_data.get('light', 'N/A')
                    ])
                    
        except Exception as e:
            self._logger.error(f"Error saving to CSV: {e}")
    
    def _extract_sensor_data(self) -> Dict[str, Any]:
        """Extract sensor data from info dictionary."""
        with self._lock:
            return {
                'id': self._info.get('id', 'unknown_id'),
                'ip': self._info.get('ip', 'unknown_ip'),
                'name': self._info.get('name', 'unknown_sensor'),
                'location': self._info.get('location', 'unknown_location'),
                'temperature': self._info.get('temperature', 'N/A'),
                'humidity': self._info.get('humidity', 'N/A'),
                'pressure': self._info.get('pressure', 'N/A'),
                'light': self._info.get('light', 'N/A')
            }
    
    def _get_csv_filename(self, sensor_name: str) -> str:
        """Get CSV filename for sensor."""
        safe_name = "".join(c for c in sensor_name if c.isalnum() or c in '_-')
        return os.path.join(self.CSV_PATH, f"{safe_name}.csv")
    
    def _write_csv_header(self, csvfile, sensor_data: Dict[str, Any]):
        """Write CSV metadata header."""
        header = (
            f"# Sensor ID: {sensor_data['id']}\n"
            f"# IP: {sensor_data['ip']}\n"
            f"# Name: {sensor_data['name']}\n"
            f"# Location: {sensor_data['location']}\n"
        )
        csvfile.write(header)



class SensorScanner(DeviceScanner):
    """Sensor-specific scanner."""
    
    SERVICE_TYPE = "_sensor._tcp.local."
    DEVICE_TYPE = "sensor"
    
    def __init__(self, results_dir: str = "/ethoscope_data", device_refresh_period: float = 300, device_class=Sensor):
        super().__init__(device_refresh_period, device_class)
        self.results_dir = os.path.join(results_dir, "/sensors")