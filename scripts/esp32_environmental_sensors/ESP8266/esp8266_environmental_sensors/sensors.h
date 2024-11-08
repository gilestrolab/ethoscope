#ifndef SENSORS_H
#define SENSORS_H

#include <Adafruit_BME280.h>
#include <BH1750FVI.h>
#include "config.h"

extern Adafruit_BME280 bme;
#if defined(USELIGHT)
    extern BH1750FVI LightSensor;
#endif

bool initializeSensors();
bool readSensorData();

#endif
