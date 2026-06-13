// Api.cpp
#include "Api.h"
#include "Config.h"
#include "incubator.h"
#include "Network.h"
#include "TimeKeeper.h"
#include "LightControl.h"
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <ArduinoJson.h>
#include <time.h>
#include <math.h>

static ESP8266WebServer server(80);

// ---- Sensor-API helpers (the incubator also presents itself as an ethoscope "sensor":
//      same endpoints/JSON as accessories/hardware/etho_sensor, so the node SensorScanner
//      logs it and runs temperature alerts with no node-side changes). ----

static String macAddress() {
  uint8_t m[6];
  WiFi.macAddress(m);
  char b[18];
  sprintf(b, "%02X:%02X:%02X:%02X:%02X:%02X", m[0], m[1], m[2], m[3], m[4], m[5]);
  return String(b);
}

// name/location default to the incubator identity when unset, so a sensor reading always
// groups under its incubator. The node overwrites `location` (authoritatively) via POST /set.
static String sensorName() {
  return cfg.name[0] ? String(cfg.name) : (String("incubator-") + cfg.node_id);
}
static String sensorLocation() {
  return cfg.location[0] ? String(cfg.location) : (String("incubator-") + cfg.node_id);
}

// Sensor JSON sends values as strings (matches etho_sensor); NaN → "N/A".
static String fmtFloat(float v) {
  if (isnan(v)) return String("N/A");
  char b[12];
  dtostrf(v, 0, 2, b);
  return String(b);
}
static String fmtLux(float v) {
  if (isnan(v)) return String("N/A");
  return String((int)lroundf(v));
}

static const char *modeName(uint8_t m) {
  switch (m) {
    case MODE_DD: return "DD";
    case MODE_LD: return "LD";
    case MODE_LL: return "LL";
    case MODE_DL: return "DL";
    default:      return "MM";
  }
}

// Build the telemetry object (also used by the root status page).
static void fillTelemetry(JsonObject o) {
  o["node_id"]      = cfg.node_id;
  o["fw"]           = FW_VERSION;
  o["build"]        = FW_BUILD;
  o["built"]        = FW_BUILD_DATE;
  o["time"]         = (uint32_t)time(nullptr);
  o["time_valid"]   = state.time_valid;
  o["uptime_s"]     = (millis() - state.boot_millis) / 1000;

  o["temperature"]  = state.temperature;
  o["humidity"]     = state.humidity;
  o["lux"]          = state.lux;
  o["sensor_fault"] = state.sensor_fault;

  o["set_temp"]     = cfg.set_temp;
  o["set_hum"]      = cfg.set_hum;
  o["mode"]         = modeName(cfg.mode);
  o["light_level"]  = state.light_level;
  o["light_target"] = state.light_target;
  o["max_light"]    = cfg.max_light;
  o["lights_on"]    = cfg.lights_on;
  o["lights_off"]   = cfg.lights_off;

  o["peltier_duty"] = state.peltier_duty;            // signed: + heat / - cool
  o["peltier_dir"]  = state.peltier_duty > 0 ? "heat"
                    : state.peltier_duty < 0 ? "cool" : "off";
  o["fan_on"]       = state.fan_on;

  o["rssi"]         = state.rssi;
  o["wifi"]         = state.wifi_connected;
}

static void sendJson(JsonDocument &doc, int code = 200) {
  String out;
  serializeJson(doc, out);
  server.send(code, "application/json", out);
}

// ---- Route handlers ----

static void handleTelemetry() {
  JsonDocument doc;
  fillTelemetry(doc.to<JsonObject>());
  sendJson(doc);
}

static void handleGetConfig() {
  JsonDocument doc;
  ConfigStore::toJson(doc.to<JsonObject>());
  sendJson(doc);
}

static void handlePostConfig() {
  JsonDocument doc;
  if (deserializeJson(doc, server.arg("plain"))) {
    server.send(400, "application/json", "{\"error\":\"bad json\"}");
    return;
  }
  int n = ConfigStore::applyJson(doc.as<JsonObjectConst>());
  if (n > 0) ConfigStore::save();

  JsonDocument resp;
  resp["changed"] = n;
  ConfigStore::toJson(resp["config"].to<JsonObject>());
  sendJson(resp);
}

