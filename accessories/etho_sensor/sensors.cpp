#include "sensors.h"

bool initializeSensors() {
    Wire.begin();
    Wire.setClock(100000);  // Set to 100kHz
    delay(100);  // Add small delay after Wire initialization

    // Try both possible BME280 I2C addresses
    if (!bme.begin(0x76)) {
        delay(100);
        if (!bme.begin(0x77)) {
            DEBUG_PRINTLN("Could not find BME280 sensor!");
            DEBUG_PRINTLN("Trying address 0x76 and 0x77");
            return false;
        }
    }

    // Set BME280 settings
    bme.setSampling(Adafruit_BME280::MODE_NORMAL,     // Operating Mode
                    Adafruit_BME280::SAMPLING_X1,      // Temp. oversampling
                    Adafruit_BME280::SAMPLING_X1,      // Pressure oversampling
                    Adafruit_BME280::SAMPLING_X1,      // Humidity oversampling
                    Adafruit_BME280::FILTER_OFF,       // Filtering
                    Adafruit_BME280::STANDBY_MS_500);  // Standby time

    delay(100);  // Give the sensor time to adjust

    // // Add I2C scan for debugging
    // DEBUG_PRINTLN("Scanning I2C bus...");
    // for(byte address = 1; address < 127; address++) {
    //     Wire.beginTransmission(address);
    //     byte error = Wire.endTransmission();
    //     if (error == 0) {
    //         char buf[32];
    //         snprintf(buf, sizeof(buf), "I2C device found at address 0x%02X", address);
    //         DEBUG_PRINTLN(buf);
    //     }
    // }

    #if defined(USELIGHT)
        LightSensor.begin();
    #endif

    return true;
}

bool readSensorData() {
    float temp = bme.readTemperature();
    if (temp == NAN) return false;

    float press = bme.readPressure();
    if (press == NAN) return false;

    env.temperature = temp;
    env.pressure = press / 100.0F;

    #if defined(__BME280_H__)
        float hum = bme.readHumidity();
        if (hum != NAN) {
            env.humidity = hum;
        }
    #endif

    #if defined(USELIGHT)
        env.lux = LightSensor.GetLightIntensity();
    #endif

    return true;
}
