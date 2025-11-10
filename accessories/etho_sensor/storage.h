// storage.h
#ifndef STORAGE_H
#define STORAGE_H

#include "config.h"

#if defined(ESP8266)
    #include <EEPROM_Rotate.h>
    #define EEPROM_SIZE 4096
    #define EEPROM_START 128

#elif defined(ESP32)
    #include <Preferences.h>
#endif

uint16_t calculateChecksum(const configuration& cfg);

enum class StorageError {
    NONE,
    NOT_INITIALIZED,
    WRITE_FAILED,
    READ_FAILED,
    VALIDATION_FAILED,
    COMMIT_FAILED,
    INVALID_FIELD
};

class Storage {
private:
    #if defined(ESP8266)
        static EEPROM_Rotate eeprom;
    #elif defined(ESP32)
        static Preferences preferences;
    #endif

    static bool initialized;
    static const char* NAMESPACE;
    static StorageError lastError;

public:
    static bool begin() {
        if (initialized) return true;

        #if defined(ESP8266)
            eeprom.begin(EEPROM_SIZE);
            initialized = true;
        #elif defined(ESP32)
            initialized = preferences.begin(NAMESPACE, false);
        #endif

        if (!initialized) {
            lastError = StorageError::NOT_INITIALIZED;
            return false;
        }

        lastError = StorageError::NONE;
        return true;
    }

static bool saveConfig(const configuration& cfg) {
    if (!initialized) {
        lastError = StorageError::NOT_INITIALIZED;
        return false;
    }

    configuration cfg_with_checksum = cfg;
    cfg_with_checksum.checksum = calculateChecksum(cfg);

    bool success = false;
    #if defined(ESP8266)
        // Write data
        eeprom.write(EEPROM_START, 1);  // validation marker
        eeprom.put(EEPROM_START + 1, cfg_with_checksum);

        // Commit changes
        if (!eeprom.commit()) {
            lastError = StorageError::COMMIT_FAILED;
            return false;
        }

        // Verify write
        configuration verify_cfg;
        uint8_t verify_marker = eeprom.read(EEPROM_START);
        eeprom.get(EEPROM_START + 1, verify_cfg);

        success = (verify_marker == 1) &&
                  (verify_cfg.checksum == cfg_with_checksum.checksum) &&
                  (strcmp(cfg.name, verify_cfg.name) == 0) &&
                  (strcmp(cfg.location, verify_cfg.location) == 0) &&
                  (strcmp(cfg.wifi_ssid, verify_cfg.wifi_ssid) == 0) &&
                  (strcmp(cfg.wifi_pwd, verify_cfg.wifi_pwd) == 0);

    #elif defined(ESP32)
        success = preferences.putString("name", cfg.name) &&
                  preferences.putString("location", cfg.location) &&
                  preferences.putString("wifi_ssid", cfg.wifi_ssid) &&
                  preferences.putString("wifi_pwd", cfg.wifi_pwd) &&
                  preferences.putUShort("checksum", cfg_with_checksum.checksum);
    #endif

    if (!success) {
        lastError = StorageError::WRITE_FAILED;
        return false;
    }

    lastError = StorageError::NONE;
    return true;
}

static bool loadConfig(configuration& cfg) {
    if (!initialized) {
        lastError = StorageError::NOT_INITIALIZED;
        return false;
    }

    bool success = false;
    #if defined(ESP8266)
        uint8_t valid = eeprom.read(EEPROM_START);
        if (valid != 1) {
            lastError = StorageError::VALIDATION_FAILED;
            return false;
        }
        eeprom.get(EEPROM_START + 1, cfg);

        uint16_t loaded_checksum = cfg.checksum;
        cfg.checksum = 0; // Reset the checksum field before calculating
        uint16_t calculated_checksum = calculateChecksum(cfg);

        if (loaded_checksum != calculated_checksum) {
            lastError = StorageError::VALIDATION_FAILED;
            return false;
        }

        success = true;

    #elif defined(ESP32)
        String name = preferences.getString("name", "");
        if (name.length() == 0) {
            lastError = StorageError::VALIDATION_FAILED;
            return false;
        }

        strlcpy(cfg.name, name.c_str(), sizeof(cfg.name));
        strlcpy(cfg.location, preferences.getString("location", "").c_str(), sizeof(cfg.location));
        strlcpy(cfg.wifi_ssid, preferences.getString("wifi_ssid", "").c_str(), sizeof(cfg.wifi_ssid));
        strlcpy(cfg.wifi_pwd, preferences.getString("wifi_pwd", "").c_str(), sizeof(cfg.wifi_pwd));
        cfg.checksum = preferences.getUShort("checksum", 0);

        uint16_t loaded_checksum = cfg.checksum;
        cfg.checksum = 0; // Reset the checksum field before calculating
        uint16_t calculated_checksum = calculateChecksum(cfg);

        if (loaded_checksum != calculated_checksum) {
            lastError = StorageError::VALIDATION_FAILED;
            return false;
        }

        success = true;
    #endif

    // Validate WiFi SSID and password
    if (strlen(cfg.wifi_ssid) == 0 || strlen(cfg.wifi_pwd) == 0) {
        lastError = StorageError::VALIDATION_FAILED;
        return false;
    }

    lastError = StorageError::NONE;
    return success;
}

    static bool updateField(const char* field, const char* value) {
        if (!initialized) {
            lastError = StorageError::NOT_INITIALIZED;
            return false;
        }

        bool success = false;
        #if defined(ESP8266)
            configuration cfg;
            if (!loadConfig(cfg)) {
                // lastError already set by loadConfig
                return false;
            }

            if (strcmp(field, "name") == 0)
                strlcpy(cfg.name, value, sizeof(cfg.name));
            else if (strcmp(field, "location") == 0)
                strlcpy(cfg.location, value, sizeof(cfg.location));
            else if (strcmp(field, "wifi_ssid") == 0)
                strlcpy(cfg.wifi_ssid, value, sizeof(cfg.wifi_ssid));
            else if (strcmp(field, "wifi_pwd") == 0)
                strlcpy(cfg.wifi_pwd, value, sizeof(cfg.wifi_pwd));
            else {
                lastError = StorageError::INVALID_FIELD;
                return false;
            }

            success = saveConfig(cfg);
        #elif defined(ESP32)
            success = preferences.putString(field, value);
            if (!success) {
                lastError = StorageError::WRITE_FAILED;
                return false;
            }
        #endif

        lastError = StorageError::NONE;
        return success;
    }

    static bool clear() {
        if (!initialized) {
            lastError = StorageError::NOT_INITIALIZED;
            return false;
        }

        #if defined(ESP8266)
            eeprom.write(EEPROM_START, 0);  // Clear validation marker
            return eeprom.commit();
        #elif defined(ESP32)
            return preferences.clear();
        #endif
    }

    static StorageError getLastError() {
        return lastError;
    }

    static const char* getErrorString(StorageError error) {
        switch (error) {
            case StorageError::NONE:
                return "No error";
            case StorageError::NOT_INITIALIZED:
                return "Storage not initialized";
            case StorageError::WRITE_FAILED:
                return "Write operation failed";
            case StorageError::READ_FAILED:
                return "Read operation failed";
            case StorageError::VALIDATION_FAILED:
                return "Validation failed";
            case StorageError::COMMIT_FAILED:
                return "Commit failed";
            case StorageError::INVALID_FIELD:
                return "Invalid field name";
            default:
                return "Unknown error";
        }
    }
};

#endif // STORAGE_H
