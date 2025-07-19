"""
Mock hardware implementations for testing.

This module provides mock implementations of hardware components
like cameras, stimulators, and sensors for use in tests.
"""

import numpy as np
from unittest.mock import Mock, MagicMock
from typing import List, Dict, Any, Optional, Tuple
import time
import threading


class MockCamera:
    """Mock implementation of camera interface."""
    
    def __init__(self, resolution: Tuple[int, int] = (640, 480), framerate: int = 30):
        """Initialize mock camera."""
        self.resolution = resolution
        self.framerate = framerate
        self.is_recording = False
        self.is_previewing = False
        self.rotation = 0
        self.brightness = 50
        self.contrast = 50
        self.saturation = 50
        self.sharpness = 50
        self.iso = 100
        self.exposure_mode = "auto"
        self.awb_mode = "auto"
        self.frame_count = 0
        self.last_frame = None
        self._recording_thread = None
        
    def start_preview(self):
        """Start camera preview."""
        self.is_previewing = True
        
    def stop_preview(self):
        """Stop camera preview."""
        self.is_previewing = False
        
    def capture(self, output, format="jpeg", **kwargs):
        """Capture a single frame."""
        if format == "jpeg":
            # Mock JPEG capture
            return self._generate_test_frame()
        elif format == "bgr":
            # Mock BGR array capture
            return self._generate_test_frame()
        else:
            raise ValueError(f"Unsupported format: {format}")
            
    def capture_continuous(self, output, format="jpeg", **kwargs):
        """Capture continuous frames."""
        while self.is_recording:
            yield self._generate_test_frame()
            time.sleep(1.0 / self.framerate)
            
    def start_recording(self, output, format="h264", **kwargs):
        """Start video recording."""
        self.is_recording = True
        self._recording_thread = threading.Thread(target=self._record_frames)
        self._recording_thread.start()
        
    def stop_recording(self):
        """Stop video recording."""
        self.is_recording = False
        if self._recording_thread:
            self._recording_thread.join()
            
    def _record_frames(self):
        """Record frames in background thread."""
        while self.is_recording:
            self.frame_count += 1
            time.sleep(1.0 / self.framerate)
            
    def _generate_test_frame(self) -> np.ndarray:
        """Generate a test frame with patterns."""
        height, width = self.resolution[1], self.resolution[0]
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        
        # Add test patterns
        # Background gradient
        for i in range(height):
            frame[i, :] = int(255 * i / height)
            
        # Add some shapes for tracking
        # White squares as targets
        for i in range(5):
            x = 50 + i * 120
            y = 50 + i * 80
            if x + 50 < width and y + 50 < height:
                frame[y:y+50, x:x+50] = [255, 255, 255]
                
        # Add some noise
        noise = np.random.randint(0, 50, (height, width, 3))
        frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        
        self.last_frame = frame
        return frame
        
    def close(self):
        """Close camera."""
        self.stop_recording()
        self.stop_preview()
        
    def __enter__(self):
        """Context manager entry."""
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


class MockStimulator:
    """Mock implementation of stimulator interface."""
    
    def __init__(self, name: str = "TestStimulator", gpio_pin: int = 18):
        """Initialize mock stimulator."""
        self.name = name
        self.gpio_pin = gpio_pin
        self.is_active = False
        self.parameters = {}
        self.activation_count = 0
        self.last_activation = None
        
    def activate(self, duration: float = 1.0, **kwargs):
        """Activate stimulator."""
        self.is_active = True
        self.activation_count += 1
        self.last_activation = time.time()
        self.parameters.update(kwargs)
        
        # Simulate activation duration
        if duration > 0:
            time.sleep(min(duration, 0.1))  # Cap at 0.1s for tests
            self.is_active = False
            
    def deactivate(self):
        """Deactivate stimulator."""
        self.is_active = False
        
    def set_parameters(self, **kwargs):
        """Set stimulator parameters."""
        self.parameters.update(kwargs)
        
    def get_parameters(self) -> Dict[str, Any]:
        """Get stimulator parameters."""
        return self.parameters.copy()
        
    def get_status(self) -> Dict[str, Any]:
        """Get stimulator status."""
        return {
            "name": self.name,
            "gpio_pin": self.gpio_pin,
            "is_active": self.is_active,
            "activation_count": self.activation_count,
            "last_activation": self.last_activation,
            "parameters": self.parameters
        }


