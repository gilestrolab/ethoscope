// LightControl.cpp
#include "LightControl.h"
#include "incubator.h"
#include "pins.h"
#include "TimeKeeper.h"

// Fade pacing: ms per 1% step (10 ms ≈ 1 s for a full 0→100 sweep, like the legacy FW).
static const unsigned long FADE_STEP_MS = 10;
static unsigned long last_step = 0;

// Is the local time inside the [lights_on, lights_off) window? Handles an overnight
// window (lights_on > lights_off) too.
static bool inDayWindow(int minuteOfDay) {
  if (cfg.lights_on == cfg.lights_off) return false;       // zero-length window
  if (cfg.lights_on < cfg.lights_off) {
    return minuteOfDay >= cfg.lights_on && minuteOfDay < cfg.lights_off;
  }
  // overnight window, e.g. on=21:00 off=06:00
  return minuteOfDay >= cfg.lights_on || minuteOfDay < cfg.lights_off;
}

// Decide the target light level from mode + time.
static void evaluateSchedule() {
  if (cfg.mode == MODE_MM) return;        // manual: leave target untouched

  switch (cfg.mode) {
    case MODE_DD: state.light_target = 0; return;
    case MODE_LL: state.light_target = cfg.max_light; return;
    default: break;                        // LD / DL need the clock
  }

  int t = TimeKeeper::localMinuteOfDay();
  if (t < 0) return;                        // no valid time yet → hold current target

  bool day = inDayWindow(t);
  if (cfg.mode == MODE_LD) state.light_target = day ? cfg.max_light : 0;
  else /* MODE_DL */       state.light_target = day ? 0 : cfg.max_light;
}

static void writeLevel(int pct) {
  state.light_level = pct;
  analogWrite(PIN_LED_PWM, (int)((long)pct * PWM_RANGE / 100));
}

namespace LightControl {

void begin() {
  analogWriteRange(PWM_RANGE);
  analogWriteFreq(PWM_FREQ_HZ);
  pinMode(PIN_LED_PWM, OUTPUT);
  writeLevel(0);
}

void setManualLevel(int pct) {
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  state.light_target = pct;
}

void update() {
  evaluateSchedule();

  // Non-blocking fade toward the target, one percent per FADE_STEP_MS.
  unsigned long now = millis();
  if (now - last_step < FADE_STEP_MS) return;
  last_step = now;

  if (state.light_level < state.light_target)      writeLevel(state.light_level + 1);
  else if (state.light_level > state.light_target) writeLevel(state.light_level - 1);
}

} // namespace LightControl
