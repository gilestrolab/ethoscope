#include "network.h"

bool setupWiFi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(cfg.wifi_ssid, cfg.wifi_pwd);

    unsigned long startAttemptTime = millis();

    while (WiFi.status() != WL_CONNECTED &&
           millis() - startAttemptTime < WIFI_CONNECT_TIMEOUT) {
        delay(100);
        DEBUG_PRINT(".");
    }

    if (WiFi.status() != WL_CONNECTED) {
        return false;
    }

    DEBUG_PRINTLN("\nConnected to WiFi");
    DEBUG_PRINTLN(WiFi.localIP());

    setupMDNS();
    return true;
}

void setupMDNS() {
    if (!MDNS.begin(cfg.name)) {
        DEBUG_PRINTLN("Error setting up MDNS responder!");
        return;
    }
    MDNS.addService("sensor", "tcp", 80);
}

static const char TEXT_PLAIN[] PROGMEM = "text/plain";
static const char NOT_FOUND[] PROGMEM = "Not found";
static const char CONFIG_OK[] PROGMEM = "OK! Configuration changed.";

void PLATFORM_ATTR setupWebServer() {
    server.onNotFound([]() {
        server.send(404, FPSTR(TEXT_PLAIN), FPSTR(NOT_FOUND));
    });

    server.on("/", HTTP_GET, handleRoot);
    server.on("/web", HTTP_GET, handleWeb);
    server.on("/set", HTTP_POST, handleConfig);
    server.on("/reset", HTTP_GET, handleReset);

    server.begin();
}

void PLATFORM_ATTR handleRoot() {
    readSensorData();
    server.send(200, F("application/json"), SendJSON());
}

void PLATFORM_ATTR handleWeb() {
    readSensorData();
    server.send(200, F("text/html"), SendConfigHTML());
}

void PLATFORM_ATTR handleReset() {
    // Send JSON response
    String jsonResponse = "{\"status\":\"OK\",\"message\":\"Resetting\"}";
    server.send(200, F("application/json"), jsonResponse);

    // Delay to allow the response to be sent before resetting
    delay(100);  // You can adjust the delay as needed

    // Perform soft reset
    softReset();
}


void handleConfig() {
    String jsonData;
    if (server.hasArg("plain")) {
        jsonData = server.arg("plain");
    } else {
        // Handle form data
        if (server.hasArg("sensor_name")) {
            JsonDocument doc;
            doc["name"] = server.arg("sensor_name");
            doc["location"] = server.arg("location");
            serializeJson(doc, jsonData);
        } else {
            DEBUG_PRINTLN("Invalid request");
            server.send(400, "application/json", "{\"error\":\"Invalid request\"}");
            return;
        }
    }

    DEBUG_PRINT("Received JSON data: ");
    DEBUG_PRINTLN(jsonData);

    StaticJsonDocument<200> doc;
    DeserializationError error = deserializeJson(doc, jsonData);

    if (error) {
        DEBUG_PRINT("Invalid JSON: ");
        DEBUG_PRINTLN(error.c_str());
        server.send(400, "application/json", "{\"error\":\"Invalid JSON\"}");
        return;
    }

    bool configChanged = false;

    if (doc.containsKey("name")) {
        const char* newName = doc["name"];
        DEBUG_PRINT("New name: ");
        DEBUG_PRINTLN(newName);
        if (Storage::updateField("name", newName)) {
            strlcpy(cfg.name, newName, sizeof(cfg.name));
            configChanged = true;
        } else {
            DEBUG_PRINTLN("Failed to update name in storage");
        }
    }

    if (doc.containsKey("location")) {
        const char* newLocation = doc["location"];
        DEBUG_PRINT("New location: ");
        DEBUG_PRINTLN(newLocation);
        if (Storage::updateField("location", newLocation)) {
            strlcpy(cfg.location, newLocation, sizeof(cfg.location));
            configChanged = true;
        } else {
            DEBUG_PRINTLN("Failed to update location in storage");
        }
    }

    if (configChanged) {
        if (Storage::saveConfig(cfg)) {
            DEBUG_PRINTLN("Configuration updated successfully");
            server.send(200, "application/json", "{\"status\":\"Configuration updated successfully\"}");
        } else {
            DEBUG_PRINTLN("Failed to save configuration");
            server.send(500, "application/json", "{\"error\":\"Failed to save configuration\"}");
        }
    } else {
        DEBUG_PRINTLN("No changes made");
        server.send(200, "application/json", "{\"status\":\"No changes made\"}");
    }
}
void PLATFORM_ATTR reconnectWiFi() {
    WiFi.disconnect();
    delay(1000);
    setupWiFi();
}

