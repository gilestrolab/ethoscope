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

  or ESP8266 D1 mini Pro
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

#include <ESP8266WiFi.h>
#include <ESP8266mDNS.h>
#include <WiFiClient.h>

//https://github.com/me-no-dev/ESPAsyncWebServer
#include <ESPAsyncWebServer.h>

#include <StringArray.h>
#include <SPIFFS.h>
#include <FS.h>




//For I2C communication
#include <Wire.h>

//For sensor-specific routines
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <BH1750FVI.h>

// Create a web server object on port 80
AsyncWebServer server(80);

//Initialise the I2C environmental sensors
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
  char phenoscope_name[20];
  char wifi_ssid[20];
  char wifi_pwd[20];
} configuration;

environment env;
configuration cfg = {"", "phenoscope_000", "pecorita.net", "p3c0r1t4"};

#define CFG_FILE "/CFG_FILE.bin"

void setup(void)
{  
    Serial.begin(115200);

    // Mount SPIFFS
    if (!SPIFFS.begin(true)) {
      Serial.println("An Error has occurred while mounting SPIFFS");
      ESP.restart();
    }
    else {
      delay(500);
      Serial.println("SPIFFS mounted successfully");
    }

      loadConfigurationSPIFFS();

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
      if (!MDNS.begin(cfg.phenoscope_name)) {
          Serial.println("Error setting up MDNS responder!");
          while(1) {
              delay(1000);
          }
      }
      Serial.println("mDNS responder started");

      // Start TCP (HTTP) server
      server.onNotFound(notFound);
      
    server.on("/", HTTP_GET, [](AsyncWebServerRequest *request){
      readEnv();
      request->send(200, "text/plain", SendJSON() );
    });    

	//to rename from commandline use the following command
  //curl -d location=Incubator_1A -d phenoscope_name=phenoscope_1A -G http://DEVICE_IP/set (for GET)
	//echo '{"phenoscope_name": "phenoscope-001", "location": "Room-A"}' | curl -d @- http://DEVICE_IP/set  (for POST)
	//DEVICE_IP can be found opening the serial port
    server.on("/set", HTTP_GET, [](AsyncWebServerRequest *request){

        if (request->hasParam("phenoscope_name")) {
            request->getParam("phenoscope_name")->value().toCharArray(cfg.phenoscope_name, 20);
            Serial.println(cfg.phenoscope_name);
        }
        
        if (request->hasParam("location")) {
            request->getParam("location")->value().toCharArray(cfg.location, 20);
            Serial.println(cfg.location);
		}
        
        saveConfigurationSPIFFS();
        request->send(200, "text/plain", "Configuration changed." );
    });

    server.begin();
    Serial.println("HTTP server started");

    // Advertise WEBSERVER service to MDNS-SD
    MDNS.addService("phenoscope", "tcp", 80);

    // Initialise BME280 and BH1750 I2C sensors
    I2CBME.begin(I2C_SDA, I2C_SCL, 100000);
   
	bool status;
	status = bme.begin(0x76, &I2CBME);  
	if (!status) {
		Serial.println("Could not find a valid BME280 sensor, check wiring!");
		//while (1);
	}

    //LightSensor.begin();
    readEnv();
    Serial.println(SendJSON());

    //Starting a watchdog timer
    timer = timerBegin(0, 80, true);                  //timer 0, div 80
    timerAttachInterrupt(timer, &resetModule, true);  //attach callback
    timerAlarmWrite(timer, wdtTimeout * 1000, false); //set time in us
    timerAlarmEnable(timer);                          //enable interrupt

    // We remove power save functions on WiFi to try and solve the mDNS disappearance issue
    WiFi.setSleep(false);


}

void loop(void)
{
  
    timerWrite(timer, 0); //reset timer (feed watchdog)
    delay(1);

}

void saveConfigurationSPIFFS() {
    // Photo file name
    Serial.printf("Configuration file name: %s\n", CFG_FILE);
    File configFile = SPIFFS.open(CFG_FILE, FILE_WRITE);

    // Insert the data in the photo file
    if (!configFile) {
      Serial.println("Failed to open file in writing mode");
    }
    else {
	  //unsigned char * data = reinterpret_cast<unsigned char*>(cfg); // use unsigned char, as uint8_t is not guarunteed to be same width as char...
	  //size_t bytes = configFile.write(data, sizeof(cfg)); 
	  configFile.write((byte *)&cfg, sizeof(cfg));
	  Serial.println("Configuration written to file");
    }
    // Close the file
    configFile.close();
}

void loadConfigurationSPIFFS() {

  if (!SPIFFS.exists(CFG_FILE)) {
	   saveConfigurationSPIFFS ();
	   }

  File configFile = SPIFFS.open (CFG_FILE, "r");

  if (configFile && configFile.size()) {
	  configFile.read((byte *)&cfg, sizeof(cfg));
	  configFile.close();
	}
}

void notFound(AsyncWebServerRequest *request) {
    request->send(404, "text/plain", "Not found");
}

void readEnv(void){
    env.temperature = bme.readTemperature();
    env.humidity = bme.readHumidity();
    env.pressure = bme.readPressure() / 100.0F;
    //env.lux = LightSensor.GetLightIntensity();
  }

String SendJSON(){
    String ptr = "{\"id\": \"";
    ptr += getMacAddress();
    ptr += "\", \"ip\" : \"";
    ptr += WiFi.localIP().toString();
    ptr += "\", \"name\" : \"";
    ptr += cfg.phenoscope_name;
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
    WiFi.macAddress(baseMac);
    
    char baseMacChr[18] = {0};
    sprintf(baseMacChr, "%02X:%02X:%02X:%02X:%02X:%02X", baseMac[0], baseMac[1], baseMac[2], baseMac[3], baseMac[4], baseMac[5]);
    return String(baseMacChr);
}
