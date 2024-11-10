// platform.cpp
#include "platform.h"

#if defined(ESP8266)
    Ticker PlatformWatchdog::watchdogTicker;
#endif

// Function to store or retrieve platform name
const char* getPlatformName() {
    #if defined(ESP8266)
        #if defined(ARDUINO_ESP8266_WEMOS_D1R1)
            return "WeMos D1 R1 (ESP8266)";
        #elif defined(ARDUINO_ESP8266_WEMOS_D1MINI)
            return "WeMos D1 Mini (ESP8266)";
        #elif defined(ARDUINO_ESP8266_NODEMCU)
            return "NodeMCU (ESP8266)";
        #else
            return "ESP8266";
        #endif
    #elif defined(ESP32)
        #if defined(ARDUINO_ESP32_DEV)
            return "ESP32 Dev Module";
        #elif defined(ARDUINO_ESP32_WROOM)
            return "ESP32-WROOM";
        #elif defined(ARDUINO_ESP32S2_DEV)
            return "ESP32-S2";
        #elif defined(ARDUINO_ESP32C3_DEV)
            return "ESP32-C3";
        #else
            return "ESP32";
        #endif
    #endif
}

// Watchdog functions
void PlatformWatchdog::begin(int timeoutSeconds) {
    #if defined(ESP8266)
        watchdogTicker.attach(timeoutSeconds, []() {
            ESP.restart();
        });
    #elif defined(ESP32)
        esp_task_wdt_config_t config = {
            .timeout_ms = timeoutSeconds * 1000,
            .idle_core_mask = (1 << portNUM_PROCESSORS) - 1,
            .trigger_panic = true
        };
        esp_task_wdt_init(&config);
        esp_task_wdt_add(NULL);
    #endif
}

void PlatformWatchdog::reset() {
    #if defined(ESP8266)
        watchdogTicker.detach();
        watchdogTicker.attach(WATCHDOG_TIMEOUT, []() {
            ESP.restart();
        });
    #elif defined(ESP32)
        esp_task_wdt_reset();
    #endif
}

// Other functions
void updateMDNS() {
    #if defined(ESP8266)
        MDNS.update();
    #endif
    // No explicit update required for ESP32
}

void setupPowerManagement() {
    #if defined(ESP8266)
        system_update_cpu_freq(80);
        WiFi.setSleepMode(WIFI_NONE_SLEEP);
    #elif defined(ESP32)
        setCpuFrequencyMhz(80);
        WiFi.setSleep(false);
    #endif
}

String platformGetChipId() {
    #if defined(ESP8266)
        return String(ESP.getChipId(), HEX);
    #elif defined(ESP32)
        uint64_t chipId = ESP.getEfuseMac();
        return String((uint32_t)(chipId >> 32), HEX) + String((uint32_t)chipId, HEX);
    #endif
}

void PLATFORM_ATTR softReset() {
    // Disconnect WiFi
    WiFi.disconnect(true);
    delay(1000); // Allow some time for disconnection

    // Restart the device
    #if defined(ESP8266) 
        ESP.restart();
    #elif defined(ESP32)
        esp_restart();
    #endif
}

// Watchdog setup
void setupWatchdog() {
    PlatformWatchdog::begin(WATCHDOG_TIMEOUT);
}

void resetWatchdog() {
    PlatformWatchdog::reset();
}