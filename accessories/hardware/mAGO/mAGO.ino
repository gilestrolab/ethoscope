/* =============================================================================
 * ARDUINO MOTOR/VALVE CONTROL MODULE
 * =============================================================================
 * 
 * Purpose:
 *   Controls motors and solenoid valves using Darlington arrays via serial commands.
 *   Supports multiple module configurations for flexible use cases.
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
 * Hardware Configuration:
 *   - PCB Version: Defined by PCBVERSION (10 for v1.0, 11 for v1.1)
 *   - Module Type: Defined by MODULE (0, 1, or 2)
 *   - Microcontroller: Arduino Micro
 *   - Power Requirements:
 *     * Motors: 6-12V DC (according to N20 motor specifications)
 *     * Solenoids: As per valve specifications
 *     * Current Budget:
 *         - Motors: Max 10×500mA = 5A
 *         - Solenoids: As per usage (not activated unless commanded)
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
 * +---------+-------------------------+------------------------------------------+
 * | Command | Format                  | Description                              |
 * +---------+-------------------------+------------------------------------------+
 * | P       | P [0-19] [ms]           | Pulse single channel for specified ms    |
 * | A       | A [s]                   | Activate all motors (0-9) for specified s |
 * | D       | D                       | Run demo sequence activating channels    |
 * | T       | T                       | Output module capabilities in JSON       |
 * | H       | H                       | Display help/menu information            |
 * +---------+-------------------------+------------------------------------------+
 * 
 * Command Details:
 * 
 * 1. Pulse Single Channel:
 *    - Command: `P [channel] [duration_ms]`
 *    - Example: `P 5 1000` activates channel 5 for 1000 milliseconds.
 * 
 * 2. Activate All Motors:
 *    - Command: `A [duration_ms]`
 *    - Example: `A 5000` activates all motors (channels 0-9) for 5000 seconds.
 * 
 * 3. Demo Mode:
 *    - Command: `D`
 *    - Description: Sequentially activates all available channels with predefined durations.
 * 
 * 4. Teach Command:
 *    - Command: `T`
 *    - Description: Outputs module capabilities in JSON format for dynamic learning.
 * 
 * 5. Help Menu:
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
 *   v2.1 (2023-08-20) - Added module flexibility, non-blocking activation, input validation.
 *   v2.0 (2023-07-15) - Implemented activate all motors feature with non-blocking timing.
 *   v1.1 (2020-07-08) - Original implementation with basic serial commands.
 * 
 * Connections:
 *   - Motors: Connected to channels 0-9 via Darlington arrays.
 *   - Valves: Connected to channels 10-19 via Darlington arrays (if applicable).
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
const float VERSION = 1.2;
#define PCBVERSION 11    // PCB Version: 10 for v1.0, 11 for v1.1
#define MODULE 1         // Module Type: 0=SD, 1=AGOSD, 2=AGO

// =============================================================================
// Module-Specific Definitions
// =============================================================================
#if (MODULE == 0)
    #define MODULE_NAME "N20 Sleep Deprivation Module"
    #define MODULE_DESC "Rotates up to twenty N20 geared motors independently"
    #define MOTOR_COUNT 10
    #define VALVE_COUNT 0
#elif (MODULE == 1)
    #define MODULE_NAME "AGOSD Sleep Deprivation and Odour Arousal Module"
    #define MODULE_DESC "Operates ten N20 geared motors and ten solenoid valves independently"
    #define MOTOR_COUNT 10
    #define VALVE_COUNT 10
#elif (MODULE == 2)
    #define MODULE_NAME "AGO Odour Arousal Module"
    #define MODULE_DESC "Operates ten solenoid valves independently"
    #define MOTOR_COUNT 0
    #define VALVE_COUNT 10
#else
    #error "Invalid MODULE type defined. Set MODULE to 0, 1, or 2."
#endif

// =============================================================================
// Libraries and Global Variables
// =============================================================================
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

uint8_t MOTOR_CHANNELS[MOTOR_COUNT];
uint8_t VALVE_CHANNELS[VALVE_COUNT];
const uint8_t TOTAL_CHANNELS = MOTOR_COUNT + VALVE_COUNT; // Total active channels based on module


// =============================================================================
// Structures for Channel State Management
// =============================================================================
struct ChannelState {
    uint8_t physicalPin;
    unsigned long endTime; // Timestamp when to deactivate
};

ChannelState activeChannels[20] = {0}; // Initialize all channels to inactive

// Variables for "Activate All" command
unsigned long allMotorsEndTime = 0; // Timestamp to deactivate all motors
bool motorsActive = false;

// =============================================================================
// Function Prototypes
// =============================================================================
void control();             // Handles 'P' command
void demo();                // Handles 'D' command
void helpMenu();            // Handles 'H' command
void teach();               // Handles 'T' command
void activateAllMotors();   // Handles 'A' command
void activate(uint8_t channel, unsigned long duration); // Activates a single channel
void updateChannels();      // Updates active channels based on time
void updateAllMotors();    // Updates the state of all motors
void emergencyShutdown();  // Emergency shutdown procedure

// =============================================================================
// Setup Function
// =============================================================================
void setup() {
    // Initialize serial communication
    Serial.begin(BAUD);


    // Initialize motor/valve channel mappings
    for(int i=0; i<MOTOR_COUNT; i++) MOTOR_CHANNELS[i] = 2*i + 1;
    for(int i=0; i<VALVE_COUNT; i++) VALVE_CHANNELS[i] = 2*i;

    // Initialize all channels as OUTPUT and set them LOW
    for (uint8_t i = 0; i < TOTAL_CHANNELS; i++) {
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
    // Optional: Uncomment the following line to run demo on startup
    // demo();
}

// =============================================================================
// Main Loop
// =============================================================================
void loop() {
    SCmd.readSerial();      // Process incoming serial commands
    updateChannels();      // Handle individual channel deactivations
    updateAllMotors();    // Handle "Activate All" deactivation
    delay(50);             // Short delay to prevent overwhelming the loop
}

// =============================================================================
// Command Handlers
// =============================================================================

// Handles 'P' command to pulse a single channel
void control() {
    char *arg1 = SCmd.next(); // Channel number
    char *arg2 = SCmd.next(); // Duration in ms
    
    if (!arg1 || !arg2) {
        Serial.println("ERROR: P command requires two arguments: P [channel 0-19] [duration_ms]");
        return;
    }
    
    int channel = atoi(arg1);
    int duration = atoi(arg2);
    
    // Input validation
    if (channel < 0 || channel >= TOTAL_CHANNELS) {
        Serial.print("ERROR: Invalid channel number. Must be between 0 and ");
        Serial.println(TOTAL_CHANNELS - 1);
        return;
    }
    if (duration <= 0) {
        Serial.println("ERROR: Duration must be a positive integer.");
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
            Serial.println("ERROR: A command requires one argument: A [duration_ms]");
            return;
        }
        
        int durationMs = atoi(arg);
        
        // Input validation
        if (durationMs <= 0) {
            Serial.println("ERROR: Duration must be a positive integer greater than 0.");
            return;
        }

        // Set the end time for deactivation
        allMotorsEndTime = millis() + durationMs;

        // Activate all motors (odd channels for MODULE 1)
        for(uint8_t i=0; i<MOTOR_COUNT; i++) {
            digitalWrite(pins[MOTOR_CHANNELS[i]], HIGH);
            delay(ACTIVATION_DELAY); // we add a delay of 250ms to avoid all motors drawing current at once
        }

        motorsActive = true;
        
        Serial.print("All motors activated for ");
        Serial.print(durationMs);
        Serial.println(" milliseconds.");
    #else
        Serial.println("ERROR: No motors configured in this module.");
    #endif
}


// Handles 'D' command to run demo sequence
void demo() {
    Serial.println("Running demo...");
    #if (MODULE == 0)
        // N20 Module: Activate motors sequentially
        for(uint8_t i=0; i<MOTOR_COUNT; i++) {
            activate(MOTOR_CHANNELS[i], 500);
            unsigned long start = millis();
            while(millis() - start < 600) {  // 500ms active + 100ms delay
                SCmd.readSerial();
                updateChannels();
                delay(50);
            }
        }
    #elif (MODULE == 1)
        // AGOSD Module: Motors first then valves
        for(uint8_t i=0; i<MOTOR_COUNT; i++) {
            activate(MOTOR_CHANNELS[i], 500);
            unsigned long start = millis();
            while(millis() - start < 600) {  // 500ms active + 100ms delay
                SCmd.readSerial();
                updateChannels();
                delay(50);
            }
        }
        for(uint8_t i=0; i<VALVE_COUNT; i++) {
            activate(VALVE_CHANNELS[i], 500);
            unsigned long start = millis();
            while(millis() - start < 600) {  // 200ms active + 100ms delay
                SCmd.readSerial();
                updateChannels();
                delay(50);
            }
        }
    #elif (MODULE == 2)
        // AGO Module: Activate valves sequentially
        for(uint8_t i=0; i<VALVE_COUNT; i++) {
            activate(VALVE_CHANNELS[i], 200);
            unsigned long start = millis();
            while(millis() - start < 300) {  // 200ms active + 100ms delay
                SCmd.readSerial();
                updateChannels();
                delay(50);
            }
        }
    #endif
    Serial.println("Demo completed.");
}

// Handles 'T' command to output module capabilities
void teach() {
    Serial.print("{");
    Serial.print("\"version\":\"FW-");
    Serial.print(VERSION);
    Serial.print(";HW-");
    Serial.print(PCBVERSION);
    Serial.print("\",");
    Serial.print("\"module\":{");
    Serial.print("\"name\":\"");
    Serial.print(MODULE_NAME);
    Serial.print("\",\"description\":\"");
    Serial.print(MODULE_DESC);
    Serial.print("\",\"type\":");
    Serial.print(MODULE);
    Serial.print("},");
    Serial.print("\"capabilities\":{");
    Serial.print("\"motors\":");
    Serial.print(MOTOR_COUNT);
    Serial.print(",\"valves\":");
    Serial.print(VALVE_COUNT);
    Serial.print(",\"total_channels\":");
    Serial.print(TOTAL_CHANNELS);
    Serial.print("},");
    Serial.print("\"interface\":{");
    Serial.print("\"test_button\":{\"title\":\"Test Output\",\"description\":\"Run demonstration sequence\",\"command\":\"D\"},");
    Serial.print("\"commands\":[");
    Serial.print("{\"name\":\"Pulse\",\"format\":\"P [channel] [ms]\",\"description\":\"Activate single channel\",\"args\":[{\"name\":\"channel\",\"range\":\"0-");
    Serial.print(TOTAL_CHANNELS-1);
    Serial.print("\"},{\"name\":\"duration\",\"unit\":\"ms\"}]}");
    #if MOTOR_COUNT > 0
        Serial.print(",{\"name\":\"Activate All\",\"format\":\"A [ms]\",\"description\":\"Activate all motors\",\"args\":[{\"name\":\"duration\",\"unit\":\"ms\"}]}");
    #endif
    Serial.print(",{\"name\":\"Demo\",\"format\":\"D\",\"description\":\"Run test sequence\"}");
    Serial.print(",{\"name\":\"Help\",\"format\":\"H\",\"description\":\"Show commands\"}");
    Serial.print("]");  // Close commands array
    Serial.print("}");  // Close interface object
    Serial.println("}"); // Close root object
}

// Handles 'H' command to display help menu
void helpMenu(){
    Serial.println("=== Command Reference ===");
    Serial.println("P [0-19] [ms]  - Pulse single channel for specified milliseconds. Example: P 5 1000");
    
    #if (MOTOR_COUNT > 0)
        Serial.println("A [ms]         - Activate all motors for specified milliseconds. Example: A 5000");
    #endif
    
    Serial.println("D              - Run demo sequence activating all channels.");
    Serial.println("T              - Output module capabilities in JSON format.");
    Serial.println("H              - Display this help menu.");
    Serial.println("========================");
}

// =============================================================================
// Core Functionality
// =============================================================================

// Activates a single channel for a specified duration (non-blocking)
void activate(uint8_t channel, unsigned long duration) {
    // Activate the channel
    digitalWrite(pins[channel], HIGH);
    
    // Set the end time for deactivation
    activeChannels[channel].physicalPin = pins[channel];
    activeChannels[channel].endTime = millis() + duration;
    
    Serial.print("Channel ");
    Serial.print(channel);
    Serial.print(" activated for ");
    Serial.print(duration);
    Serial.println(" ms.");
}

// Updates channels to deactivate them when their time has elapsed
void updateChannels() {
    unsigned long currentTime = millis();
    
    for (uint8_t i = 0; i < TOTAL_CHANNELS; i++) {
        if (activeChannels[i].endTime > 0 && currentTime >= activeChannels[i].endTime) {
            digitalWrite(activeChannels[i].physicalPin, LOW); // Deactivate channel
            activeChannels[i].endTime = 0;                    // Reset end time
            Serial.print("Channel ");
            Serial.print(i);
            Serial.println(" deactivated.");
        }
    }
}

// Updates the state of all motors for "Activate All" command
void updateAllMotors() {
    if(motorsActive && millis() >= allMotorsEndTime) {
        for(uint8_t i=0; i<MOTOR_COUNT; i++) {
            digitalWrite(pins[MOTOR_CHANNELS[i]], LOW);
            delay(ACTIVATION_DELAY);
        }
        motorsActive = false;
        Serial.println("All motors deactivated.");
    }
}

// Emergency shutdown: Deactivate all channels immediately
void emergencyShutdown() {
    for(uint8_t i=0; i<MOTOR_COUNT; i++) digitalWrite(pins[MOTOR_CHANNELS[i]], LOW);
    for(uint8_t i=0; i<VALVE_COUNT; i++) digitalWrite(pins[VALVE_CHANNELS[i]], LOW);
    memset(activeChannels, 0, sizeof(activeChannels));
    motorsActive = false;
    Serial.println("EMERGENCY: All outputs disabled.");
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