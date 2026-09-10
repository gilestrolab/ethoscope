// LightControl.h
// Light panel control: a non-blocking fader plus the LD window schedule.
// The schedule sets a target level from the local time; the fader walks the
// actual PWM level toward the target one step at a time so loop() never blocks.
// A manual override (REST ``set_light``) holds a level until the schedule next
// flips on/off, then the schedule takes back control.
#pragma once

namespace LightControl {
  void begin();              // configure the LED PWM pin
  void update();             // evaluate schedule + advance the fade (call often)
  void setManualLevel(int pct); // 0..100 = hold this level; < 0 = back to the schedule
}
