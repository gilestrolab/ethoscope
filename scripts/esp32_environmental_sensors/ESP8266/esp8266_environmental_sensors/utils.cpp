#include <ESP8266WiFi.h>
#include <Ticker.h>
#include "utils.h"
#include "config.h"

extern Ticker watchdogTicker;
extern EEPROM_Rotate EEPROMr;
extern configuration cfg;

void setupWatchdog() {
    watchdogTicker.attach(WATCHDOG_TIMEOUT, []() {
        ESP.restart();
    });
}

void resetWatchdog() {
    watchdogTicker.detach();
    watchdogTicker.attach(WATCHDOG_TIMEOUT, []() {
        ESP.restart();
    });
}

void setupPowerManagement() {
    system_update_cpu_freq(80);
    WiFi.setSleepMode(WIFI_NONE_SLEEP);
}

void softReset() {
    DEBUG_PRINTLN("Performing soft reset...");
    WiFi.disconnect(true);
    delay(1000);
    ESP.restart();
}

void saveConfiguration() {
    EEPROMr.write(EEPROM_START, 1);
    delay(250);
    EEPROMr.put(EEPROM_START+2, cfg);
    delay(250);

    if (!EEPROMr.commit()) {
        DEBUG_PRINTLN("Failed to commit EEPROM changes");
    } else {
        DEBUG_PRINTLN("Configuration saved.");
    }
}

void loadConfiguration() {
    if (EEPROMr.read(EEPROM_START) != 1) { 
        saveConfiguration(); 
    }
    EEPROMr.get(EEPROM_START+2, cfg);
    delay(500);
    DEBUG_PRINTLN("Configuration loaded.");
}
