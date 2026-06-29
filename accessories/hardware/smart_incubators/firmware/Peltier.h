// Peltier.h
// Bidirectional temperature regulation through the Cytron SHIELD-MD10 R2.
//   - hand-rolled PID on (set_temp - measured)
//   - sign of the output -> DIR (heat/cool); magnitude -> PWM duty
//   - deadband, direction-dwell, slew limiting, and a sensor/over-temp failsafe
// Sets state.peltier_duty (signed, -100..+100) and state.fan_on.
#pragma once

namespace Peltier {
  void begin();    // configure PWM/DIR pins; force the H-bridge OFF
  void update();   // run one control cycle (call ~1 Hz)
  void off();      // immediately stop the Peltier (duty 0)
}
