/*
  ESP32 mDNS responder sample

  This is an example of an HTTP server that is accessible
  via http://esp32.local URL thanks to mDNS responder.

  Instructions:
  - Update WiFi SSID and password as necessary.
  - Flash the sketch to the ESP32 board
  - Install host software:
    - For Linux, install Avahi (http://avahi.org/).
    - For Windows, install Bonjour (http://www.apple.com/support/bonjour/).
    - For Mac OSX and iOS support is built in through Bonjour already.
  - Point your browser to http://esp32.local, you should see a response.

 */


#include <WiFi.h>
#include <ESPmDNS.h>
#include <WiFiClient.h>

#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <BH1750FVI.h>


#include <WebServer.h>

Adafruit_BME280 bme;
BH1750FVI LightSensor(BH1750FVI::k_DevModeContLowRes);

float temperature, humidity, pressure;
uint16_t lux;

const char* ssid = "ETHOSCOPE_WIFI";
const char* password = "ETHOSCOPE_1234";
const char* sensor_name = "esp32";

// TCP server at port 80 will respond to HTTP requests
//WiFiServer server(80);
WebServer server(80);    

void setup(void)
{  
    Serial.begin(115200);

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
    // - first argument is the domain name, in this example
    //   the fully-qualified domain name is "esp8266.local"
    // - second argument is the IP address to advertise
    //   we send our IP address on the WiFi network
    if (!MDNS.begin(sensor_name)) {
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
    server.begin();
    Serial.println("HTTP server started");

    // Add service to MDNS-SD
    //MDNS.addService("http", "tcp", 80);
    MDNS.addService("sensor", "tcp", 80);

    // Initialise BME 280 I2C sensor
    bme.begin(0x76);
    LightSensor.begin();  
    
}

void handle_OnID(void) {
    String ptr = "{\"id\": \"";
    ptr += getMacAddress();
    ptr += "\"}";
    server.send(200, "application/json", ptr);
}

void handle_OnConnect(void) {
    temperature = bme.readTemperature();
    humidity = bme.readHumidity();
    pressure = bme.readPressure() / 100.0F;
    lux = LightSensor.GetLightIntensity();
//  server.send(200, "text/html", SendHTML(temperature,humidity,pressure,lux));
    server.send(200, "application/json", SendJSON(temperature,humidity,pressure,lux));

}

void handle_NotFound(){
    server.send(404, "text/plain", "Not found");
}

void loop(void)
{
    server.handleClient();
}

String SendJSON(float temperature, float humidity, float pressure, uint16_t lux){
  String ptr = "{\"id\": \"";
  ptr += getMacAddress();
  ptr += "\", \"ip\" : \"";
  ptr += WiFi.localIP().toString();
  ptr += "\", \"temperature\" : \"";
  ptr += temperature;
  ptr += "\", \"humidity\" : \"";
  ptr += humidity;
  ptr += "\", \"pressure\" : \"";
  ptr += pressure;
  ptr += "\", \"light\" : \"";
  ptr += lux;
  ptr += "\"}";
  return ptr; 
}

String SendHTML(float temperature, float humidity, float pressure, uint16_t lux){
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
  ptr +="<p>Temperature: ";
  ptr +=temperature;
  ptr +="&deg;C</p>";
  ptr +="<p>Humidity: ";
  ptr +=humidity;
  ptr +="%</p>";
  ptr +="<p>Pressure: ";
  ptr +=pressure;
  ptr +="hPa</p>";
  ptr +="<p>Lux: ";
  ptr +=lux;
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
