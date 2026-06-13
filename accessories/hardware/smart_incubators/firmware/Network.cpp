// Network.cpp
#include "Network.h"
#include "Config.h"
#include "incubator.h"
#include <ESP8266WiFi.h>
#include <ESP8266mDNS.h>
#include <ArduinoOTA.h>
#include <WiFiManager.h>

static char host[24];
static unsigned long last_reconnect = 0;
static const unsigned long RECONNECT_INTERVAL_MS = 15000;

static void makeHostname() {
  snprintf(host, sizeof(host), "incubator-%u", cfg.node_id);
}

namespace Network {

const char *hostname() { return host; }

void begin() {
  makeHostname();
  WiFi.mode(WIFI_STA);
  WiFi.hostname(host);

  // --- Provisioning: WiFiManager opens a portal only if no creds are stored or the
  //     connection fails. node_id is offered as a custom field and persisted on change. ---
  WiFiManager wm;
  char idbuf[6];
  snprintf(idbuf, sizeof(idbuf), "%u", cfg.node_id);
  WiFiManagerParameter p_node_id("node_id", "Incubator ID (number)", idbuf, 5);
  wm.addParameter(&p_node_id);
  wm.setConfigPortalTimeout(180);          // give up the portal after 3 min, keep running

  char ap[28];
  snprintf(ap, sizeof(ap), "incubator-setup-%u", cfg.node_id);
  bool connected = wm.autoConnect(ap);     // blocks only during first-time provisioning

  int new_id = atoi(p_node_id.getValue());
  if (new_id > 0 && new_id != cfg.node_id) {
    cfg.node_id = new_id;
    ConfigStore::save();
    makeHostname();
    WiFi.hostname(host);
  }

  state.wifi_connected = connected;

  // --- mDNS: incubator-<id>.local, advertising two services on port 80 so the node
  //     discovers the unit on BOTH channels: as an incubator (IncubatorScanner polls
  //     /telemetry) and as an ethoscope sensor (SensorScanner polls /). ---
  if (MDNS.begin(host)) {
    MDNS.addService("incubator", "tcp", 80);
    MDNS.addServiceTxt("incubator", "tcp", "id", String(cfg.node_id));
    MDNS.addServiceTxt("incubator", "tcp", "fw", FW_VERSION);
    MDNS.addService("sensor", "tcp", 80);
  }

  // --- OTA ---
  ArduinoOTA.setHostname(host);
  ArduinoOTA.begin();
}

void update() {
  ArduinoOTA.handle();
  MDNS.update();

  bool up = (WiFi.status() == WL_CONNECTED);
  state.wifi_connected = up;
  state.rssi = up ? WiFi.RSSI() : 0;

  // Non-blocking reconnect attempts; never stall the control loop.
  if (!up && millis() - last_reconnect > RECONNECT_INTERVAL_MS) {
    last_reconnect = millis();
    WiFi.reconnect();
  }
}

} // namespace Network
