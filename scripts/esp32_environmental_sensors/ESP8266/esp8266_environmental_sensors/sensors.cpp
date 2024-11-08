#include "sensors.h"

Adafruit_BME280 bme;
#if defined(USELIGHT)
    BH1750FVI LightSensor(BH1750FVI::k_DevModeContLowRes);
#endif

bool initializeSensors() {
    Wire.begin();
    Wire.setClockStretchLimit(2000);

    unsigned long timeout = millis();
    bool bmeInitialized = false;
    
    while (!bmeInitialized && (millis() - timeout < SENSOR_INIT_TIMEOUT)) {
        bmeInitialized = bme.begin(0x77);
        if (!bmeInitialized) delay(100);
    }
    
    if (!bmeInitialized) {
        DEBUG_PRINTLN("BME280 initialization failed!");
        return false;
    }
    
    #if defined(USELIGHT)
        if (!LightSensor.begin()) {
            DEBUG_PRINTLN("Light sensor initialization failed!");
            return false;
        }
    #endif
    
    return true;
}

bool readSensorData() {
    unsigned long readTimeout = millis();
    bool readSuccess = false;
    
    while (!readSuccess && (millis() - readTimeout < SENSOR_READ_TIMEOUT)) {
        try {
            extern environment env;
            env.temperature = bme.readTemperature();
            env.pressure = bme.readPressure() / 100.0F;
            
            #if defined(__BME280_H__)
                env.humidity = bme.readHumidity();
            #endif
            
            #if defined(USELIGHT)
                env.lux = LightSensor.GetLightIntensity();
            #endif
            
            if (env.temperature != NAN && env.pressure != NAN) {
                readSuccess = true;
            }
        } catch (...) {
            delay(100);
        }
    }
    
    return readSuccess;
}