String PLATFORM_ATTR getMacAddress() {
    uint8_t baseMac[6];
    WiFi.macAddress(baseMac);
    char baseMacChr[18] = {0};
    sprintf(baseMacChr, "%02X:%02X:%02X:%02X:%02X:%02X",
            baseMac[0], baseMac[1], baseMac[2],
            baseMac[3], baseMac[4], baseMac[5]);
    return String(baseMacChr);
}

String PLATFORM_ATTR getID() {
    String id_json = "{\"id\": \"";
    id_json += getMacAddress();
    id_json += "\"}\n";
    return id_json;
}


String PLATFORM_ATTR SendJSON() {
    static char jsonBuffer[JSON_BUFFER_SIZE];
    static char tempStr[TEMP_BUFFER_SIZE];
    static char humStr[HUM_BUFFER_SIZE];
    static char pressStr[PRESS_BUFFER_SIZE];
    #if defined(USELIGHT)
        static char luxStr[LUX_BUFFER_SIZE];
    #endif

    // Convert float values to strings with specified precision
    dtostrf(env.temperature, -6, 2, tempStr);
    dtostrf(env.humidity, -5, 2, humStr);
    dtostrf(env.pressure, -7, 2, pressStr);
    #if defined(USELIGHT)
        snprintf(luxStr, LUX_BUFFER_SIZE, "%u", env.lux);
    #endif

    String macAddr = getMacAddress();
    String ipAddr = WiFi.localIP().toString();

    // Format JSON using snprintf
    int written = snprintf(jsonBuffer, JSON_BUFFER_SIZE,
        "{"
        "\"id\":\"%s\","
        "\"ip\":\"%s\","
        "\"name\":\"%s\","
        "\"location\":\"%s\","
        "\"temperature\":\"%s\","
        "\"humidity\":\"%s\","
        "\"pressure\":\"%s\""
        #if defined(USELIGHT)
        ",\"light\":\"%s\""
        #endif
        "}",
        macAddr.c_str(),
        ipAddr.c_str(),
        cfg.name,
        cfg.location,
        tempStr,
        humStr,
        pressStr
        #if defined(USELIGHT)
        , luxStr
        #endif
    );

    // Check if buffer overflow would have occurred
    if (written >= JSON_BUFFER_SIZE) {
        DEBUG_PRINTLN("Warning: JSON buffer size too small");
        DEBUG_PRINT("Required size: ");
        DEBUG_PRINTLN(written + 1);
    }

    return String(jsonBuffer);
}

