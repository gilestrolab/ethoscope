// Sensors.h
// SHT31 (temperature + humidity) and BH1750 (lux) on the shared I2C bus.
// Readings are cached and refreshed no faster than a minimum interval to avoid
// SHT31 self-heating. Updates `state.temperature/humidity/lux/sensor_fault`.
#pragma once

namespace Sensors {
  void begin();          // init I2C + both sensors
  void update();         // refresh readings if the min interval elapsed (call often)
  bool ok();             // true if the last temperature/humidity read was valid
}
