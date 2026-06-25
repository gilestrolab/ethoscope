// LightControl.cpp
#include "LightControl.h"
#include "incubator.h"
#include "pins.h"
#include "TimeKeeper.h"
#include <time.h>

// Per-direction fade pacing: ms per 1% step, computed from cfg.fade_in_ms /
// fade_out_ms at the top of update(). A floor of 1 ms avoids div-by-zero and
// caps the on-CPU rate.
static unsigned long last_step = 0;

// True iff the cycle-relative time falls inside the [lights_on, lights_off)
// window. Handles wrap-around (lights_on > lights_off) for both wall-clock
// (24h) and T-cycle modes.
static bool inWindow(int minuteInCycle) {
  if (cfg.lights_on == cfg.lights_off) return true;   // always-on convention
  if (cfg.lights_on < cfg.lights_off) {
    return minuteInCycle >= cfg.lights_on && minuteInCycle < cfg.lights_off;
  }
  return minuteInCycle >= cfg.lights_on || minuteInCycle < cfg.lights_off;
}

// Compute "should the light be on right now?" using the same algorithm as the
// node-side ``ethoscope_node.incubators.schedule.is_light_on`` and the
// ethoscope-side ``LightController.should_light_be_on`` — keep all three in
// step or the merged drift detector will think the firmware is wrong forever.
static bool isLightOn() {
  // T-cycle if period != 24h OR an explicit anchor is set; otherwise wall-clock.
  bool anchored = cfg.light_cycle_anchor != 0 || cfg.light_period_minutes != 1440;

  if (anchored) {
    if (cfg.light_cycle_anchor == 0) return false; // non-24h with no anchor → refuse
    time_t now_ts = time(nullptr);
    if (now_ts <= 0) return false;                 // no valid time yet
    long period_s = (long)cfg.light_period_minutes * 60L;
    if (period_s <= 0) return false;
    long phase_s = ((long)now_ts - (long)cfg.light_cycle_anchor) % period_s;
    if (phase_s < 0) phase_s += period_s;
    int phase_min = (int)(phase_s / 60);
    return inWindow(phase_min);
  }

  // Wall-clock mode — same path as the legacy firmware.
  int t = TimeKeeper::localMinuteOfDay();
  if (t < 0) return false;                          // hold off until time is valid
  return inWindow(t);
}

static void evaluateSchedule() {
  state.light_target = isLightOn() ? cfg.max_light : 0;
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

  // Crepuscular off → hard transition. Jump straight to the target so old
  // operators who don't opt in see the legacy on/off behaviour.
  if (!cfg.crepuscular) {
    if (state.light_level != state.light_target) writeLevel(state.light_target);
    return;
  }

  // Direction-aware fade step: separate ramp-up and ramp-down durations.
  // Both stored in ms; one 1% step every (ms / 100) ms with a 1ms floor.
  // (A sunset-like S-curve would require larger code + lookup tables; the
  // node-side reference uses smoothstep, but on the ESP8266 the eye-perceived
  // 1%-per-step linear ramp at this rate is visually indistinguishable from
  // a curved one when the total fade is > ~5 s. Trade-off in favour of code
  // simplicity / RAM headroom.)
  unsigned long fade_ms = (state.light_level < state.light_target)
                          ? cfg.fade_in_ms
                          : cfg.fade_out_ms;
  unsigned long step_ms = fade_ms / 100;
  if (step_ms == 0) step_ms = 1;

  unsigned long now = millis();
  if (now - last_step < step_ms) return;
  last_step = now;

  if (state.light_level < state.light_target)      writeLevel(state.light_level + 1);
  else if (state.light_level > state.light_target) writeLevel(state.light_level - 1);
}

} // namespace LightControl
