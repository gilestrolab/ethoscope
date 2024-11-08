#include <ESP8266WiFi.h>
#include <ESP8266mDNS.h>
#include <ESPAsyncWebServer.h>
#include "network.h"
#include "config.h"

extern AsyncWebServer server;
extern configuration cfg;
extern environment env;

bool setupWiFi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(cfg.wifi_ssid, cfg.wifi_pwd);
    
    unsigned long startAttemptTime = millis();
    
    while (WiFi.status() != WL_CONNECTED && 
           millis() - startAttemptTime < WIFI_CONNECT_TIMEOUT) {
        delay(100);
        DEBUG_PRINT(".");
    }
    
    if (WiFi.status() != WL_CONNECTED) {
        return false;
    }
    
    DEBUG_PRINTLN("\nConnected to WiFi");
    DEBUG_PRINTLN(WiFi.localIP());
    
    setupMDNS();
    return true;
}

void setupMDNS() {
    if (!MDNS.begin(cfg.name)) {
        DEBUG_PRINTLN("Error setting up MDNS responder!");
        return;
    }
    MDNS.addService("sensor", "tcp", 80);
}

void setupWebServer() {
    server.onNotFound([](AsyncWebServerRequest *request){
        request->send(404, "text/plain", "Not found");
    });

    server.on("/id", HTTP_GET, [](AsyncWebServerRequest *request){
        request->send(200, "text/plain", getID());
    });
    
    server.on("/", HTTP_GET, [](AsyncWebServerRequest *request){
        readSensorData();
        request->send(200, "text/plain", SendJSON());
    });
    
    server.on("/set", HTTP_GET, [](AsyncWebServerRequest *request){
        if (request->hasParam("name")) {
            request->getParam("name")->value().toCharArray(cfg.name, 20);
        }
        
        if (request->hasParam("location")) {
            request->getParam("location")->value().toCharArray(cfg.location, 20);
        }
        
        saveConfiguration();
        request->send(200, "text/plain", "OK! Configuration changed.");
    });

    server.begin();
}

void reconnectWiFi() {
    WiFi.disconnect();
    delay(1000);
    setupWiFi();
}

// ... (Include the rest of your existing network-related functions like SendJSON, 
// SendHTML, getMacAddress, and getID)
