#ifndef NETWORK_H
#define NETWORK_H

#include "config.h"
#include "platform.h"
#include "storage.h"
#include "sensors.h"
#include <ArduinoJson.h>


// Use PLATFORM_ATTR instead of ICACHE_FLASH_ATTR
void PLATFORM_ATTR setupWebServer();
void PLATFORM_ATTR handleRoot();
void PLATFORM_ATTR handleConfig();
void PLATFORM_ATTR handleReset();
void PLATFORM_ATTR handleWeb();
bool PLATFORM_ATTR setupWiFi();
void PLATFORM_ATTR reconnectWiFi();
void PLATFORM_ATTR setupMDNS();
String PLATFORM_ATTR getMacAddress();
String PLATFORM_ATTR getID();
String PLATFORM_ATTR SendJSON();
String PLATFORM_ATTR SendConfigHTML();

// External declarations
extern WebServer server;  // Uses the typedef from platform.h
extern configuration cfg;
extern environment env;

#endif // NETWORK_H