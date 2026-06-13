// Config.cpp
#include "Config.h"
#include <LittleFS.h>

// The single definitions of the shared globals (declared extern in incubator.h).
Config cfg;
State  state;

static const char *CONFIG_PATH = "/config.json";

namespace ConfigStore {

// Helper: clamp a value into [lo, hi].
template <typename T> static T clampv(T v, T lo, T hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

void toJson(JsonObject o) {
  o["node_id"]         = cfg.node_id;
  o["name"]            = cfg.name;
  o["location"]        = cfg.location;
  o["tz"]              = cfg.tz;
  o["ntp"]             = cfg.ntp;
  o["set_temp"]        = cfg.set_temp;
  o["set_hum"]         = cfg.set_hum;
  o["max_light"]       = cfg.max_light;
  o["mode"]            = cfg.mode;
  o["lights_on"]       = cfg.lights_on;
  o["lights_off"]      = cfg.lights_off;
  o["report_interval"] = cfg.report_interval;
  o["kp"]              = cfg.kp;
  o["ki"]              = cfg.ki;
  o["kd"]              = cfg.kd;
  o["deadband"]        = cfg.deadband;
  o["max_duty"]        = cfg.max_duty;
  o["dir_dwell_ms"]    = cfg.dir_dwell_ms;
  o["slew_per_cycle"]  = cfg.slew_per_cycle;
  o["temp_min"]        = cfg.temp_min;
  o["temp_max"]        = cfg.temp_max;
  o["peltier_enabled"] = cfg.peltier_enabled;
}

// Accept "09:00" or a raw minute-of-day integer.
static bool parseMinuteOfDay(JsonVariantConst v, uint16_t &out) {
  if (v.is<const char *>()) {
    const char *s = v.as<const char *>();
    int hh = 0, mm = 0;
    if (sscanf(s, "%d:%d", &hh, &mm) == 2) {
      out = clampv(hh * 60 + mm, 0, 24 * 60 - 1);
      return true;
    }
    return false;
  }
  if (v.is<int>()) { out = clampv(v.as<int>(), 0, 24 * 60 - 1); return true; }
  return false;
}

int applyJson(JsonObjectConst in) {
  int n = 0;
  if (in["node_id"].is<int>())   { cfg.node_id = in["node_id"]; n++; }
  if (in["name"].is<const char *>()) {
    strlcpy(cfg.name, in["name"], sizeof(cfg.name)); n++;
  }
  if (in["location"].is<const char *>()) {
    strlcpy(cfg.location, in["location"], sizeof(cfg.location)); n++;
  }
  if (in["tz"].is<const char *>()) {
    strlcpy(cfg.tz, in["tz"], sizeof(cfg.tz)); n++;
  }
  if (in["ntp"].is<const char *>()) {
    strlcpy(cfg.ntp, in["ntp"], sizeof(cfg.ntp)); n++;
  }
  if (in["set_temp"].is<float>())  { cfg.set_temp = clampv((float)in["set_temp"], 0.0f, 50.0f); n++; }
  if (in["set_hum"].is<float>())   { cfg.set_hum  = clampv((float)in["set_hum"], 0.0f, 100.0f); n++; }
  if (in["max_light"].is<int>())   { cfg.max_light = clampv((int)in["max_light"], 0, 100); n++; }
  if (in["mode"].is<int>())        { cfg.mode = clampv((int)in["mode"], 0, 4); n++; }
  // mode may also arrive as a string ("LD", "DD", ...)
  if (in["mode"].is<const char *>()) {
    const char *m = in["mode"];
    if      (!strcmp(m, "DD")) cfg.mode = MODE_DD;
    else if (!strcmp(m, "LD")) cfg.mode = MODE_LD;
    else if (!strcmp(m, "LL")) cfg.mode = MODE_LL;
    else if (!strcmp(m, "DL")) cfg.mode = MODE_DL;
    else if (!strcmp(m, "MM")) cfg.mode = MODE_MM;
    n++;
  }
  uint16_t mod;
  if (in["lights_on"]  && parseMinuteOfDay(in["lights_on"],  mod)) { cfg.lights_on  = mod; n++; }
  if (in["lights_off"] && parseMinuteOfDay(in["lights_off"], mod)) { cfg.lights_off = mod; n++; }
  if (in["report_interval"].is<int>()) { cfg.report_interval = clampv((int)in["report_interval"], 1, 3600); n++; }
  if (in["kp"].is<float>())            { cfg.kp = in["kp"]; n++; }
  if (in["ki"].is<float>())            { cfg.ki = in["ki"]; n++; }
  if (in["kd"].is<float>())            { cfg.kd = in["kd"]; n++; }
  if (in["deadband"].is<float>())      { cfg.deadband = clampv((float)in["deadband"], 0.0f, 5.0f); n++; }
  if (in["max_duty"].is<int>())        { cfg.max_duty = clampv((int)in["max_duty"], 0, 100); n++; }
  if (in["dir_dwell_ms"].is<int>())    { cfg.dir_dwell_ms = clampv((int)in["dir_dwell_ms"], 0, 600000); n++; }
  if (in["slew_per_cycle"].is<int>())  { cfg.slew_per_cycle = clampv((int)in["slew_per_cycle"], 1, 100); n++; }
  if (in["temp_min"].is<float>())      { cfg.temp_min = in["temp_min"]; n++; }
  if (in["temp_max"].is<float>())      { cfg.temp_max = in["temp_max"]; n++; }
  if (in["peltier_enabled"].is<bool>()){ cfg.peltier_enabled = in["peltier_enabled"]; n++; }
  return n;
}

bool save() {
  File f = LittleFS.open(CONFIG_PATH, "w");
  if (!f) return false;
  JsonDocument doc;
  toJson(doc.to<JsonObject>());
  bool ok = serializeJson(doc, f) > 0;
  f.close();
  return ok;
}

bool begin() {
  if (!LittleFS.begin()) {
    // First-ever boot on a blank FS: format then mount.
    LittleFS.format();
    LittleFS.begin();
  }
  File f = LittleFS.open(CONFIG_PATH, "r");
  if (!f) {            // no config yet — write defaults
    save();
    return false;
  }
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, f);
  f.close();
  if (err) {           // corrupt config — fall back to defaults
    save();
    return false;
  }
  applyJson(doc.as<JsonObjectConst>());
  return true;
}

} // namespace ConfigStore
