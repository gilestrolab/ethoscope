#ifndef NETWORK_H
#define NETWORK_H

bool setupWiFi();
void reconnectWiFi();
void setupWebServer();
void setupMDNS();
String getMacAddress();
String getID();
String SendJSON();
String SendHTML();

#endif
