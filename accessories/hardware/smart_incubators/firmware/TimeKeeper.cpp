// TimeKeeper.cpp
#include "TimeKeeper.h"
#include "incubator.h"
#include <time.h>
#include <sys/time.h>
#include <Wire.h>
#include <RTClib.h>

// RTC_DS1307 works with BOTH the DS1307 and DS3231: they share I2C 0x68 and the same
// time registers (0x00-0x06). isrunning() (the DS1307 CH bit) reads as "running" on a
// DS3231 too, so this one class covers either module on the bus.
static RTC_DS1307 rtc;
static bool rtc_present = false;
static unsigned long last_rtc_sync = 0;
static const unsigned long RTC_SYNC_INTERVAL_MS = 3600000UL; // resync RTC hourly

// Anything before 2021-01-01 means the clock has not been set yet.
static const time_t MIN_VALID_EPOCH = 1609459200;

// Track what we last pushed to SNTP so a runtime tz/ntp change can be re-applied.
static char applied_tz[48]  = "";
static char applied_ntp[64] = "";

// (Re)start SNTP with the configured timezone + NTP server. The configured server is
// primary; pool.ntp.org is a fallback used only when the internet is reachable.
static void applyTimeConfig() {
  strlcpy(applied_tz,  cfg.tz,  sizeof(applied_tz));
  strlcpy(applied_ntp, cfg.ntp, sizeof(applied_ntp));
  configTime(cfg.tz, cfg.ntp, "pool.ntp.org");
}

namespace TimeKeeper {

void begin() {
  rtc_present = rtc.begin();   // uses the shared Wire bus (already begun by Sensors)

  // Seed the system clock from the RTC so the schedule works before NTP arrives.
  if (rtc_present && rtc.isrunning()) {
    DateTime dt = rtc.now();
    if (dt.unixtime() > MIN_VALID_EPOCH) {
      struct timeval tv = { (time_t)dt.unixtime(), 0 };
      settimeofday(&tv, nullptr);
    }
  }

  applyTimeConfig();           // start SNTP (configTime also applies the POSIX TZ string)
}

bool valid() { return time(nullptr) > MIN_VALID_EPOCH; }

void setTime(uint32_t epoch) {
  if (epoch < (uint32_t)MIN_VALID_EPOCH) return;   // reject implausible times
  struct timeval tv = { (time_t)epoch, 0 };
  settimeofday(&tv, nullptr);
  if (rtc_present) rtc.adjust(DateTime(epoch));     // persist to the backup RTC too
}

void syncRtcFromNtp() {
  if (!rtc_present) return;
  time_t now = time(nullptr);
  if (now > MIN_VALID_EPOCH) {
    rtc.adjust(DateTime((uint32_t)now));
    last_rtc_sync = millis();
  }
}

void update() {
  // If tz/ntp were changed over REST, re-apply without needing a reboot.
  if (strcmp(applied_tz, cfg.tz) != 0 || strcmp(applied_ntp, cfg.ntp) != 0) {
    applyTimeConfig();
  }

  state.time_valid = valid();

  // Once NTP is good, keep the backup RTC fresh (hourly, and once right after sync).
  if (state.time_valid &&
      (last_rtc_sync == 0 || millis() - last_rtc_sync > RTC_SYNC_INTERVAL_MS)) {
    syncRtcFromNtp();
  }
}

int localMinuteOfDay() {
  if (!valid()) return -1;
  time_t now = time(nullptr);
  struct tm lt;
  localtime_r(&now, &lt);     // TZ-aware (configTime set the zone)
  return lt.tm_hour * 60 + lt.tm_min;
}

} // namespace TimeKeeper
