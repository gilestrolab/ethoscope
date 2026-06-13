// Sensors.cpp
#include "Sensors.h"
#include "incubator.h"
#include "pins.h"
#include <Wire.h>
#include <Adafruit_SHT31.h>
#include <BH1750.h>

static Adafruit_SHT31 sht;
static BH1750 lightMeter;

static bool sht_present = false;
static bool bh_present  = false;

// Don't poll the SHT31 faster than this (self-heating guard, matches legacy 5 s).
static const unsigned long MIN_INTERVAL_MS = 5000;
static unsigned long last_read = 0;

namespace Sensors {

void begin() {
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setClock(100000);

  sht_present = sht.begin(0x44);          // 0x44 default; 0x45 if ADDR tied high
  bh_present  = lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE);

  state.sensor_fault = !sht_present;      // temp/hum is the critical sensor for control
}

void update() {
  unsigned long now = millis();
  if (last_read != 0 && (now - last_read) < MIN_INTERVAL_MS) return;
  last_read = now;

  if (sht_present) {
    float t = sht.readTemperature();
    float h = sht.readHumidity();
    if (!isnan(t) && !isnan(h)) {
      state.temperature  = t;
      state.humidity     = h;
      state.sensor_fault = false;
    } else {
      state.sensor_fault = true;          // bad read → control loop will failsafe
    }
  } else {
    state.sensor_fault = true;
  }

  if (bh_present && lightMeter.measurementReady()) {
    float l = lightMeter.readLightLevel();
    if (l >= 0) state.lux = l;
  }
}

bool ok() { return !state.sensor_fault; }

} // namespace Sensors
