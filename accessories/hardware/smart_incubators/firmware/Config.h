// Config.h
// Load/save the persisted Config struct as JSON on LittleFS (/config.json).
#pragma once
#include <ArduinoJson.h>
#include "incubator.h"

namespace ConfigStore {
  // Mounts LittleFS and loads /config.json into `cfg`. If missing/invalid, keeps the
  // compiled defaults and writes a fresh file. Returns true if an existing file loaded.
  bool begin();

  // Serialises `cfg` to /config.json. Returns true on success.
  bool save();

  // Serialises `cfg` into a JSON object (used by the REST /config endpoint).
  void toJson(JsonObject out);

  // Applies a subset of fields from a JSON object onto `cfg` (used by POST /config).
  // Only known keys are touched; returns the number of fields changed.
  int applyJson(JsonObjectConst in);
}
