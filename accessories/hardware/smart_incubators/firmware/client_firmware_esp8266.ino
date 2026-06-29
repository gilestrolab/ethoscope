// client_firmware_esp8266.ino
// Smart Incubator node — WiFi rewrite for the WeMos D1 R2 (ESP8266).
//
// Replaces the legacy nRF24L01 + Arduino UNO node. Regulates temperature with a Peltier
// (via a Cytron SHIELD-MD10 R2 H-bridge), runs a programmable light schedule, senses
// temperature/humidity/lux, keeps time from NTP (DS3231 backup), and exposes an HTTP REST
// API that the controller polls. See README.md for hardware wiring and the API contract.
//
// Architecture note: the ESP8266 WiFi stack must be serviced frequently, so EVERYTHING is
// non-blocking — loop() returns fast and each task runs on its own millis() timer. No
// long delay()s anywhere in the control path.

#include "incubator.h"
#include "Config.h"
#include "Sensors.h"
#include "TimeKeeper.h"
#include "Peltier.h"
#include "LightControl.h"
#include "Network.h"
#include "Api.h"

// Cooperative scheduler: run a task every `interval` ms without blocking.
struct Task {
  unsigned long interval;
  unsigned long last;
  void (*fn)();
};

static void tickTime();      // forward decl

static Task tasks[] = {
  { 1000, 0, Peltier::update      },   // temperature control loop, 1 Hz
  {  200, 0, LightControl::update },   // schedule + fade stepper (fast for smooth fade)
  { 2000, 0, Sensors::update      },   // sensor refresh (internally rate-limited to 5 s)
  { 5000, 0, tickTime             },   // time housekeeping / RTC resync
};
static const size_t NUM_TASKS = sizeof(tasks) / sizeof(tasks[0]);

static void tickTime() { TimeKeeper::update(); }

void setup() {
  Serial.begin(115200);
  Serial.println();
  Serial.print(F("Smart Incubator node fw "));
  Serial.println(F(FW_VERSION));

  state.boot_millis = millis();

  ConfigStore::begin();     // mount LittleFS, load /config.json (or write defaults)
  Sensors::begin();         // I2C + SHT31 + BH1750  (begins Wire)
  TimeKeeper::begin();      // DS3231 seed + SNTP start (shares Wire)
  Peltier::begin();         // PWM/DIR pins; H-bridge forced OFF
  LightControl::begin();    // LED PWM pin
  Network::begin();         // WiFi (portal if unprovisioned), mDNS, OTA
  Api::begin();             // REST server on :80

  Serial.print(F("Ready: http://"));
  Serial.print(Network::hostname());
  Serial.println(F(".local/"));
}

void loop() {
  // Service the network/OTA/HTTP stacks every pass.
  Network::update();
  Api::update();

  // Run scheduled tasks whose interval has elapsed.
  unsigned long now = millis();
  for (size_t i = 0; i < NUM_TASKS; i++) {
    if (now - tasks[i].last >= tasks[i].interval) {
      tasks[i].last = now;
      tasks[i].fn();
    }
  }

  yield();   // hand back to the ESP8266 RTOS/WiFi stack
}
