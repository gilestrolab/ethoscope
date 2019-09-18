/*
  ESP32 mDNS responder sample

  This is an example of an HTTP server that is accessible
  via http://esp32.local URL thanks to mDNS responder.

  Soldier together the two sensors boards (BME280 and BH1750), using the same header
  then connect to the ESP32 
  VCC -> 3.3V
  Gnd -> Gnd
  SDA -> D21
  SCL -> D22

  Instructions:
  - Update WiFi SSID and password as necessary.
  - Flash the sketch to the ESP32 board
  - Install host software:
    - For Linux, install Avahi (http://avahi.org/).
    - For Windows, install Bonjour (http://www.apple.com/support/bonjour/).
    - For Mac OSX and iOS support is built in through Bonjour already.
  - Point your browser to http://etho_sensor.local, you should see a response.

*/


#include <WiFi.h>
#include <ESPmDNS.h>
#include <WiFiClient.h>

#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <BH1750FVI.h>

#include <WebServer.h>

// To save data in the EEPROM use the following
// http://tronixstuff.com/2011/03/16/tutorial-your-arduinos-inbuilt-eeprom/
#include <EEPROM.h>
int addr = 0;
#define EEPROM_SIZE 64

Adafruit_BME280 bme;
BH1750FVI LightSensor(BH1750FVI::k_DevModeContLowRes);

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

// TCP server at port 80 will respond to HTTP requests
//WiFiServer server(80);
WebServer server(80);    

void setup(void)
{  
    Serial.begin(57600);

    if (!EEPROM.begin(EEPROM_SIZE)) {
        Serial.println("Failed to initialise EEPROM");
        Serial.println("Restarting...");
        delay(1000);
        ESP.restart();
    }
    
    loadConfiguration();

    // Connect to WiFi network
    WiFi.begin(ssid, password);
    Serial.println("");

    // We remove power save functions on WiFi to try and solve the mDNS disappearance issue
    WiFi.setSleep(false);

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
    // - first argument is the domain name, in this example
    //   the fully-qualified domain name is "esp8266.local"
    // - second argument is the IP address to advertise
    //   we send our IP address on the WiFi network
    if (!MDNS.begin(cfg.sensor_name)) {
        Serial.println("Error setting up MDNS responder!");
        while(1) {
            delay(1000);
        }
    }
    Serial.println("mDNS responder started");

    // Start TCP (HTTP) server
    //server.begin();
    server.on("/", handle_OnConnect);
    server.on("/id", handle_OnID);
    server.onNotFound(handle_NotFound);
    server.on("/set", handlePost);
    server.begin();
    Serial.println("HTTP server started");

    // Add service to MDNS-SD
    //MDNS.addService("http", "tcp", 80);
    MDNS.addService("_sensor", "_tcp", 80);

    // Initialise BME 280 I2C sensor
    bme.begin(0x76);
    LightSensor.begin();

    readEnv();
    Serial.println(SendJSON());
    
}

void loadConfiguration()
{
// on the very first flash, byte 9 is set to 255
// we use this to save the default values to the arduino
  if (EEPROM.read(0) != 1) { saveConfiguration(); } 
  EEPROM.get(1, cfg);
  Serial.println("Configuration loaded.");

}

void saveConfiguration()
{
//saves values to EEPROM

  EEPROM.write(0, 1);
  EEPROM.put(1, cfg);
  EEPROM.commit();
  Serial.println("Configuration saved.");

}

//to rename from commandline use the following command
//curl -d location=Incubator_1A -d sensor_name=etho_sensor_1A -G http://DEVICE_IP/set
//DEVICE_IP can be found opening the serial port

void handlePost() {
  if (server.hasArg("location")) {
    //cfg.location = (char*) server.arg("location").c_str();
    server.arg("location").toCharArray(cfg.location, 20);
    Serial.println("Changed the value of location");
    }
  if (server.hasArg("sensor_name")) {
    //cfg.sensor_name = (char*) server.arg("name").c_str(); 
    server.arg("sensor_name").toCharArray(cfg.sensor_name, 20); 
    Serial.println("Changed the value of sensor_name");
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

void loop(void)
{
    server.handleClient();
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
  ptr +="<title>ESP8266 Weather Station</title>\n";
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
    // Get MAC address for WiFi station
    esp_read_mac(baseMac, ESP_MAC_WIFI_STA);
    char baseMacChr[18] = {0};
    sprintf(baseMacChr, "%02X:%02X:%02X:%02X:%02X:%02X", baseMac[0], baseMac[1], baseMac[2], baseMac[3], baseMac[4], baseMac[5]);
    return String(baseMacChr);
}
