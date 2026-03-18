/* =============================================================================
 * ARDUINO MOTOR/VALVE/LED CONTROL MODULE
 * =============================================================================
 *
 * Purpose:
 *   Controls motors, solenoid valves, and LEDs using Darlington arrays via
 *   serial commands. Supports multiple module configurations for flexible
 *   use cases including optogenetic stimulation.
 *
 * Supported Modules:
 *   - MODULE 0: N20 Sleep Deprivation Module
 *       * Rotates up to twenty N20 geared motors independently.
 *
 *   - MODULE 1: AGOSD Sleep Deprivation and Odour Arousal Module
 *       * Operates ten N20 geared motors and ten solenoid valves independently.
 *
 *   - MODULE 2: AGO Odour Arousal Module
 *       * Operates ten solenoid valves independently.
 *
 *   - MODULE 3: mAGOLED Motor and Optogenetic LED Module
 *       * Operates ten N20 geared motors and ten LEDs independently.
 *       * LEDs on even channels, motors on odd channels.
 *
 *   - MODULE 4: LED Optogenetic Module
 *       * Operates twenty LEDs independently.
 *       * Designed for CsChrimson activation at 620-630 nm.
 *
 * Hardware Configuration:
 *   - PCB Version: Defined by PCBVERSION (10 for v1.0, 11 for v1.1)
 *   - Module Type: Defined by MODULE (0-4)
 *   - Microcontroller: Arduino Micro
 *   - Power Requirements:
 *     * Motors: 6-12V DC (according to N20 motor specifications)
 *     * Solenoids: As per valve specifications
 *     * LEDs: Via current-limiting resistors (intensity set at hardware level)
 *     * Current Budget:
 *         - Motors: Max 10x500mA = 5A
 *         - Solenoids: As per usage (not activated unless commanded)
 *         - LEDs: Max 20x20mA = 400mA
 *     * Total System Current: Up to 10A continuous with safety margin
 *   - Darlington Arrays:
 *     * Example: ULN2803 or similar
 *     * Ensure proper heat sinking and current ratings
 *
 * Serial Communication:
 *   - Baud Rate: 115200 (fixed)
 *   - Format: ASCII commands terminated by newline/carriage return
 *
 * Serial Commands Overview:
 * +---------+-------------------------------+-------------------------------------------+
 * | Command | Format                        | Description                               |
 * +---------+-------------------------------+-------------------------------------------+
 * | P       | P [0-19] [ms]                 | Pulse single channel for specified ms     |
 * | A       | A [s]                         | Activate all motors for specified seconds |
 * | W       | W [ch] [on_ms] [off_ms] [n]   | Pulse train on channel (n cycles)         |
 * | B       | B [s]                         | Activate all LEDs for specified seconds   |
 * | X       | X [on_ms] [off_ms] [n]        | Pulse train on all LEDs (n cycles)        |
 * | D       | D                             | Run demo sequence activating channels     |
 * | T       | T                             | Output module capabilities in JSON        |
 * | H       | H                             | Display help/menu information             |
 * +---------+-------------------------------+-------------------------------------------+
 *
 * Command Details:
 *
 * 1. Pulse Single Channel:
 *    - Command: `P [channel] [duration_ms]`
 *    - Example: `P 5 1000` activates channel 5 for 1000 milliseconds.
 *
 * 2. Activate All Motors:
 *    - Command: `A [duration_s]`
 *    - Example: `A 5` activates all motors for 5 seconds.
 *
 * 3. Pulse Train (single channel):
 *    - Command: `W [channel] [on_ms] [off_ms] [cycles]`
 *    - Example: `W 4 100 900 30` channel 4 pulses 30 times (100ms on, 900ms off).
 *    - Useful for pulsed optogenetic protocols to avoid depolarization block.
 *
 * 4. Activate All LEDs:
 *    - Command: `B [duration_s]`
 *    - Example: `B 3` activates all LEDs for 3 seconds.
 *
 * 5. Pulse Train All LEDs:
 *    - Command: `X [on_ms] [off_ms] [cycles]`
 *    - Example: `X 100 900 10` all LEDs pulse 10 times (100ms on, 900ms off).
 *
 * 6. Demo Mode:
 *    - Command: `D`
 *    - Description: Sequentially activates all available channels with predefined durations.
 *
 * 7. Teach Command:
 *    - Command: `T`
 *    - Description: Outputs module capabilities in JSON format for dynamic learning.
 *
 * 8. Help Menu:
 *    - Command: `H`
 *    - Description: Displays a list of available commands and their formats.
 *
 * Safety Features:
 *   - Non-blocking operations using millis() to allow concurrent command processing.
 *   - Input validation to prevent invalid channel numbers and durations.
 *   - Emergency shutdown function to deactivate all channels in case of overload.
 *   - Current monitoring (implementation placeholder) for advanced protection.
 *
 * Revision History:
 *   v1.3 (2026-02-27) - Added MODULE 3/4 for optogenetic LEDs, pulse train support.
 *   v2.1 (2023-08-20) - Added module flexibility, non-blocking activation, input validation.
 *   v2.0 (2023-07-15) - Implemented activate all motors feature with non-blocking timing.
 *   v1.1 (2020-07-08) - Original implementation with basic serial commands.
 *
 * Connections:
 *   - Motors: Connected to channels 0-9 via Darlington arrays.
 *   - Valves: Connected to channels 10-19 via Darlington arrays (if applicable).
 *   - LEDs: Connected via Darlington arrays with current-limiting resistors.
 *   - Serial Communication: USB connection to host computer/controller.
 *   - Power:
 *     * Motors and valves should have a common ground with the Arduino.
 *     * Use appropriate wiring (e.g., 16-14 AWG) for power distribution.
 *     * Consider separate power supplies for motors/valves and Arduino for stability.
 *
 * Troubleshooting:
 *   Q: Channels not activating.
 *   A:
 *      1. Verify power supply connections and ratings.
 *      2. Ensure PCBVERSION and MODULE are correctly defined.
 *      3. Check Darlington array orientation and connections.
 *      4. Confirm serial communication settings.
 *
 *   Q: Random or unintended activations.
 *   A:
 *      1. Inspect for ground loops or electrical noise.
 *      2. Check serial cable integrity and shielding.
 *      3. Ensure appropriate current limiting and protection.
 *
 * License:
 *   MIT Open Source License
 *
 * Author:
 *   Giorgio Gilestro <giorgio@gilest.ro>
 *
 * Repository:
 *   https://github.com/gilestrolab/ethoscope
 * =============================================================================
 */