static void handleCommand() {
  JsonDocument doc;
  if (deserializeJson(doc, server.arg("plain"))) {
    server.send(400, "application/json", "{\"error\":\"bad json\"}");
    return;
  }
  JsonObjectConst in = doc.as<JsonObjectConst>();
  JsonDocument resp;

  if (in["sync_time"].as<bool>())  { TimeKeeper::syncRtcFromNtp(); resp["sync_time"] = true; }
  if (in["set_time"].is<unsigned long>()) { uint32_t e = in["set_time"].as<unsigned long>(); TimeKeeper::setTime(e); resp["set_time"] = e; }
  if (in["set_light"].is<int>())   { LightControl::setManualLevel(in["set_light"]); resp["set_light"] = (int)in["set_light"]; }
  if (in["identify"].as<bool>())   { resp["identify"] = true; }   // (hook for a blink/beep)
  if (in["reboot"].as<bool>())     { resp["reboot"] = true; sendJson(resp); delay(200); ESP.restart(); return; }

  resp["ok"] = true;
  sendJson(resp);
}

static void handleHealth() {
  JsonDocument doc;
  doc["wifi"]         = state.wifi_connected;
  doc["rssi"]         = state.rssi;
  doc["heap"]         = ESP.getFreeHeap();
  doc["time_valid"]   = state.time_valid;
  doc["sensor_fault"] = state.sensor_fault;
  doc["uptime_s"]     = (millis() - state.boot_millis) / 1000;
  doc["host"]         = Network::hostname();
  doc["fw"]           = FW_VERSION;
  doc["build"]        = FW_BUILD;
  sendJson(doc);
}

// GET /  → sensor JSON (the ethoscope "sensor" data endpoint).
static void handleSensorData() {
  JsonDocument doc;
  doc["id"]          = macAddress();
  doc["ip"]          = WiFi.localIP().toString();
  doc["name"]        = sensorName();
  doc["location"]    = sensorLocation();
  doc["temperature"] = fmtFloat(state.temperature);
  doc["humidity"]    = fmtFloat(state.humidity);
  doc["light"]       = fmtLux(state.lux);     // BH1750 lux (etho_sensor "light")
  doc["alerts"]      = true;                  // participate in node temperature alerts
  sendJson(doc);
}

// GET /id → {"id":"<MAC>"} (sensor identity).
static void handleId() {
  JsonDocument doc;
  doc["id"] = macAddress();
  sendJson(doc);
}

// POST /set → update sensor name/location (the node pushes the bound incubator name here).
static void handleSet() {
  JsonDocument doc;
  if (deserializeJson(doc, server.arg("plain"))) {
    server.send(400, "application/json", "{\"error\":\"bad json\"}");
    return;
  }
  JsonObjectConst in = doc.as<JsonObjectConst>();
  int n = 0;
  if (in["name"].is<const char *>())     { strlcpy(cfg.name, in["name"], sizeof(cfg.name)); n++; }
  if (in["location"].is<const char *>()) { strlcpy(cfg.location, in["location"], sizeof(cfg.location)); n++; }
  if (n > 0) ConfigStore::save();
  JsonDocument resp;
  resp["status"]  = "ok";
  resp["changed"] = n;
  sendJson(resp);
}

// GET /status → human-readable status page (was "/" before the sensor API took that route).
static void handleStatus() {
  JsonDocument doc;
  fillTelemetry(doc.to<JsonObject>());
  String body;
  serializeJsonPretty(doc, body);
  String page = "<!doctype html><html><head><meta charset=utf-8>"
                "<title>Incubator ";
  page += cfg.node_id;
  page += "</title><meta http-equiv=refresh content=5></head>"
          "<body style='font-family:monospace'><h2>Incubator ";
  page += cfg.node_id;
  page += " (";
  page += FW_VERSION;
  page += " build ";
  page += FW_BUILD;
  page += ")</h2><pre>";
  page += body;
  page += "</pre><p>Incubator REST: GET /telemetry /config /health · POST /config /command"
          "<br>Sensor API: GET / /id · POST /set</p>"
          "</body></html>";
  server.send(200, "text/html", page);
}

namespace Api {

void begin() {
  // Incubator-specific API (polled by the node IncubatorScanner).
  server.on("/telemetry", HTTP_GET,  handleTelemetry);
  server.on("/config",    HTTP_GET,  handleGetConfig);
  server.on("/config",    HTTP_POST, handlePostConfig);
  server.on("/command",   HTTP_POST, handleCommand);
  server.on("/health",    HTTP_GET,  handleHealth);
  // Sensor-compatible API (discovered by the node SensorScanner as an ethoscope sensor).
  server.on("/",          HTTP_GET,  handleSensorData);
  server.on("/id",        HTTP_GET,  handleId);
  server.on("/set",       HTTP_POST, handleSet);
  // Human status page (moved off "/" to make room for the sensor data endpoint).
  server.on("/status",    HTTP_GET,  handleStatus);
  server.begin();
}

void update() { server.handleClient(); }

} // namespace Api
