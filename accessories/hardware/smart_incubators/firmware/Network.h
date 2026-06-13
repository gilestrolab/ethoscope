// Network.h
// WiFi connectivity, provisioning, mDNS discovery and OTA updates.
//  - WiFiManager handles first-boot provisioning (captive portal "incubator-setup-<id>")
//    and stores credentials; node_id is captured as a custom parameter into config.json.
//  - mDNS advertises the node as  incubator-<id>.local  (HTTP service on port 80).
//  - ArduinoOTA enables LAN firmware push.
//  - Non-blocking reconnect keeps the control loop alive while offline.
#pragma once

namespace Network {
  void begin();      // bring up WiFi (portal if needed), mDNS, OTA
  void update();     // service OTA + mDNS, refresh rssi/connection state, reconnect
  const char *hostname();
}
