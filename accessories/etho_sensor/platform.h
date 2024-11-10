// platform.h
#ifndef PLATFORM_H
#define PLATFORM_H

// Common includes
#include <Wire.h>
#include <SPI.h>
#include "config.h"

// Platform-specific includes
#if defined(ESP8266)
    #include <ESP8266WiFi.h>
    #include <ESP8266WebServer.h>
    #include <ESP8266mDNS.h>
    #include <Ticker.h>
    typedef ESP8266WebServer WebServer;
    #define PLATFORM_ATTR ICACHE_FLASH_ATTR

#elif defined(ESP32)
    #include <WiFi.h>
    #include <WebServer.h>
    #include <ESPmDNS.h>
    #include "esp_task_wdt.h"
    typedef WebServer WebServer;
    #define PLATFORM_ATTR 
#else
    #error "This sketch is only for ESP8266 or ESP32"
#endif

// Common pin definitions
#if defined(ESP8266)
    #define SDA_PIN D2
    #define SCL_PIN D1

#elif defined(ESP32)
    #define SDA_PIN 21
    #define SCL_PIN 22
#endif

// PlatformWatchdog class declaration
class PlatformWatchdog {
public:
    static void begin(int timeoutSeconds);
    static void reset();

private:
    #if defined(ESP8266)
        static Ticker watchdogTicker;
    #endif
};

// Function declarations
void updateMDNS();
void setupPowerManagement();
String platformGetChipId();
void softReset();
void setupWatchdog();
void resetWatchdog();
const char* getPlatformName();

#endif // PLATFORM_H