/*
  ESP8266 mDNS based environmental sensor

  This is an example of an HTTP server that is accessible
  via mDNS responder.

  Soldier together the two sensors boards (BME280 and BH1750), using the same header
  then connect to the ESP32 
  VCC -> 3.3V
  Gnd -> Gnd
  SDA -> D21
  SCL -> D22

  or ESP8266 D1 mini Pro (use WEMOS D1 R1)
  VCC -> 3.3V
  Gnd -> Gnd
  SDA -> D2
  SCL -> D1

  Instructions:
  - Update WiFi SSID and password as necessary.
  - Flash the sketch to the board
  - Install host software:
    - For Linux, install Avahi (http://avahi.org/).
    - For Windows, install Bonjour (http://www.apple.com/support/bonjour/).
    - For Mac OSX and iOS support is built in through Bonjour already.
  - Point your browser to http://etho_sensor.local, you should see a response.

  - To memorize multiple SSIDs options instead of only one
 https://tttapa.github.io/ESP8266/Chap10%20-%20Simple%20Web%20Server.html


*/

#define USELIGHT

#include <ESP8266WiFi.h>
#include <ESP8266mDNS.h>
#include <WiFiClient.h>

//https://github.com/me-no-dev/ESPAsyncWebServer
#include <ESPAsyncWebServer.h>
#include <StringArray.h>

// For ESP8266, EEPROM rotate seems the only library that actually works
// https://github.com/xoseperez/eeprom_rotate
#include <EEPROM_Rotate.h>
EEPROM_Rotate EEPROMr;

#define EEPROM_SIZE 4096 //total size of the eeprom we want to use
#define EEPROM_START 128 //from which byte on we start writing data

//For I2C communication
#include <Wire.h>

//For sensor-specific routines
#include <Adafruit_Sensor.h>

//BMP cannot measure humidity
#include <Adafruit_BME280.h>
//#include <Adafruit_BMP280.h>

#include <BH1750FVI.h>

//Initialise the I2C environmental sensors
Adafruit_BME280 bme; // I2C

#if defined(USELIGHT)
    BH1750FVI LightSensor(BH1750FVI::k_DevModeContLowRes);
#endif

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

environment env;
configuration cfg = {"", "etho_sensor", "ETHOSCOPE_WIFI", "ETHOSCOPE_1234"};

#define CFG_FILE "/CFG_FILE.bin"

// Create a web server object on port 80
AsyncWebServer server(80);


void setup(void)
{  
    Serial.begin(115200);

    // Connect to WiFi network
    WiFi.begin(cfg.wifi_ssid, cfg.wifi_pwd);

    // Wait for connection
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("");
    Serial.print("Connected to ");
    Serial.println(cfg.wifi_ssid);
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());

    // Set up mDNS responder:
    if (!MDNS.begin(cfg.name)) {
        Serial.println("Error setting up MDNS responder!");
        while(1) {
            delay(1000);
        }
    }
    Serial.println("mDNS responder started");

    // Start TCP (HTTP) server
    server.onNotFound(notFound);

    server.on("/id", HTTP_GET, [](AsyncWebServerRequest *request){
      request->send(200, "text/plain", getID() );
    });
      
    server.on("/", HTTP_GET, [](AsyncWebServerRequest *request){
      readEnv();
      request->send(200, "text/plain", SendJSON() );
    });    

	//to rename from commandline use curl as below:
  //curl -d location=Incubator_1A -d name=etho_sensor_1A -G http://DEVICE_IP/set (for GET)
	//echo '{"name": "etho_sensor-001", "location": "Incubator-18C"}' | curl -d @- http://DEVICE_IP/set  (for POST)
  //DEVICE_IP can be found opening the serial port
  
    server.on("/set", HTTP_GET, [](AsyncWebServerRequest *request){

        if (request->hasParam("name")) {
            request->getParam("name")->value().toCharArray(cfg.name, 20);
            Serial.println(cfg.name);
        }
        
        if (request->hasParam("location")) {
            request->getParam("location")->value().toCharArray(cfg.location, 20);
            Serial.println(cfg.location);
        }
            
        saveConfiguration();
            request->send(200, "text/plain", "OK! Configuration changed." );
    });

    server.begin();
    Serial.println("HTTP server started");

    // Advertise WEBSERVER service to MDNS-SD
    MDNS.addService("sensor", "tcp", 80);

    // Initialise Wire. This is where we can specify different SDA/SCL pins if needed
    Wire.begin();

    // Initialise BME280 and BH1750 I2C sensors
    bool status;
    status = bme.begin(0x77);  
    if (!status) {
    	Serial.println("Could not find a valid BME280 sensor, check wiring!");
    	//while (1);
    }

    #if defined(USELIGHT)
      LightSensor.begin();
    #endif
    
    readEnv();
    Serial.println(SendJSON());

}

