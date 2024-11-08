#ifndef CONFIG_H
#define CONFIG_H

// Feature flags
#define USELIGHT
#define DEBUG_SERIAL

// Debug macros
#ifdef DEBUG_SERIAL
    #define DEBUG_PRINT(x) Serial.print(x)
    #define DEBUG_PRINTLN(x) Serial.println(x)
#else
    #define DEBUG_PRINT(x)
    #define DEBUG_PRINTLN(x)
#endif

// Constants
#define EEPROM_SIZE 4096
#define EEPROM_START 128
#define WATCHDOG_TIMEOUT 30
#define WIFI_CONNECT_TIMEOUT 30000
#define SENSOR_INIT_TIMEOUT 5000
#define SENSOR_READ_TIMEOUT 1000
#define CHECK_INTERVAL 1000

// Structures
typedef struct {
    float temperature;
    float humidity;
    float pressure;
    #if defined(USELIGHT)
        uint16_t lux;
    #endif
} environment;

typedef struct {
    char location[20];
    char name[20];
    char wifi_ssid[20];
    char wifi_pwd[20];
} configuration;

#endif
