#ifndef CONFIG_H
#define CONFIG_H

#include "structs.h"

// Feature flags
#define USELIGHT                //use the I2C Ligth sensor BH1750FVI
#define DEBUG_SERIAL            //use the serial port to send debug information
#define DEFAULT_NAME "etho_sensor_000"
#define WIFI_SSID "ETHOSCOPE_WIFI"
#define WIFI_PASSWORD "ETHOSCOPE_1234"
#define DEFAULT_LOCATION "n/a"

// Debug macros
#ifdef DEBUG_SERIAL
    #define DEBUG_PRINT(x) Serial.print(x)
    #define DEBUG_PRINTLN(x) Serial.println(x)
    #define DEBUG_PRINTF(x, y) Serial.print(x, y)  // For printing with format
#else
    #define DEBUG_PRINT(x)
    #define DEBUG_PRINTLN(x)
    #define DEBUG_PRINTF(x, y)
#endif

// Constants
#define WATCHDOG_TIMEOUT 30
#define WIFI_CONNECT_TIMEOUT 30000
#define SENSOR_INIT_TIMEOUT 5000
#define SENSOR_READ_TIMEOUT 1000

#define ARDUINOJSON_USE_LONG_LONG 0
#define ARDUINOJSON_USE_DOUBLE 0
#define ARDUINOJSON_ENABLE_STD_STRING 0
#define ARDUINOJSON_ENABLE_STD_STREAM 0
#define ASYNC_TCP_SSL_ENABLED 0
#define ESP8266_DISABLE_EXTRA_4K 1

// Buffer sizes for JSON and HTML responses
#define JSON_BUFFER_SIZE 384
#define HTML_BUFFER_SIZE 1024

// Buffer sizes for individual measurements
#define TEMP_BUFFER_SIZE 8    // "-123.45\0"
#define HUM_BUFFER_SIZE 7     // "100.00\0"
#define PRESS_BUFFER_SIZE 8   // "1234.56\0"
#define LUX_BUFFER_SIZE 6     // "99999\0"

#endif