// =============================================================================
// Version and Configuration
// =============================================================================
const float VERSION = 1.3;
#define PCBVERSION 10    // PCB Version: 10 for v1.0, 11 for v1.1
#define MODULE 0         // Module Type: 0=SD, 1=AGOSD, 2=AGO, 3=mAGOLED, 4=LED

// =============================================================================
// Module-Specific Definitions
// =============================================================================
#if (MODULE == 0)
    #define MODULE_NAME "N20 Sleep Deprivation Module"
    #define MODULE_DESC "Rotates up to twenty N20 geared motors independently"
    #define MOTOR_COUNT 10
    #define VALVE_COUNT 0
    #define LED_COUNT 0
#elif (MODULE == 1)
    #define MODULE_NAME "AGOSD Sleep Deprivation and Odour Arousal Module"
    #define MODULE_DESC "Operates ten N20 geared motors and ten solenoid valves independently"
    #define MOTOR_COUNT 10
    #define VALVE_COUNT 10
    #define LED_COUNT 0
#elif (MODULE == 2)
    #define MODULE_NAME "AGO Odour Arousal Module"
    #define MODULE_DESC "Operates ten solenoid valves independently"
    #define MOTOR_COUNT 0
    #define VALVE_COUNT 10
    #define LED_COUNT 0
#elif (MODULE == 3)
    #define MODULE_NAME "mAGOLED Motor and Optogenetic LED Module"
    #define MODULE_DESC "Operates ten N20 geared motors and ten LEDs independently"
    #define MOTOR_COUNT 10
    #define VALVE_COUNT 0
    #define LED_COUNT 10
#elif (MODULE == 4)
    #define MODULE_NAME "LED Optogenetic Module"
    #define MODULE_DESC "Operates twenty LEDs independently"
    #define MOTOR_COUNT 0
    #define VALVE_COUNT 0
    #define LED_COUNT 20
