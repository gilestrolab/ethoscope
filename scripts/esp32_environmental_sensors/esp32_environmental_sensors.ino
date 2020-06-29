/*
  ESP32/8266 mDNS based environmental sensor

  This is an example of an HTTP server that is accessible
  via mDNS responder.

  Soldier together the two sensors boards (BME280 and BH1750), using the same header
  then connect to the ESP32 
  VCC -> 3.3V
  Gnd -> Gnd
  SDA -> D21
  SCL -> D22

  or ESP8266 D1 mini Pro
  VCC -> 3.3V
  Gnd -> Gnd
  SDA -> D1
  SCL -> D2

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

#if defined(ESP32)
  #include <WiFi.h>
  #include <ESPmDNS.h>
  #include <WiFiClient.h>
  #include "esp_system.h"
  #include <WebServer.h>  

  WebServer server(80);    

  // Ideally, on ESP32 we would also use EEPROM rotate for consistency
  // https://github.com/xoseperez/eeprom32_rotate
  // but it seems to be too buggy
  //#include <EEPROM32_Rotate.h>
  //EEPROM32_Rotate EEPROMr;

  // To save data in the EEPROM use the following
  // http://tronixstuff.com/2011/03/16/tutorial-your-arduinos-inbuilt-eeprom/
  #include <EEPROM.h>

#elif defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266mDNS.h>
  #include <WiFiClient.h>
  #include <ESP8266WebServer.h>

  ESP8266WebServer server(80);

  // For ESP8266, EEPROM rotate seems the only library that actually works
  // https://github.com/xoseperez/eeprom_rotate
  #include <EEPROM_Rotate.h>
  EEPROM_Rotate EEPROMr;
#endif

#define EEPROM_SIZE 4096 //total size of the eeprom we want to use
#define EEPROM_START 128 //from which byte on we start writing data

//For I2C communication
#include <Wire.h>

//For sensor-specific routines
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <BH1750FVI.h>

//Initialise the I2C environmental sensors
Adafruit_BME280 bme;
BH1750FVI LightSensor(BH1750FVI::k_DevModeContLowRes);

//We want to use a watchdog for ESP32 to avoid recurrent crashes
#if defined(ESP32)
  const int button = 0;         //gpio to use to trigger delay
  const int wdtTimeout = 3000;  //time in ms to trigger the watchdog
  hw_timer_t *timer = NULL;

  void IRAM_ATTR resetModule() {
    esp_restart();
  }
#endif

typedef struct {
  float temperature;
  float humidity;
  float pressure;
  uint16_t lux;  
} environment;

typedef struct {
  char location[20];
  char sensor_name[20];
} configuration;

configuration cfg = {"", "etho_sensor"};
environment env;

const char* ssid = "ETHOSCOPE_WIFI";
const char* password = "ETHOSCOPE_1234";

void setup(void)
{  
    Serial.begin(57600);

#if defined(ESP8266)    
    Serial.println("Initialising EEPROM.");
    EEPROMr.begin(EEPROM_SIZE);
    delay(1000);
    Serial.println("EEPROM initialised.");
#endif

#if defined(ESP32)
    if (!EEPROM.begin(EEPROM_SIZE)) {
        Serial.println("Failed to initialise EEPROM");
        Serial.println("Restarting...");
        delay(1000);
        ESP.restart();
    }
#endif

    loadConfiguration();

    // Connect to WiFi network
    WiFi.begin(ssid, password);
    Serial.println("");

    // Wait for connection
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("");
    Serial.print("Connected to ");
    Serial.println(ssid);
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());

    // Set up mDNS responder:
    if (!MDNS.begin(cfg.sensor_name)) {
        Serial.println("Error setting up MDNS responder!");
        while(1) {
            delay(1000);
        }
    }
    Serial.println("mDNS responder started");

    // Start TCP (HTTP) server
    server.begin();
    server.on("/", handle_OnConnect);
    server.on("/id", handle_OnID);
    server.onNotFound(handle_NotFound);
    server.on("/set", handlePost);
    server.begin();
    Serial.println("HTTP server started");

    // Advertise service to MDNS-SD
    MDNS.addService("sensor", "tcp", 80);

    // Initialise BME280 and BH1750 I2C sensors
    bme.begin(0x76);
    LightSensor.begin();

    readEnv();
    Serial.println(SendJSON());

#if defined(ESP32)
    //Starting a watchdog timer
    timer = timerBegin(0, 80, true);                  //timer 0, div 80
    timerAttachInterrupt(timer, &resetModule, true);  //attach callback
    timerAlarmWrite(timer, wdtTimeout * 1000, false); //set time in us
    timerAlarmEnable(timer);                          //enable interrupt

    // We remove power save functions on WiFi to try and solve the mDNS disappearance issue
    WiFi.setSleep(false);
#endif
}

void loop(void)
{
  
#if defined(ESP8266)
    MDNS.update();
#endif

#if defined(ESP32)
    timerWrite(timer, 0); //reset timer (feed watchdog)
#endif

    server.handleClient();

}

void loadConfiguration()
{

#if defined(ESP8266)
    if (EEPROMr.read(EEPROM_START) != 1) { saveConfiguration(); }
    EEPROMr.get(EEPROM_START+2, cfg);
    delay(500);
#endif

#if defined(ESP32)
    if (EEPROM.read(EEPROM_START) != 1) { saveConfiguration(); } 
    EEPROM.get(EEPROM_START+2, cfg);
#endif

    Serial.println("Configuration loaded.");

}

void saveConfiguration()
{
#if defined(ESP8266)
    EEPROMr.write(EEPROM_START, 1);
    delay(250);
    EEPROMr.put(EEPROM_START+2, cfg);
    delay(250);
    EEPROMr.commit();
#endif

#if defined(ESP32)
    EEPROM.write(EEPROM_START, 1);
    EEPROM.put(EEPROM_START+2, cfg);
    EEPROM.commit();
#endif

    Serial.println("Configuration saved.");
}

//to rename from commandline use the following command
//curl -d location=Incubator_1A -d sensor_name=etho_sensor_1A -G http://DEVICE_IP/set
//DEVICE_IP can be found opening the serial port

void handlePost() {
    if (server.hasArg("location")) {
      //cfg.location = (char*) server.arg("location").c_str();
      server.arg("location").toCharArray(cfg.location, 20);
      Serial.print("New value of location: ");
      Serial.println(cfg.location);
    }
    if (server.hasArg("sensor_name")) {
      //cfg.sensor_name = (char*) server.arg("name").c_str(); 
      server.arg("sensor_name").toCharArray(cfg.sensor_name, 20); 
      Serial.print("New value of sensor_name: ");
      Serial.println(cfg.sensor_name);
  }
    saveConfiguration();
    server.send(200, "application/json", "OK\n");
}


void handle_OnID(void) {
    String ptr = "{\"id\": \"";
    ptr += getMacAddress();
    ptr += "\"}";
    server.send(200, "application/json", ptr);
}

void readEnv(void){
    env.temperature = bme.readTemperature();
    env.humidity = bme.readHumidity();
    env.pressure = bme.readPressure() / 100.0F;
    env.lux = LightSensor.GetLightIntensity();
  }

void handle_OnConnect(void) {
//  server.send(200, "text/html", SendHTML());
    readEnv();
    server.send(200, "application/json", SendJSON());

}

void handle_NotFound(){
    server.send(404, "text/plain", "Not found");
}


String SendJSON(){
    String ptr = "{\"id\": \"";
    ptr += getMacAddress();
    ptr += "\", \"ip\" : \"";
    ptr += WiFi.localIP().toString();
    ptr += "\", \"name\" : \"";
    ptr += cfg.sensor_name;
    ptr += "\", \"location\" : \"";
    ptr += cfg.location;
    ptr += "\", \"temperature\" : \"";
    ptr += env.temperature;
    ptr += "\", \"humidity\" : \"";
    ptr += env.humidity;
    ptr += "\", \"pressure\" : \"";
    ptr += env.pressure;
    ptr += "\", \"light\" : \"";
    ptr += env.lux;
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
    ptr +="<p>Humidity: ";
    ptr +=env.humidity;
    ptr +="%</p>";
    ptr +="<p>Pressure: ";
    ptr +=env.pressure;
    ptr +="hPa</p>";
    ptr +="<p>Lux: ";
    ptr +=env.lux;
    ptr +="hPa</p>";
    ptr +="</div>\n";
    ptr +="</body>\n";
    ptr +="</html>\n";
    return ptr;
}

String getMacAddress(void) {
    uint8_t baseMac[6];

    // Get the MAC address as UID
    #if defined(ESP32)
      esp_read_mac(baseMac, ESP_MAC_WIFI_STA);
    #elif defined(ESP8266)
      WiFi.macAddress(baseMac);
    #endif
    
    char baseMacChr[18] = {0};
    sprintf(baseMacChr, "%02X:%02X:%02X:%02X:%02X:%02X", baseMac[0], baseMac[1], baseMac[2], baseMac[3], baseMac[4], baseMac[5]);
    return String(baseMacChr);
}