static const char PROGMEM HTML_FORM_HEAD[] = R"(
<!DOCTYPE html><html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>ESP Sensor Configuration</title>
    <style>
        * { box-sizing: border-box; }
        html {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            display: flex;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            background: #f0f2f5;
        }
        body {
            margin: 20px;
            max-width: 800px;
            width: 100%;
        }
        .container {
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 {
            color: #2c3e50;
            margin: 20px 0;
            font-size: 28px;
            font-weight: 500;
        }
        .info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .info-box {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #3498db;
        }
        .info-box.system { border-left-color: #34495e; }
        .info-box.environment { border-left-color: #2ecc71; }
        .label {
            font-size: 14px;
            color: #666;
            margin-bottom: 5px;
            text-transform: uppercase;
        }
        .value {
            font-size: 20px;
            color: #2c3e50;
            font-weight: 500;
        }
        .collapsible {
            background: #3498db;
            color: white;
            cursor: pointer;
            padding: 18px;
            width: 100%;
            border: none;
            text-align: left;
            outline: none;
            font-size: 16px;
            border-radius: 4px;
            margin: 20px 0 0 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .active, .collapsible:hover {
            background-color: #2980b9;
        }
        .collapsible:after {
            content: '+';
            font-size: 20px;
            font-weight: bold;
        }
        .active:after {
            content: '-';
        }
        .config-content {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.2s ease-out;
            background-color: #f8f9fa;
            border-radius: 0 0 4px 4px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            color: #34495e;
            font-weight: 500;
        }
        input[type="text"] {
            width: 100%;
            padding: 8px 12px;
            border: 2px solid #ddd;
            border-radius: 4px;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        input[type="text"]:focus {
            border-color: #3498db;
            outline: none;
        }
        .button {
            background: #3498db;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
            transition: background 0.3s;
        }
        .button:hover {
            background: #2980b9;
        }
        .api-info {
            margin-top: 20px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 8px;
            font-size: 14px;
        }
        code {
            background: #e9ecef;
            padding: 2px 5px;
            border-radius: 3px;
            font-family: monospace;
        }
    </style>
    <script>
        function submitForm(event) {
            event.preventDefault();
            const data = {
                name: document.getElementById('name').value,
                location: document.getElementById('location').value
            };

            fetch('/set', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data)
            })
            .then(response => response.text())
            .then(result => alert(result))
            .catch(error => alert('Error: ' + error));
        }

        document.addEventListener('DOMContentLoaded', function() {
            var coll = document.getElementsByClassName("collapsible");
            for (var i = 0; i < coll.length; i++) {
                coll[i].addEventListener("click", function() {
                    this.classList.toggle("active");
                    var content = this.nextElementSibling;
                    if (content.style.maxHeight) {
                        content.style.maxHeight = null;
                    } else {
                        content.style.maxHeight = content.scrollHeight + "px";
                    }
                });
            }
        });
    </script>
</head>
)";

String PLATFORM_ATTR SendConfigHTML() {
    String ptr = FPSTR(HTML_FORM_HEAD);
    ptr +="<body>\n";
    ptr +="<div class='container'>\n";
    ptr +="<h1>Environmental Sensor Station</h1>\n";

    // Device Information Grid
    ptr +="<div class='info-grid'>\n";

    // Add Board Information first
    ptr +="<div class='info-box system'>\n";
    ptr +="<div class='label'>Board Type</div>\n";
    ptr +="<div class='value'>" + String(getPlatformName()) + "</div>\n";
    ptr +="</div>\n";

    // System Information
    ptr +="<div class='info-box system'>\n";
    ptr +="<div class='label'>Device Name</div>\n";
    ptr +="<div class='value'>" + String(cfg.name) + "</div>\n";
    ptr +="</div>\n";

    ptr +="<div class='info-box system'>\n";
    ptr +="<div class='label'>Location</div>\n";
    ptr +="<div class='value'>" + String(cfg.location) + "</div>\n";
    ptr +="</div>\n";

    ptr +="<div class='info-box system'>\n";
    ptr +="<div class='label'>Device ID</div>\n";
    ptr +="<div class='value'>" + getMacAddress() + "</div>\n";
    ptr +="</div>\n";

    ptr +="<div class='info-box system'>\n";
    ptr +="<div class='label'>IP Address</div>\n";
    ptr +="<div class='value'>" + WiFi.localIP().toString() + "</div>\n";
    ptr +="</div>\n";

    // Sensor Readings
    ptr +="<div class='info-box environment'>\n";
    ptr +="<div class='label'>Temperature</div>\n";
    ptr +="<div class='value'>" + String(env.temperature, 1) + " C</div>\n";
    ptr +="</div>\n";

    #if defined(__BME280_H__)
    ptr +="<div class='info-box environment'>\n";
    ptr +="<div class='label'>Humidity</div>\n";
    ptr +="<div class='value'>" + String(env.humidity, 1) + " %</div>\n";
    ptr +="</div>\n";
    #endif

    ptr +="<div class='info-box environment'>\n";
    ptr +="<div class='label'>Pressure</div>\n";
    ptr +="<div class='value'>" + String(env.pressure, 1) + " hPa</div>\n";
    ptr +="</div>\n";

    #if defined(USELIGHT)
    ptr +="<div class='info-box environment'>\n";
    ptr +="<div class='label'>Light Level</div>\n";
    ptr +="<div class='value'>" + String(env.lux) + " lux</div>\n";
    ptr +="</div>\n";
    #endif

    ptr +="</div>\n"; // Close info-grid

    // Collapsible Configuration Section
    ptr +="<button class='collapsible'>Configuration Settings</button>\n";
    ptr +="<div class='config-content'>\n";
    ptr +="<div style='padding: 20px;'>\n";  // Add padding to the content

    // Configuration form
    ptr +="<form onsubmit='submitForm(event)'>\n";
    ptr +="<div class='form-group'>\n";
    ptr +="<label for='name'>Device Name:</label>\n";
    ptr +="<input type='text' id='name' name='name' value='" + String(cfg.name) + "'>\n";
    ptr +="</div>\n";

    ptr +="<div class='form-group'>\n";
    ptr +="<label for='location'>Location:</label>\n";
    ptr +="<input type='text' id='location' name='location' value='" + String(cfg.location) + "'>\n";
    ptr +="</div>\n";

    ptr +="<button type='submit' class='button'>Update Configuration</button>\n";
    ptr +="<a href='/reset' class='button' style='margin-left: 10px;'>Reset Device</a>\n";

    ptr +="</form>\n";

    // API Documentation
    ptr +="<div class='api-info'>\n";
    ptr +="<h3>API Usage</h3>\n";
    ptr +="<p>Configure this device using POST request with JSON:</p>\n";
    ptr +="<code>echo '{\"name\": \"etho_sensor-001\", \"location\": \"Incubator-18C\"}' | curl -d @- http://" + WiFi.localIP().toString() + "/set</code>\n";
    ptr +="</div>\n";

    ptr +="</div>\n"; // Close padding div
    ptr +="</div>\n"; // Close config-content

    ptr +="</div>\n"; // Close container
    ptr +="</body>\n";
    ptr +="</html>\n";
    return ptr;
}