#else
    #error "Invalid MODULE type defined. Set MODULE to 0, 1, 2, 3, or 4."
#endif

// =============================================================================
// Libraries and Global Variables
// =============================================================================
// Requires Arduino-SerialCommand library: https://github.com/shyd/Arduino-SerialCommand
// Install via Arduino Library Manager or clone into your Arduino/libraries folder.
#include <SerialCommand.h>
SerialCommand SCmd;

#define BAUD 115200  // Fixed baud rate as per requirements
#define ACTIVATION_DELAY 250 // activation delay to avoid drawing current all at once

// =============================================================================
// Pin Configuration based on PCB Version
// =============================================================================
#if (PCBVERSION == 10) // PCB Version 1.0
    static const uint8_t pins[] = {1, 0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, A0, A1, A2, A3, A4, A5};
#elif (PCBVERSION == 11) // PCB Version 1.1
    static const uint8_t pins[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, A0, A1, A2, A3, A4, A5};
#else
    #error "Invalid PCBVERSION defined. Use 10 for v1.0 or 11 for v1.1."
#endif

// Channel mapping arrays — sized at compile time per module
#if MOTOR_COUNT > 0
    uint8_t MOTOR_CHANNELS[MOTOR_COUNT];
#endif
#if VALVE_COUNT > 0
    uint8_t VALVE_CHANNELS[VALVE_COUNT];
#endif
#if LED_COUNT > 0
    uint8_t LED_CHANNELS[LED_COUNT];
#endif

const uint8_t NUM_ACTUATORS = MOTOR_COUNT + VALVE_COUNT + LED_COUNT;
const uint8_t TOTAL_CHANNELS = 20; // Always 20 physical channels (pins 0-19)

// =============================================================================
// Structures for Channel State Management
// =============================================================================
struct ChannelState {
    uint8_t physicalPin;
    unsigned long endTime;       // Timestamp when to deactivate (simple pulse)
    #if LED_COUNT > 0
    // Pulse train fields — only compiled for LED-capable modules to save RAM
    unsigned long pulseOnTime;   // Duration of ON phase in ms
    unsigned long pulseOffTime;  // Duration of OFF phase in ms
    unsigned long nextToggle;    // When to toggle next
    uint16_t cyclesRemaining;    // Remaining cycles (0 = inactive pulse train)
    bool pulseState;             // Current state in pulse train (true=ON)
    #endif
};

ChannelState activeChannels[20] = {0}; // Initialize all channels to inactive

// Variables for "Activate All Motors" command
unsigned long allMotorsEndTime = 0;
bool motorsActive = false;

// Variables for "Activate All LEDs" command
#if LED_COUNT > 0
    unsigned long allLedsEndTime = 0;
    bool ledsActive = false;
#endif

// =============================================================================
// Function Prototypes
// =============================================================================
void control();              // Handles 'P' command
void demo();                 // Handles 'D' command
void helpMenu();             // Handles 'H' command
void teach();                // Handles 'T' command
void activateAllMotors();    // Handles 'A' command
void pulseTrain();           // Handles 'W' command
void activateAllLeds();      // Handles 'B' command
void pulseTrainAllLeds();    // Handles 'X' command
void activate(uint8_t channel, unsigned long duration);
void updateChannels();       // Updates active channels based on time
void updateAllMotors();      // Updates the state of all motors
void updateAllLeds();        // Updates the state of all LEDs
void updatePulseTrains();    // Updates pulse train states
void emergencyShutdown();    // Emergency shutdown procedure

