// LightControl.h
// Light panel control: a non-blocking fader plus the DD/LD/LL/DL/MM schedule.
// The schedule sets a target level from the local time + mode; the fader walks the
// actual PWM level toward the target one step at a time so loop() never blocks.
#pragma once

namespace LightControl {
  void begin();              // configure the LED PWM pin
  void update();             // evaluate schedule + advance the fade (call often)
  void setManualLevel(int pct); // used in MODE_MM (and by REST) to set the target directly
}
