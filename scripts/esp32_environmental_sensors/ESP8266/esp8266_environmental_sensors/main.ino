/*
  ESP8266 mDNS based environmental sensor

  This is an example of an HTTP server that is accessible
  via mDNS responder.

  Soldier together the two sensors boards (BME280 and BH1750), using the same header
  then connect to the ESP32 
  VCC -> 3.3V
  Gnd -> Gnd
  SDA -> D21
  SCL -> D22

  or ESP8266 D1 mini Pro (use WEMOS D1 R1)
  VCC -> 3.3V
  Gnd -> Gnd
  SDA -> D2
  SCL -> D1

  Instructions:
  - Update WiFi SSID and password as necessary.
  - Flash the sketch to the board
  - Install host software:
    - For Linux, install Avahi (http://avahi.org/).
    - For Windows, install Bonjour (http://www.apple.com/support/bonjour/).
    - For Mac OSX and iOS support is built in through Bonjour already.
  - Point your browser to http://etho_sensor.local, you should see a response.

  - To memorize multiple SSIDs options instead of only one
 https://tttapa.github.io/ESP8266/Chap10%20-%20Simple%20Web%20Server.html

v2.0
*/
#include <ESP8266WiFi.h>
#include <ESP8266mDNS.h>
#include <ESPAsyncWebServer.h>
#include <EEPROM_Rotate.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <BH1750FVI.h>
#include <Ticker.h>
#include "config.h"
#include "sensors.h"
#include "network.h"

EEPROM_Rotate EEPROMr;
AsyncWebServer server(80);
Ticker watchdogTicker;

environment env;
configuration cfg = {"", "etho_sensor", "ETHOSCOPE_WIFI", "ETHOSCOPE_1234"};

void setup() {
    Serial.begin(115200);
    DEBUG_PRINTLN("Starting up...");

    setupWatchdog();
    setupPowerManagement();
    
    if (!initializeSensors()) {
        DEBUG_PRINTLN("Sensor initialization failed. Restarting...");
        softReset();
    }

    if (!setupWiFi()) {
        DEBUG_PRINTLN("WiFi setup failed. Restarting...");
        softReset();
    }

    setupWebServer();
    DEBUG_PRINTLN("Setup complete");
}

void loop() {
    resetWatchdog();
    
    static unsigned long lastCheck = 0;
    
    if (millis() - lastCheck >= CHECK_INTERVAL) {
        lastCheck = millis();
        
        if (WiFi.status() != WL_CONNECTED) {
            DEBUG_PRINTLN("WiFi connection lost. Reconnecting...");
            reconnectWiFi();
        }
        
        if (!readSensorData()) {
            DEBUG_PRINTLN("Sensor read failed");
        }
    }
    
    MDNS.update();
    yield();
}
