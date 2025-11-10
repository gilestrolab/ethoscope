#include <stdint.h>  // Add this for uint16_t and other integer types

typedef struct {
    char location[20];
    char name[20];
    char wifi_ssid[20];
    char wifi_pwd[20];
    uint16_t checksum; // Add a checksum field
} configuration;

typedef struct {
    float temperature;
    float humidity;
    float pressure;
    uint16_t lux;
} environment;
