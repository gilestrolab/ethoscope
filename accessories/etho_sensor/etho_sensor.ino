/*
  ESP8266/ESP32 mDNS based environmental sensor for the ethoscope platform

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

  - Point your browser to http://etho_sensor_000.local, you should see a JSON response.
  - http://etho_sensor_000.local/web will give you a html page

  - To memorize multiple SSIDs options instead of only one
 https://tttapa.github.io/ESP8266/Chap10%20-%20Simple%20Web%20Server.html


 	To rename from commandline use curl as below:
    echo '{"name": "etho_sensor-001", "location": "Incubator-18C"}' | curl -d @- http://etho_sensor_000.local/set

  More easily, point your browser to http://etho_sensor_000.local/web

*/
#include "config.h"
#include "platform.h"
#include "network.h"
#include "storage.h"
#include "sensors.h"

#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <BH1750FVI.h>

// Global variable definitions (not declarations)
environment env;
configuration cfg;

WebServer server(80);  // Uses the typedef from platform.h

Adafruit_BME280 bme;
#if defined(USELIGHT)
    BH1750FVI LightSensor(BH1750FVI::k_DevModeContLowRes);
#endif

void PLATFORM_ATTR handleSystemTasks();
bool PLATFORM_ATTR checkSystem();

void setup() {
    Serial.begin(115200);
    DEBUG_PRINTLN("###########");
    DEBUG_PRINTLN("Starting up.");

    setupWatchdog();
    setupPowerManagement();

    if (!Storage::begin()) {
        DEBUG_PRINT("Storage initialization failed: ");
        DEBUG_PRINTLN(Storage::getErrorString(Storage::getLastError()));
        return;
    }

    // Define default configuration
    configuration defaultCfg = {DEFAULT_LOCATION, DEFAULT_NAME, WIFI_SSID, WIFI_PASSWORD};

    if (!Storage::loadConfig(cfg)) {
        StorageError error = Storage::getLastError();
        if (error == StorageError::VALIDATION_FAILED) {
            DEBUG_PRINTLN("No valid configuration found in storage, using defaults.");
            cfg = defaultCfg; // Assign the default configuration
            DEBUG_PRINTLN("Saving default configuration to storage...");
            if (!Storage::saveConfig(cfg)) {
                DEBUG_PRINT("Failed to save default configuration: ");
                DEBUG_PRINTLN(Storage::getErrorString(Storage::getLastError()));
            } else {
                DEBUG_PRINTLN("Default configuration saved successfully.");
            }
        } else {
            DEBUG_PRINT("Failed to load configuration from storage: ");
            DEBUG_PRINTLN(Storage::getErrorString(error));
            DEBUG_PRINTLN("Using default configuration instead.");
            cfg = defaultCfg; // Assign the default configuration
        }
    } else {
        DEBUG_PRINTLN("Configuration loaded from storage:");
        DEBUG_PRINT("Name: ");
        DEBUG_PRINTLN(cfg.name);
        DEBUG_PRINT("Location: ");
        DEBUG_PRINTLN(cfg.location);
        DEBUG_PRINT("WiFi SSID: ");
        DEBUG_PRINTLN(cfg.wifi_ssid);
        DEBUG_PRINT("WiFi Password: ");
        DEBUG_PRINTLN(cfg.wifi_pwd);
    }

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
    server.handleClient();  // Handle web server requests
    updateMDNS();          // Handle mDNS updates
    yield();               // Allow system tasks to run
    handleSystemTasks();   // Handle our system tasks
}

void PLATFORM_ATTR handleSystemTasks() {
    static uint32_t lastCheck = 0;
    static const uint32_t SYSTEM_CHECK_INTERVAL = 1000;
    static uint8_t errorCount = 0;
    static const uint8_t ERROR_THRESHOLD = 5;

    const uint32_t currentMillis = millis();

    if ((uint32_t)(currentMillis - lastCheck) >= SYSTEM_CHECK_INTERVAL) {
        lastCheck = currentMillis;

        if (!checkSystem()) {
            errorCount++;
            if (errorCount >= ERROR_THRESHOLD) {
                DEBUG_PRINTLN("System check failed too many times, restarting...");
                #if defined(ESP8266)
                    ESP.reset();
                #elif defined(ESP32)
                    ESP.restart();
                #endif
            }
        } else {
            errorCount = 0;
        }
    }
}

bool PLATFORM_ATTR checkSystem() {
    bool status = true;

    if (WiFi.status() != WL_CONNECTED) {
        DEBUG_PRINTLN("WiFi connection lost. Reconnecting...");
        reconnectWiFi();
        status = false;
    }

    if (!readSensorData()) {
        DEBUG_PRINTLN("Sensor read failed");
        status = false;
    }

    return status;
}
