// TimeKeeper.h
// Time strategy: NTP (SNTP) is primary; a DS1307 or DS3231 RTC is a battery-backed backup
// (handled by the RTC_DS1307 class — both share I2C 0x68 and the same time registers).
//  - At boot (before WiFi/NTP), seed the system clock from the DS3231 if it holds a
//    plausible time, so the light schedule works immediately offline.
//  - Once NTP delivers a valid time, periodically write it back to the DS3231.
// Local time (via the POSIX TZ in cfg.tz) drives the light schedule.
#pragma once
#include <stdint.h>

namespace TimeKeeper {
  void begin();              // init DS3231, seed clock, start SNTP with cfg.tz/cfg.ntp
  void update();             // housekeeping: refresh time_valid, resync RTC, re-apply config
  void syncRtcFromNtp();     // force-write current NTP time into the DS3231
  void setTime(uint32_t epoch); // manually set the clock (UTC epoch) + DS3231 — no NTP needed

  bool valid();              // true once the system clock holds a real (post-2021) time
  int  localMinuteOfDay();   // 0..1439 in local time, or -1 if time is not yet valid
}