void loop(void)
{
  
    delay(10);
    MDNS.update();

}

void loadConfiguration()
{

    if (EEPROMr.read(EEPROM_START) != 1) { saveConfiguration(); }
    EEPROMr.get(EEPROM_START+2, cfg);
    delay(500);

    Serial.println("Configuration loaded.");

}

void saveConfiguration()
{
    EEPROMr.write(EEPROM_START, 1);
    delay(250);
    EEPROMr.put(EEPROM_START+2, cfg);
    delay(250);
    EEPROMr.commit();

    Serial.println("Configuration saved.");
}


void notFound(AsyncWebServerRequest *request) {
    request->send(404, "text/plain", "Not found");
}

void readEnv(void){
    env.temperature = bme.readTemperature();
    env.pressure = bme.readPressure() / 100.0F;

    #if defined(__BME280_H__)
      env.humidity = bme.readHumidity();
    #endif

    #if defined(USELIGHT)
      env.lux = LightSensor.GetLightIntensity();
    #endif
  }

String SendJSON(){
    String ptr = "{\"id\": \"";
    ptr += getMacAddress();
    ptr += "\", \"ip\" : \"";
    ptr += WiFi.localIP().toString();
    ptr += "\", \"name\" : \"";
    ptr += cfg.name;
    ptr += "\", \"location\" : \"";
    ptr += cfg.location;
    ptr += "\", \"temperature\" : \"";
    ptr += env.temperature;

    #if defined(__BME280_H__)
      ptr += "\", \"humidity\" : \"";
      ptr += env.humidity;
    #endif

    ptr += "\", \"pressure\" : \"";
    ptr += env.pressure;

    #if defined(USELIGHT)
        ptr += "\", \"light\" : \"";
        ptr += env.lux;
    #endif

    ptr += "\"}";
    return ptr; 
}

String SendHTML(){
    String ptr = "<!DOCTYPE html> <html>\n";
    ptr +="<head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0, user-scalable=no\">\n";
    ptr +="<title>ESP based Environmental Station</title>\n";
    ptr +="<style>html { font-family: Helvetica; display: inline-block; margin: 0px auto; text-align: center;}\n";
    ptr +="body{margin-top: 50px;} h1 {color: #444444;margin: 50px auto 30px;}\n";
    ptr +="p {font-size: 24px;color: #444444;margin-bottom: 10px;}\n";
    ptr +="</style>\n";
    ptr +="</head>\n";
    ptr +="<body>\n";
    ptr +="<div id=\"webpage\">\n";
    ptr +="<h1>ESP32 Based WIFI sensor</h1>\n";
    ptr +="<p>ID: ";
    ptr +=getMacAddress();
    ptr +="</p>";
    ptr +="<p>IP: ";
    ptr +=WiFi.localIP().toString();
    ptr +="</p>";
    ptr +="<p>Temperature: ";
    ptr +=env.temperature;
    ptr +="&deg;C</p>";

    #if defined(__BME280_H__)
      ptr +="<p>Humidity: ";
      ptr +=env.humidity;
      ptr +="%</p>";
    #endif

    ptr +="<p>Pressure: ";
    ptr +=env.pressure;
    ptr +="hPa</p>";

    #if defined(USELIGHT)
        ptr +="<p>Lux: ";
        ptr +=env.lux;
    #endif

    ptr +="</p>";
    ptr +="</div>\n";
    ptr +="</body>\n";
    ptr +="</html>\n";
    return ptr;
}

String getMacAddress(void) {
    uint8_t baseMac[6];

    // Get the MAC address as UID
    WiFi.macAddress(baseMac);
    
    char baseMacChr[18] = {0};
    sprintf(baseMacChr, "%02X:%02X:%02X:%02X:%02X:%02X", baseMac[0], baseMac[1], baseMac[2], baseMac[3], baseMac[4], baseMac[5]);
    return String(baseMacChr);
}

String getID(void) {
    String id_json = "{\"id\": \"";
    id_json += getMacAddress();
    id_json += "\"}\n";
    return id_json;
}