// =============================================================================
// Setup Function
// =============================================================================
void setup() {
    // Initialize serial communication
    Serial.begin(BAUD);

    // Initialize channel mappings based on module type
    #if (MODULE == 0)
        // SD: Motors on odd channels (1,3,5,...19)
        for(int i = 0; i < MOTOR_COUNT; i++) MOTOR_CHANNELS[i] = 2*i + 1;
    #elif (MODULE == 1)
        // AGOSD: Motors on odd channels, valves on even channels
        for(int i = 0; i < MOTOR_COUNT; i++) MOTOR_CHANNELS[i] = 2*i + 1;
        for(int i = 0; i < VALVE_COUNT; i++) VALVE_CHANNELS[i] = 2*i;
    #elif (MODULE == 2)
        // AGO: Valves on even channels (0,2,4,...18)
        for(int i = 0; i < VALVE_COUNT; i++) VALVE_CHANNELS[i] = 2*i;
    #elif (MODULE == 3)
        // mAGOLED: Motors on odd channels, LEDs on even channels
        for(int i = 0; i < MOTOR_COUNT; i++) MOTOR_CHANNELS[i] = 2*i + 1;
        for(int i = 0; i < LED_COUNT; i++) LED_CHANNELS[i] = 2*i;
    #elif (MODULE == 4)
        // LED: All 20 channels are LEDs (0-19)
        for(int i = 0; i < LED_COUNT; i++) LED_CHANNELS[i] = i;
    #endif

    // Initialize all channels as OUTPUT and set them LOW
    for (uint8_t i = 0; i < 20; i++) {
        pinMode(pins[i], OUTPUT);
        digitalWrite(pins[i], LOW);
    }

    // Register serial commands
    SCmd.addCommand("P", control);     // Pulse single channel
    SCmd.addCommand("D", demo);        // Demo mode
    SCmd.addCommand("T", teach);       // Teach command
    SCmd.addCommand("H", helpMenu);    // Help menu

    #if MOTOR_COUNT > 0
        SCmd.addCommand("A", activateAllMotors);
    #endif

    #if LED_COUNT > 0
        SCmd.addCommand("W", pulseTrain);        // Pulse train single channel
        SCmd.addCommand("B", activateAllLeds);    // Activate all LEDs
        SCmd.addCommand("X", pulseTrainAllLeds);  // Pulse train all LEDs
    #endif
}

// =============================================================================
// Main Loop
// =============================================================================
void loop() {
    SCmd.readSerial();       // Process incoming serial commands
    updateChannels();        // Handle individual channel deactivations
    updateAllMotors();       // Handle "Activate All Motors" deactivation
    updatePulseTrains();     // Handle pulse train toggling
    #if LED_COUNT > 0
        updateAllLeds();     // Handle "Activate All LEDs" deactivation
    #endif
    delay(50);               // Short delay to prevent overwhelming the loop
}

// =============================================================================
// Command Handlers
// =============================================================================

// Handles 'P' command to pulse a single channel
void control() {
    char *arg1 = SCmd.next(); // Channel number
    char *arg2 = SCmd.next(); // Duration in ms

    if (!arg1 || !arg2) {
        Serial.println(F("ERROR: P requires: P [channel 0-19] [ms]"));
        return;
    }

    int channel = atoi(arg1);
    int duration = atoi(arg2);

    // Input validation
    if (channel < 0 || channel >= TOTAL_CHANNELS) {
        Serial.print(F("ERROR: Channel must be 0-"));
        Serial.println(TOTAL_CHANNELS - 1);
        return;
    }
    if (duration <= 0) {
        Serial.println(F("ERROR: Duration must be positive."));
        return;
    }

    // Activate the specified channel
    activate(channel, duration);
}

// Handles 'A' command to activate all motors
void activateAllMotors() {
    #if (MOTOR_COUNT > 0)
        char *arg = SCmd.next(); // Duration in seconds

        if (!arg) {
            Serial.println(F("ERROR: A requires: A [duration_s]"));
            return;
        }

        int duration_s = atoi(arg);

        // Input validation
        if (duration_s <= 0) {
            Serial.println(F("ERROR: Duration must be positive."));
            return;
        }

        // Set the end time for deactivation
        allMotorsEndTime = ((unsigned long)duration_s * 1000) + millis();

        // Activate all motors with staggered start
        for(uint8_t i = 0; i < MOTOR_COUNT; i++) {
            digitalWrite(pins[MOTOR_CHANNELS[i]], HIGH);
            delay(ACTIVATION_DELAY);
        }

        motorsActive = true;

        Serial.print(F("All motors ON for "));
        Serial.print(duration_s);
        Serial.println(F("s."));

    #else
        Serial.println(F("ERROR: No motors in this module."));
    #endif
}

