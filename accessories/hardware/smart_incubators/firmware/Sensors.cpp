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

// --- Sensor recovery thresholds ---------------------------------------------
// On a glitchy I2C bus at boot (e.g. another device with swapped SDA/SCL),
// a chip's begin() can ACK but its configuration write may silently fail,
// leaving the sensor in a half-initialised state that never recovers without
// a reboot — observed on the BH1750 producing 0 lux indefinitely. The two
// trackers below let update() re-call begin() periodically without complex
// bus-monitoring:
//   - last_sht_activity_ms: bumped on each successful SHT31 read AND on each
//     re-init attempt, so retries are paced at SHT_RECOVER_MS even if the
//     sensor is permanently absent. A stale window > SHT_RECOVER_MS (= 30 s)
//     triggers sht.begin() again. NaN reads stop bumping the counter, which
//     is the trigger that catches an SHT31 that went into a stuck mode.
//   - last_bh_refresh_ms: bumped on each lightMeter.begin(). Refreshed every
//     BH_REFRESH_MS regardless of read success, because a 0 lux reading is
//     ambiguous (real darkness vs. power-down latch) — we have no other
//     local signal to detect the stuck-at-0 case.
static unsigned long last_sht_activity_ms = 0;
static unsigned long last_bh_refresh_ms = 0;
static const unsigned long SHT_RECOVER_MS = 30000UL;
static const unsigned long BH_REFRESH_MS  = 300000UL;  // 5 min

namespace Sensors {

void begin() {
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setClock(100000);

  sht_present = sht.begin(0x44);          // 0x44 default; 0x45 if ADDR tied high
  bh_present  = lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE);

  unsigned long now = millis();
  last_sht_activity_ms = now;             // pace the first retry SHT_RECOVER_MS later
  last_bh_refresh_ms   = now;

  state.sensor_fault = !sht_present;      // temp/hum is the critical sensor for control
}

void update() {
  unsigned long now = millis();

  // Re-init either chip if it has gone quiet. Cheap (one config write each)
  // and catches a chip that ACKed at boot but never accepted its mode.
  if ((now - last_sht_activity_ms) > SHT_RECOVER_MS) {
    sht_present = sht.begin(0x44);
    last_sht_activity_ms = now;           // pace next retry whether or not it stuck
    if (!sht_present) state.sensor_fault = true;
  }
  if ((now - last_bh_refresh_ms) > BH_REFRESH_MS) {
    bh_present = lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE);
    last_bh_refresh_ms = now;
  }

  if (last_read != 0 && (now - last_read) < MIN_INTERVAL_MS) return;
  last_read = now;

  if (sht_present) {
    float t = sht.readTemperature();
    float h = sht.readHumidity();
    if (!isnan(t) && !isnan(h)) {
      state.temperature    = t;
      state.humidity       = h;
      state.sensor_fault   = false;
      last_sht_activity_ms = now;         // good read = chip is healthy
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
