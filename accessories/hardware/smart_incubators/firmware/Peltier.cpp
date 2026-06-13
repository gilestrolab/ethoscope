// Peltier.cpp
#include "Peltier.h"
#include "incubator.h"
#include "pins.h"

static float    integ = 0;            // PID integral accumulator
static float    prev_err = 0;
static unsigned long prev_ms = 0;

static int  applied_duty = 0;         // signed duty actually applied last cycle
static int  current_dir = DIR_HEAT;   // last DIR level written
static unsigned long last_dir_change = 0;

static const float INTEG_LIMIT = 100.0; // anti-windup clamp (in %duty terms)

// Write the H-bridge: signed duty in -100..+100. Positive = heat.
static void drive(int signed_duty) {
  applied_duty = signed_duty;
  state.peltier_duty = signed_duty;

  if (signed_duty == 0) {
    analogWrite(PIN_PELTIER_PWM, 0);    // PWM=0 → both outputs low → motor off
    state.fan_on = false;
    digitalWrite(PIN_FAN, LOW);
    return;
  }

  int want_dir = (signed_duty > 0) ? DIR_HEAT : DIR_COOL;
  if (want_dir != current_dir) {
    current_dir = want_dir;
    last_dir_change = millis();
  }
  digitalWrite(PIN_PELTIER_DIR, current_dir);

  int duty = abs(signed_duty);
  analogWrite(PIN_PELTIER_PWM, (int)((long)duty * PWM_RANGE / 100));

  state.fan_on = true;                  // run the hot-side fan whenever the TEC is active
  digitalWrite(PIN_FAN, HIGH);
}

namespace Peltier {

void begin() {
  pinMode(PIN_PELTIER_DIR, OUTPUT);
  pinMode(PIN_FAN, OUTPUT);
  digitalWrite(PIN_PELTIER_DIR, DIR_COOL);
  digitalWrite(PIN_FAN, LOW);

  analogWriteRange(PWM_RANGE);
  analogWriteFreq(PWM_FREQ_HZ);
  pinMode(PIN_PELTIER_PWM, OUTPUT);
  analogWrite(PIN_PELTIER_PWM, 0);      // guaranteed OFF at init

  prev_ms = millis();
}

void off() { drive(0); integ = 0; }

void update() {
  // ---- Failsafes: any of these forces the Peltier OFF ----
  if (!cfg.peltier_enabled || state.sensor_fault || isnan(state.temperature) ||
      state.temperature < cfg.temp_min || state.temperature > cfg.temp_max) {
    off();
    return;
  }

  unsigned long now = millis();
  float dt = (now - prev_ms) / 1000.0;
  if (dt <= 0) dt = 0.001;
  prev_ms = now;

  float err = cfg.set_temp - state.temperature;   // +ve → need to heat

  // ---- Deadband: close enough → coast, bleed the integral ----
  if (fabs(err) < cfg.deadband) {
    integ *= 0.95;
    prev_err = err;
    drive(0);
    return;
  }

  // ---- PID ----
  integ += cfg.ki * err * dt;
  if (integ >  INTEG_LIMIT) integ =  INTEG_LIMIT;
  if (integ < -INTEG_LIMIT) integ = -INTEG_LIMIT;
  float deriv = (err - prev_err) / dt;
  prev_err = err;

  float out = cfg.kp * err + integ + cfg.kd * deriv;   // % duty, signed

  // ---- Duty ceiling ----
  float ceil = cfg.max_duty;
  if (out >  ceil) out =  ceil;
  if (out < -ceil) out = -ceil;

  int target = (int)out;

  // ---- Direction-dwell: don't reverse current too often. If a reversal is wanted
  //      but the dwell hasn't elapsed, coast (0) rather than driving the old way. ----
  int want_dir = (target > 0) ? DIR_HEAT : DIR_COOL;
  if (target != 0 && want_dir != current_dir &&
      (now - last_dir_change) < cfg.dir_dwell_ms) {
    drive(0);
    return;
  }

  // ---- Slew limit: cap how fast duty changes per cycle ----
  int delta = target - applied_duty;
  int step  = cfg.slew_per_cycle;
  if (delta >  step) target = applied_duty + step;
  if (delta < -step) target = applied_duty - step;

  drive(target);
}

} // namespace Peltier