// Handles 'W' command for pulse train on a single channel
void pulseTrain() {
    #if LED_COUNT > 0
    char *arg1 = SCmd.next(); // Channel
    char *arg2 = SCmd.next(); // ON duration in ms
    char *arg3 = SCmd.next(); // OFF duration in ms
    char *arg4 = SCmd.next(); // Number of cycles

    if (!arg1 || !arg2 || !arg3 || !arg4) {
        Serial.println(F("ERROR: W requires: W [ch] [on_ms] [off_ms] [cycles]"));
        return;
    }

    int channel = atoi(arg1);
    int onTime = atoi(arg2);
    int offTime = atoi(arg3);
    int cycles = atoi(arg4);

    // Input validation
    if (channel < 0 || channel >= TOTAL_CHANNELS) {
        Serial.print(F("ERROR: Channel must be 0-"));
        Serial.println(TOTAL_CHANNELS - 1);
        return;
    }
    if (onTime <= 0 || offTime <= 0) {
        Serial.println(F("ERROR: ON/OFF durations must be positive."));
        return;
    }
    if (cycles <= 0) {
        Serial.println(F("ERROR: Cycle count must be positive."));
        return;
    }

    // Cancel any existing simple pulse on this channel
    activeChannels[channel].endTime = 0;

    // Set up pulse train
    activeChannels[channel].physicalPin = pins[channel];
    activeChannels[channel].pulseOnTime = (unsigned long)onTime;
    activeChannels[channel].pulseOffTime = (unsigned long)offTime;
    activeChannels[channel].cyclesRemaining = (uint16_t)cycles;
    activeChannels[channel].pulseState = true;
    activeChannels[channel].nextToggle = millis() + (unsigned long)onTime;

    // Start first ON phase
    digitalWrite(pins[channel], HIGH);

    Serial.print(F("Pulse ch"));
    Serial.print(channel);
    Serial.print(F(": "));
    Serial.print(onTime);
    Serial.print(F("/"));
    Serial.print(offTime);
    Serial.print(F("ms x"));
    Serial.println(cycles);
    #else
    Serial.println(F("ERROR: Pulse train not available."));
    #endif
}

// Handles 'B' command to activate all LEDs
void activateAllLeds() {
    #if (LED_COUNT > 0)
        char *arg = SCmd.next(); // Duration in seconds

        if (!arg) {
            Serial.println(F("ERROR: B requires: B [duration_s]"));
            return;
        }

        int duration_s = atoi(arg);

        if (duration_s <= 0) {
            Serial.println(F("ERROR: Duration must be positive."));
            return;
        }

        allLedsEndTime = ((unsigned long)duration_s * 1000) + millis();

        for(uint8_t i = 0; i < LED_COUNT; i++) {
            digitalWrite(pins[LED_CHANNELS[i]], HIGH);
        }

        ledsActive = true;

        Serial.print(F("All LEDs ON for "));
        Serial.print(duration_s);
        Serial.println(F("s."));

    #else
        Serial.println(F("ERROR: No LEDs in this module."));
    #endif
}

// Handles 'X' command for pulse train on all LEDs
void pulseTrainAllLeds() {
    #if (LED_COUNT > 0)
        char *arg1 = SCmd.next(); // ON duration in ms
        char *arg2 = SCmd.next(); // OFF duration in ms
        char *arg3 = SCmd.next(); // Number of cycles

        if (!arg1 || !arg2 || !arg3) {
            Serial.println(F("ERROR: X requires: X [on_ms] [off_ms] [cycles]"));
            return;
        }

        int onTime = atoi(arg1);
        int offTime = atoi(arg2);
        int cycles = atoi(arg3);

        if (onTime <= 0 || offTime <= 0) {
            Serial.println(F("ERROR: ON/OFF durations must be positive."));
            return;
        }
        if (cycles <= 0) {
            Serial.println(F("ERROR: Cycle count must be positive."));
            return;
        }

        unsigned long now = millis();

        for(uint8_t i = 0; i < LED_COUNT; i++) {
            uint8_t ch = LED_CHANNELS[i];
            activeChannels[ch].endTime = 0; // Cancel any simple pulse
            activeChannels[ch].physicalPin = pins[ch];
            activeChannels[ch].pulseOnTime = (unsigned long)onTime;
            activeChannels[ch].pulseOffTime = (unsigned long)offTime;
            activeChannels[ch].cyclesRemaining = (uint16_t)cycles;
            activeChannels[ch].pulseState = true;
            activeChannels[ch].nextToggle = now + (unsigned long)onTime;
            digitalWrite(pins[ch], HIGH);
        }

        Serial.print(F("All LEDs pulse: "));
        Serial.print(onTime);
        Serial.print(F("/"));
        Serial.print(offTime);
        Serial.print(F("ms x"));
        Serial.println(cycles);

    #else
        Serial.println(F("ERROR: No LEDs in this module."));
    #endif
}