class MockSensor:
    """Mock implementation of sensor interface."""
    
    def __init__(self, name: str = "TestSensor", gpio_pin: int = 4):
        """Initialize mock sensor."""
        self.name = name
        self.gpio_pin = gpio_pin
        self.is_active = False
        self.readings = []
        self.last_reading = None
        
    def read(self) -> float:
        """Read sensor value."""
        # Generate mock reading
        reading = np.random.normal(25.0, 2.0)  # Temperature-like reading
        self.readings.append(reading)
        self.last_reading = reading
        return reading
        
    def start_continuous_reading(self, interval: float = 1.0):
        """Start continuous reading."""
        self.is_active = True
        
    def stop_continuous_reading(self):
        """Stop continuous reading."""
        self.is_active = False
        
    def get_readings(self) -> List[float]:
        """Get all readings."""
        return self.readings.copy()
        
    def clear_readings(self):
        """Clear reading history."""
        self.readings = []
        
    def get_status(self) -> Dict[str, Any]:
        """Get sensor status."""
        return {
            "name": self.name,
            "gpio_pin": self.gpio_pin,
            "is_active": self.is_active,
            "reading_count": len(self.readings),
            "last_reading": self.last_reading
        }


class MockGPIO:
    """Mock implementation of GPIO interface."""
    
    def __init__(self):
        """Initialize mock GPIO."""
        self.pins = {}
        self.mode = "BCM"
        
    def setmode(self, mode: str):
        """Set GPIO mode."""
        self.mode = mode
        
    def setup(self, pin: int, direction: str, pull_up_down: str = None):
        """Setup GPIO pin."""
        self.pins[pin] = {
            "direction": direction,
            "pull_up_down": pull_up_down,
            "value": 0
        }
        
    def output(self, pin: int, value: int):
        """Set GPIO output."""
        if pin in self.pins:
            self.pins[pin]["value"] = value
            
    def input(self, pin: int) -> int:
        """Read GPIO input."""
        if pin in self.pins:
            return self.pins[pin]["value"]
        return 0
        
    def cleanup(self):
        """Cleanup GPIO pins."""
        self.pins = {}
        
    def get_pin_status(self, pin: int) -> Dict[str, Any]:
        """Get pin status."""
        return self.pins.get(pin, {})


class MockSerialPort:
    """Mock implementation of serial port interface."""
    
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 9600):
        """Initialize mock serial port."""
        self.port = port
        self.baudrate = baudrate
        self.is_open = False
        self.timeout = 1.0
        self.write_buffer = []
        self.read_buffer = []
        
    def open(self):
        """Open serial port."""
        self.is_open = True
        
    def close(self):
        """Close serial port."""
        self.is_open = False
        
    def write(self, data: bytes) -> int:
        """Write data to serial port."""
        if not self.is_open:
            raise RuntimeError("Serial port is not open")
        self.write_buffer.append(data)
        return len(data)
        
    def read(self, size: int = 1) -> bytes:
        """Read data from serial port."""
        if not self.is_open:
            raise RuntimeError("Serial port is not open")
        if self.read_buffer:
            return self.read_buffer.pop(0)
        return b"OK"  # Default response
        
    def readline(self) -> bytes:
        """Read a line from serial port."""
        return self.read(1024)
        
    def flush(self):
        """Flush serial port buffers."""
        self.write_buffer = []
        self.read_buffer = []
        
    def add_response(self, response: bytes):
        """Add a response to the read buffer."""
        self.read_buffer.append(response)
        
    def get_written_data(self) -> List[bytes]:
        """Get all written data."""
        return self.write_buffer.copy()
        
    def __enter__(self):
        """Context manager entry."""
        self.open()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


def create_mock_hardware_setup() -> Dict[str, Any]:
    """Create a complete mock hardware setup."""
    return {
        "camera": MockCamera(),
        "stimulators": [
            MockStimulator("OptomotorStimulator", 18),
            MockStimulator("SleepDeprivationStimulator", 19)
        ],
        "sensors": [
            MockSensor("TemperatureSensor", 4),
            MockSensor("HumiditySensor", 5)
        ],
        "gpio": MockGPIO(),
        "serial": MockSerialPort()
    }