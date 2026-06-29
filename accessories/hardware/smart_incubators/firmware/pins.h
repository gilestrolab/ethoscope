// pins.h
// Pin map for the WeMos D1 R2 (ESP8266). See README.md "Hardware" for the full wiring
// rationale. Assignments are constrained by the Cytron SHIELD-MD10 R2 jumper selectors,
// which use Arduino-format labels. On this board revision the Arduino<->Wemos silkscreen
// maps as follows for the available jumper positions:
//   PWM (JP5)  Arduino->Wemos:  D3->D1, D5->D3, D6->D4, D9->D7, D10->D8, D11->D7(MOSI)
//   DIR (JP8)  Arduino->Wemos:  D2->D0, D4->D2(SDA), D7->D5, D8->D6, D12->D6(MISO), D13->D5(SCK)
// Active picks below: PWM jumper = Arduino-D6 (Wemos D4 = GPIO2),
// DIR jumper = Arduino-D2 (Wemos D0 = GPIO16).
// Note the -2 shift on this board revision: Arduino-DN sits at Wemos-D(N-2).
#pragma once
#include <Arduino.h>

// --- I2C bus (SHT31 + BH1750 + DS3231) ---
#define PIN_I2C_SDA      D2   // GPIO4  (board-designated SDA)
#define PIN_I2C_SCL      D1   // GPIO5  (board-designated SCL)

// --- Peltier via Cytron SHIELD-MD10 R2 (shield stacked; set its jumpers to match) ---
// PWM lands on GPIO2 (the built-in LED pin). The LED will mirror PWM duty — cosmetic.
// GPIO2 must be HIGH at boot, which the internal pull-up handles; consequence is a brief
// (~100 ms) blip of full-duty TEC current at the boot-default DIR before begin() runs,
// which is harmless because DIR defaults to DIR_COOL (the safe direction).
#define PIN_PELTIER_PWM  D4   // GPIO2  -> MD10 PWM, jumper JP5 = Arduino-D6 (Wemos D4)
#define PIN_PELTIER_DIR  D0   // GPIO16 -> MD10 DIR, jumper JP8 = Arduino-D2 (Wemos D0)

// --- Light panel (logic-level N-MOSFET gate, e.g. 30N06L low-side switch) ---
// GPIO15 must be LOW at boot; the 10k gate pull-down on the MOSFET enforces this.
// Do NOT add an external pull-up on this line.
#define PIN_LED_PWM      D8   // GPIO15 -> MOSFET gate

// --- Hot-side fan (direct MOSFET, NOT through the MD10) ---
#define PIN_FAN          D7   // GPIO13 -> fan MOSFET (digital on/off; optional)

// Peltier current-direction polarity.
// IMPORTANT: verify on the bench which DIR level heats vs cools for YOUR TEC wiring
// (depends on how the module faces and how OUT A/B connect). Swap if reversed.
#define DIR_HEAT  HIGH
#define DIR_COOL  LOW

// PWM configuration. MD10 accepts up to 10 kHz; we use 5 kHz.
#define PWM_FREQ_HZ  5000
#define PWM_RANGE    1023    // analogWrite resolution (0..PWM_RANGE)

// Gamma correction for the LED panel PWM. Human brightness perception is roughly
// logarithmic, so a linear duty cycle looks crammed at the bottom and plateaued
// at the top. ~2.2 matches the sRGB convention and gives a visually even ramp.
#define LIGHT_GAMMA  2.2f