// Handles 'D' command to run demo sequence
void demo() {
    Serial.println(F("Running demo..."));
    #if (MODULE == 0)
        // N20 Module: Activate motors sequentially
        for(uint8_t i = 0; i < MOTOR_COUNT; i++) {
            activate(MOTOR_CHANNELS[i], 500);
            unsigned long start = millis();
            while(millis() - start < 600) {
                SCmd.readSerial();
                updateChannels();
                delay(50);
            }
        }
    #elif (MODULE == 1)
        // AGOSD Module: Motors first then valves
        for(uint8_t i = 0; i < MOTOR_COUNT; i++) {
            activate(MOTOR_CHANNELS[i], 500);
            unsigned long start = millis();
            while(millis() - start < 600) {
                SCmd.readSerial();
                updateChannels();
                delay(50);
            }
        }
        for(uint8_t i = 0; i < VALVE_COUNT; i++) {
            activate(VALVE_CHANNELS[i], 500);
            unsigned long start = millis();
            while(millis() - start < 600) {
                SCmd.readSerial();
                updateChannels();
                delay(50);
            }
        }
    #elif (MODULE == 2)
        // AGO Module: Activate valves sequentially
        for(uint8_t i = 0; i < VALVE_COUNT; i++) {
            activate(VALVE_CHANNELS[i], 200);
            unsigned long start = millis();
            while(millis() - start < 300) {
                SCmd.readSerial();
                updateChannels();
                delay(50);
            }
        }
    #elif (MODULE == 3)
        // mAGOLED Module: Motors first then LEDs
        for(uint8_t i = 0; i < MOTOR_COUNT; i++) {
            activate(MOTOR_CHANNELS[i], 500);
            unsigned long start = millis();
            while(millis() - start < 600) {
                SCmd.readSerial();
                updateChannels();
                delay(50);
            }
        }
        for(uint8_t i = 0; i < LED_COUNT; i++) {
            activate(LED_CHANNELS[i], 300);
            unsigned long start = millis();
            while(millis() - start < 400) {
                SCmd.readSerial();
                updateChannels();
                delay(50);
            }
        }
    #elif (MODULE == 4)
        // LED Module: Activate LEDs sequentially
        for(uint8_t i = 0; i < LED_COUNT; i++) {
            activate(LED_CHANNELS[i], 300);
            unsigned long start = millis();
            while(millis() - start < 400) {
                SCmd.readSerial();
                updateChannels();
                delay(50);
            }
        }
    #endif
    Serial.println(F("Demo completed."));
}

