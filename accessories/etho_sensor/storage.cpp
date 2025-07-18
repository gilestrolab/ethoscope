// storage.cpp
#include "storage.h"

// Initialize static members
#if defined(ESP8266)
    EEPROM_Rotate Storage::eeprom;
#elif defined(ESP32)
    Preferences Storage::preferences;
#endif

uint16_t calculateChecksum(const configuration& cfg) {
    uint16_t checksum = 0;
    const uint8_t* data = reinterpret_cast<const uint8_t*>(&cfg);
    const size_t size = sizeof(configuration);
    for (size_t i = 0; i < size; i++) {
        checksum += data[i];
    }
    return checksum;
}

bool Storage::initialized = false;
const char* Storage::NAMESPACE = "app";
StorageError Storage::lastError = StorageError::NONE;