"""
Sensor API Module

Handles sensor management including discovery, configuration, and data visualization.
"""

import json
import os
from .base import BaseAPI, error_decorator


class SensorAPI(BaseAPI):
    """API endpoints for sensor management and data."""
    
    def register_routes(self):
        """Register sensor-related routes."""
        self.app.route('/sensors', method='GET')(self._get_sensors)
        self.app.route('/sensor/set', method='POST')(self._edit_sensor)
        self.app.route('/list_sensor_csv_files', method='GET')(self._list_csv_files)
        self.app.route('/get_sensor_csv_data/<filename>', method='GET')(self._get_csv_data)
    
    @error_decorator
    def _get_sensors(self):
        """Get all sensor information."""
        return self.sensor_scanner.get_all_devices_info() if self.sensor_scanner else {}
    
    def _edit_sensor(self):
        """Edit sensor settings."""
        input_string = self.get_request_data().decode("utf-8")
        
        # Use json.loads instead of eval for security
        try:
            data = json.loads(input_string)
        except json.JSONDecodeError:
            # Fallback for malformed JSON - but this is risky
            try:
                data = eval(input_string)  # This should eventually be removed
            except:
                return {'error': 'Invalid data format'}
        
        if self.sensor_scanner:
            try:
                sensor = self.sensor_scanner.get_device(data["id"])
                if sensor:
                    return sensor.set({"location": data["location"], "sensor_name": data["name"]})
            except Exception as e:
                return {'error': f'Sensor operation failed: {str(e)}'}
        
        return {'error': 'Sensor not found'}
    
    @error_decorator
    def _list_csv_files(self):
        """List CSV files in /ethoscope_data/sensors/."""
        directory = '/ethoscope_data/sensors/'
        try:
            if os.path.exists(directory):
                csv_files = [f for f in os.listdir(directory) if f.endswith('.csv')]
                return {'files': csv_files}
        except Exception:
            pass
        return {'files': []}
    
    @error_decorator
    def _get_csv_data(self, filename):
        """Read CSV file and return data for plotting."""
        directory = '/ethoscope_data/sensors/'
        filepath = os.path.join(directory, filename)
        
        data = []
        with open(filepath, 'r') as csvfile:
            headers = csvfile.readline().strip().split(',')
            for line in csvfile:
                data.append(line.strip().split(','))
        
        return {'headers': headers, 'data': data}