// Handles 'T' command to output module capabilities in JSON
void teach() {
    Serial.print(F("{\"version\":\"FW-"));
    Serial.print(VERSION);
    Serial.print(F(";HW-"));
    Serial.print(PCBVERSION);
    Serial.print(F("\",\"module\":{\"name\":\""));
    Serial.print(F(MODULE_NAME));
    Serial.print(F("\",\"description\":\""));
    Serial.print(F(MODULE_DESC));
    Serial.print(F("\",\"type\":"));
    Serial.print(MODULE);
    Serial.print(F("},\"capabilities\":{\"motors\":"));
    Serial.print(MOTOR_COUNT);
    Serial.print(F(",\"valves\":"));
    Serial.print(VALVE_COUNT);
    Serial.print(F(",\"leds\":"));
    Serial.print(LED_COUNT);
    Serial.print(F(",\"total_channels\":"));
    Serial.print(TOTAL_CHANNELS);
    Serial.print(F(",\"num_actuators\":"));
    Serial.print(NUM_ACTUATORS);
    Serial.print(F("},\"interface\":{\"test_button\":{\"title\":\"Test Output\",\"description\":\"Run demonstration sequence\",\"command\":\"D\"},\"commands\":["));
    Serial.print(F("{\"name\":\"Pulse\",\"format\":\"P [channel] [ms]\",\"description\":\"Activate single channel\",\"args\":[{\"name\":\"channel\",\"range\":\"0-"));
    Serial.print(TOTAL_CHANNELS-1);
    Serial.print(F("\"},{\"name\":\"duration\",\"unit\":\"ms\"}]}"));
    #if MOTOR_COUNT > 0
        Serial.print(F(",{\"name\":\"Activate All Motors\",\"format\":\"A [s]\",\"description\":\"Activate all motors\",\"args\":[{\"name\":\"duration\",\"unit\":\"s\"}]}"));
    #endif
    #if LED_COUNT > 0
        Serial.print(F(",{\"name\":\"Pulse Train\",\"format\":\"W [ch] [on_ms] [off_ms] [n]\",\"description\":\"Pulse train on single channel\",\"args\":[{\"name\":\"channel\",\"range\":\"0-"));
        Serial.print(TOTAL_CHANNELS-1);
        Serial.print(F("\"},{\"name\":\"on_ms\",\"unit\":\"ms\"},{\"name\":\"off_ms\",\"unit\":\"ms\"},{\"name\":\"cycles\",\"unit\":\"count\"}]}"));
        Serial.print(F(",{\"name\":\"Activate All LEDs\",\"format\":\"B [s]\",\"description\":\"Activate all LEDs\",\"args\":[{\"name\":\"duration\",\"unit\":\"s\"}]}"));
        Serial.print(F(",{\"name\":\"Pulse Train All LEDs\",\"format\":\"X [on_ms] [off_ms] [n]\",\"description\":\"Pulse train on all LEDs\",\"args\":[{\"name\":\"on_ms\",\"unit\":\"ms\"},{\"name\":\"off_ms\",\"unit\":\"ms\"},{\"name\":\"cycles\",\"unit\":\"count\"}]}"));
    #endif
    Serial.print(F(",{\"name\":\"Demo\",\"format\":\"D\",\"description\":\"Run test sequence\"}"));
    Serial.print(F(",{\"name\":\"Help\",\"format\":\"H\",\"description\":\"Show commands\"}"));
    Serial.println(F("]}}"));
}

// Handles 'H' command to display help menu
void helpMenu(){
    Serial.println(F("=== Command Reference ==="));
    Serial.println(F("P [0-19] [ms]              - Pulse single channel. Example: P 5 1000"));

    #if (MOTOR_COUNT > 0)
        Serial.println(F("A [s]                      - Activate all motors. Example: A 5"));
    #endif

    #if (LED_COUNT > 0)
        Serial.println(F("W [ch] [on] [off] [n]      - Pulse train. Example: W 4 100 900 30"));
        Serial.println(F("B [s]                      - All LEDs on. Example: B 3"));
        Serial.println(F("X [on] [off] [n]           - Pulse all LEDs. Example: X 100 900 10"));
    #endif

    Serial.println(F("D                          - Run demo sequence."));
    Serial.println(F("T                          - Output JSON capabilities."));
    Serial.println(F("H                          - Display this help menu."));
    Serial.println(F("========================="));
}

// =============================================================================
// Core Functionality
// =============================================================================

// Activates a single channel for a specified duration (non-blocking)
void activate(uint8_t channel, unsigned long duration) {
    #if LED_COUNT > 0
    // Cancel any active pulse train on this channel
    activeChannels[channel].cyclesRemaining = 0;
    #endif

    // Activate the channel
    digitalWrite(pins[channel], HIGH);

    // Set the end time for deactivation
    activeChannels[channel].physicalPin = pins[channel];
    activeChannels[channel].endTime = millis() + duration;

    Serial.print(F("Ch"));
    Serial.print(channel);
    Serial.print(F(" ON "));
    Serial.print(duration);
    Serial.println(F("ms."));
}

// Updates channels to deactivate them when their time has elapsed
void updateChannels() {
    unsigned long currentTime = millis();

    for (uint8_t i = 0; i < TOTAL_CHANNELS; i++) {
        if (activeChannels[i].endTime > 0 && currentTime >= activeChannels[i].endTime) {
            digitalWrite(activeChannels[i].physicalPin, LOW);
            activeChannels[i].endTime = 0;
            Serial.print(F("Ch"));
            Serial.print(i);
            Serial.println(F(" OFF."));
        }
    }
}

