// incubator.h
// Shared data model for the WiFi incubator node.
//
// `cfg`   : persisted configuration (LittleFS /config.json), editable over REST.
// `state` : live runtime state (sensor readings, actuator state) — never persisted.
//
// Both are defined once in Config.cpp and referenced everywhere via these externs.
#pragma once
#include <Arduino.h>
#include "version.h"     // FW_VERSION / FW_BUILD / FW_BUILD_DATE

// Light schedule modes (same five behaviours as the legacy radio firmware).
enum LightMode {
  MODE_DD = 0,  // constant dark
  MODE_LD = 1,  // light during the day window [lights_on, lights_off)
  MODE_LL = 2,  // constant light
  MODE_DL = 3,  // inverted: dark during the day window, light otherwise
  MODE_MM = 4   // manual: firmware does not touch the light; set via REST
};

// Persisted configuration. Defaults below are written on first boot.
struct Config {
  uint8_t  node_id        = 1;                              // unique per incubator
  char     name[32]       = "";   // sensor-API name; empty → derived "incubator-<id>"
  char     location[48]   = "";   // sensor-API location; the node (authoritative) sets this
                                  // to the bound incubator's name. Empty → "incubator-<id>"
  char     tz[48]         = "GMT0BST,M3.5.0/1,M10.5.0/2";   // POSIX TZ (UK default)
  char     ntp[64]        = "pool.ntp.org";                 // NTP server — set to a LOCAL
                                                            // IP/hostname for offline labs
                                                            // (e.g. the controller running ntpd)

  // Setpoints & light schedule
  float    set_temp       = 22.0;   // °C  — Peltier target
  float    set_hum        = 65.0;   // %RH — SENSED ONLY (no humidity actuator in HW)
  uint8_t  max_light      = 100;    // %   — light level used when "on"
  uint8_t  mode           = MODE_LD;
  uint16_t lights_on      = 9 * 60;  // minute-of-day, local time (09:00)
  uint16_t lights_off     = 21 * 60; // (21:00)
  uint16_t report_interval = 60;     // s — sensor refresh / telemetry freshness target

  // Temperature control (hand-rolled PID) + safety
  float    kp             = 40.0;   // %duty per °C error
  float    ki             = 0.5;
  float    kd             = 0.0;
  float    deadband       = 0.3;    // °C — within this, Peltier is off (no hunting)
  uint8_t  max_duty       = 100;    // % — duty ceiling
  uint16_t dir_dwell_ms   = 30000;  // ms — min time between heat/cool reversals
  uint8_t  slew_per_cycle = 10;     // % — max duty change per control cycle
  float    temp_min       = 5.0;    // °C — below/above → failsafe OFF (implausible/unsafe)
  float    temp_max       = 45.0;
  bool     peltier_enabled = true;
};

// Live runtime state.
struct State {
  // Sensors
  float temperature = NAN;   // °C   (SHT31)
  float humidity    = NAN;   // %RH  (SHT31)
  float lux         = NAN;   // lux  (BH1750)
  bool  sensor_fault = true; // true until a valid SHT31 read succeeds

  // Actuators
  int  light_level  = 0;     // current light %, 0..100 (faded)
  int  light_target = 0;     // commanded light %, 0..100
  int  peltier_duty = 0;     // -100..+100  (sign = direction; + = heating)
  bool fan_on       = false;

  // Time / network
  bool time_valid     = false;
  bool wifi_connected = false;
  int  rssi           = 0;
  unsigned long boot_millis = 0;
};

extern Config cfg;
extern State  state;
