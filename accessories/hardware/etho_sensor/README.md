# Environmental Sensor Station for Ethoscope Platform

## Overview

This project is an mDNS-based environmental sensor platform designed to work with ESP8266 and ESP32 microcontrollers. It measures environmental parameters such as temperature, humidity, pressure, and light intensity (when enabled) using the BME280 and BH1750FVI sensors. The data is served via a local web server, allowing the user to access sensor data in JSON format or an HTML configuration page. Additionally, users can update the device configuration remotely via an HTTP POST request.

## Features

- **Sensor Integration**: Measures temperature, humidity, pressure, and optionally light intensity.
- **Web Interface**:
  - JSON API for raw data access.
  - HTML interface for easy configuration and visualization.
- **Device Configuration**:
  - Change device name and location settings.
  - WiFi configuration using stored SSID and password.
- **MDNS Support**: Access device using `http://etho_sensor_000.local`.
- **Error Handling**: Alerts and system resets on sensor or WiFi failures.
- **Platform Compatibility**: Compatible with ESP8266 and ESP32 platforms.

## Hardware Requirements

- ESP8266 (e.g., WeMos D1 Mini) or ESP32 board.
- BME280 sensor for temperature, humidity, and pressure measurements.
- BH1750FVI sensor for light intensity measurement (optional).
- Connection Wires.

## Wiring

### ESP32 Wiring
- **VCC**: Connect to 3.3V
- **GND**: Connect to GND
- **SDA**: Connect to GPIO 21
- **SCL**: Connect to GPIO 22

### ESP8266 Wiring
- **VCC**: Connect to 3.3V
- **GND**: Connect to GND
- **SDA**: Connect to D2
- **SCL**: Connect to D1

## Software Requirements

- Arduino IDE with ESP8266 or ESP32 board installed.
- Required Libraries:
  - `Adafruit BME280 Library`
  - `BH1750 Library`
  - `ESP8266WiFi` or `WiFi` (for ESP32)
  - `ESP8266mDNS` or `ESPmDNS` (for ESP32)
  - `Ticker` (for ESP8266)

## Configuration

### WiFi Settings

Update your WiFi SSID and Password in `etho_sensor.ino`:

```cpp
configuration cfg = {"", "etho_sensor_000", "YOUR_WIFI_SSID", "YOUR_WIFI_PASSWORD"};
```

### Flash the Sketch

- Connect your ESP8266/ESP32 board.
- Choose the correct board and port in Arduino IDE.
- Flash the `etho_sensor.ino` sketch to the board.

### Host Configuration (For mDNS Support)

- **Linux**: Install Avahi.
- **Windows**: Install Bonjour.
- **Mac OSX**: mDNS is built-in.

## Usage

1. **Access Sensor Data**: 
   - Open a web browser.
   - Navigate to `http://etho_sensor_000.local` for JSON response.
   - Visit `http://etho_sensor_000.local/web` for the HTML interface.

2. **Update Configuration**: 
   - Use the HTML interface or send a POST request to update device configuration:

   ```sh
   echo '{"name": "etho_sensor-001", "location": "Incubator-18C"}' | curl -d @- http://etho_sensor_000.local/set
   ```

## Debugging

- Use `DEBUG_SERIAL` flag defined in `config.h` for serial debugging.
- Monitor sensor and network status via Serial Monitor at 115200 baud rate.

## Contribution

Feel free to fork the repository and submit pull requests. For major changes, please open an issue first to discuss the intended changes.

## License

This project is licensed under the MIT License. See the LICENSE file for more details.