// Updates pulse train states — toggles channels on/off according to their schedule
void updatePulseTrains() {
    #if LED_COUNT > 0
    unsigned long currentTime = millis();

    for (uint8_t i = 0; i < TOTAL_CHANNELS; i++) {
        if (activeChannels[i].cyclesRemaining == 0) continue;
        if (currentTime < activeChannels[i].nextToggle) continue;

        if (activeChannels[i].pulseState) {
            // Was ON, transition to OFF
            digitalWrite(activeChannels[i].physicalPin, LOW);
            activeChannels[i].pulseState = false;
            activeChannels[i].nextToggle = currentTime + activeChannels[i].pulseOffTime;
        } else {
            // Was OFF, one full cycle completed
            activeChannels[i].cyclesRemaining--;

            if (activeChannels[i].cyclesRemaining == 0) {
                // Pulse train complete — ensure channel is off
                digitalWrite(activeChannels[i].physicalPin, LOW);
                Serial.print(F("Pulse ch"));
                Serial.print(i);
                Serial.println(F(" done."));
            } else {
                // Start next ON phase
                digitalWrite(activeChannels[i].physicalPin, HIGH);
                activeChannels[i].pulseState = true;
                activeChannels[i].nextToggle = currentTime + activeChannels[i].pulseOnTime;
            }
        }
    }
    #endif
}

// Updates the state of all motors for "Activate All" command
void updateAllMotors() {
    #if MOTOR_COUNT > 0
    if(motorsActive && millis() >= allMotorsEndTime) {
        for(uint8_t i = 0; i < MOTOR_COUNT; i++) {
            digitalWrite(pins[MOTOR_CHANNELS[i]], LOW);
            delay(ACTIVATION_DELAY);
        }
        motorsActive = false;
        Serial.println(F("All motors OFF."));
    }
    #endif
}

// Updates the state of all LEDs for "Activate All LEDs" command
void updateAllLeds() {
    #if LED_COUNT > 0
    if(ledsActive && millis() >= allLedsEndTime) {
        for(uint8_t i = 0; i < LED_COUNT; i++) {
            digitalWrite(pins[LED_CHANNELS[i]], LOW);
        }
        ledsActive = false;
        Serial.println(F("All LEDs OFF."));
    }
    #endif
}

// Emergency shutdown: Deactivate all channels immediately
void emergencyShutdown() {
    #if MOTOR_COUNT > 0
        for(uint8_t i = 0; i < MOTOR_COUNT; i++) digitalWrite(pins[MOTOR_CHANNELS[i]], LOW);
    #endif
    #if VALVE_COUNT > 0
        for(uint8_t i = 0; i < VALVE_COUNT; i++) digitalWrite(pins[VALVE_CHANNELS[i]], LOW);
    #endif
    #if LED_COUNT > 0
        for(uint8_t i = 0; i < LED_COUNT; i++) digitalWrite(pins[LED_CHANNELS[i]], LOW);
        ledsActive = false;
    #endif
    memset(activeChannels, 0, sizeof(activeChannels));
    motorsActive = false;
    Serial.println(F("EMERGENCY: All outputs disabled."));
}

// =============================================================================
// (Optional) Current Monitoring and Safety Implementation
// =============================================================================
// Placeholder for integrating current monitoring hardware (e.g., ACS712 sensor)
// Uncomment and modify the following code as needed based on your hardware setup

/*
const int CURRENT_SENSE_PIN = A6;      // Analog pin connected to current sensor
const float CURRENT_THRESHOLD = 7000;  // Maximum allowed current in mA (7A)

void setup() {
    // Existing setup code...
    pinMode(CURRENT_SENSE_PIN, INPUT);
}

void loop() {
    // Existing loop code...
    checkCurrent();
}

void checkCurrent() {
    int sensorValue = analogRead(CURRENT_SENSE_PIN);
    float voltage = sensorValue * (5.0 / 1023.0); // Assuming 5V reference
    float current = voltage * (1000.0 / 66.0);    // For ACS712-30A (66mV/A)

    if (current > CURRENT_THRESHOLD) {
        emergencyShutdown();
    }
}
*/

// =============================================================================
// End of Sketch
// =============================================================================
