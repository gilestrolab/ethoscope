// pins.h
// Pin map for the WeMos D1 R2 (ESP8266). See README.md "Hardware" for the full wiring
// rationale. Assignments are constrained by the Cytron SHIELD-MD10 R2 jumper selectors:
//   PWM (JP5) ∈ {D3,D5,D6,D9,D10,D11}   DIR (JP8) ∈ {D2,D4,D7,D8,D12,D13}
// The D1 R2 only exposes D0..D8, so the only safe, free intersection is PWM=D6, DIR=D7.
#pragma once
#include <Arduino.h>

// --- I2C bus (SHT31 + BH1750 + DS3231) ---
#define PIN_I2C_SDA      D2   // GPIO4  (board-designated SDA)
#define PIN_I2C_SCL      D1   // GPIO5  (board-designated SCL)

// --- Peltier via Cytron SHIELD-MD10 R2 (shield stacked; set its jumpers to match) ---
#define PIN_PELTIER_PWM  D6   // GPIO12 -> MD10 PWM, jumper JP5 = D6
#define PIN_PELTIER_DIR  D7   // GPIO13 -> MD10 DIR, jumper JP8 = D7

// --- Light panel (logic-level N-MOSFET gate) ---
#define PIN_LED_PWM      D5   // GPIO14 -> MOSFET gate (onboard LED mirrors this — cosmetic)

// --- Hot-side fan (direct MOSFET, NOT through the MD10) ---
#define PIN_FAN          D0   // GPIO16 -> fan MOSFET (digital on/off; optional)

// Peltier current-direction polarity.
// IMPORTANT: verify on the bench which DIR level heats vs cools for YOUR TEC wiring
// (depends on how the module faces and how OUT A/B connect). Swap if reversed.
#define DIR_HEAT  HIGH
#define DIR_COOL  LOW

// PWM configuration. MD10 accepts up to 10 kHz; we use 5 kHz.
#define PWM_FREQ_HZ  5000
#define PWM_RANGE    1023    // analogWrite resolution (0..PWM_RANGE)
