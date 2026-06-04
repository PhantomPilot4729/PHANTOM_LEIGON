#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "config.h"

Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);
WiFiClient client;

// ── Helpers ──────────────────────────────────────────────────────────────────

void showStatus(const char* msg) {
    display.clearDisplay();
    display.setTextSize(2);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(20, 24);
    display.print(msg);
    display.display();
}

void renderFrame(JsonDocument& doc) {
    display.clearDisplay();

    int heading = doc["h"] | 0;
    int pitch   = doc["p"] | 0;
    int ambient = doc["n"] | 0;
    JsonArray cone = doc["c"];

    // --- Header bar ---
    display.fillRect(0, 0, 128, 11, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK);
    display.setTextSize(1);
    display.setCursor(2, 2);
    display.print("HDG:");
    display.print(heading);
    display.print((char)247);   // degree symbol
    display.print("  AMB:");
    display.print(ambient);

    // --- Cone device list ---
    display.setTextColor(SSD1306_WHITE);
    int y     = 14;
    int count = 0;

    for (JsonObject dev : cone) {
        if (count >= 4) break;
        const char* manuf = dev["m"] | "---";
        int rssi          = dev["r"] | -99;
        int conf          = dev["d"] | 0;

        display.setTextSize(1);
        display.setCursor(0, y);
        display.print((char)16);    // ▶ right-pointing triangle
        display.print(manuf);

        display.setCursor(95, y);
        display.print(rssi);
        display.print("dB");

        y += 11;
        count++;
    }

    if (count == 0) {
        display.setTextSize(1);
        display.setCursor(14, 30);
        display.print("-- NO CONE TARGETS --");
    }

    // --- Pitch indicator (bottom-right) ---
    display.setTextSize(1);
    display.setCursor(100, 56);
    display.print("P:");
    display.print(pitch);

    display.display();
}

// ── Setup ─────────────────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);

    if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
        Serial.println("OLED init failed");
        for (;;);
    }
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    showStatus("BOOT");

    WiFi.begin(WIFI_SSID, WIFI_PASS);
    showStatus("WIFI...");
    while (WiFi.status() != WL_CONNECTED) delay(300);
    showStatus("LINKED");
    delay(400);
}

// ── Loop ──────────────────────────────────────────────────────────────────────

void loop() {
    if (!client.connected()) {
        display.clearDisplay();
        display.setTextSize(1);
        display.setTextColor(SSD1306_WHITE);
        display.setCursor(10, 28);
        display.print("Connecting...");
        display.display();

        client.connect(SERVER_HOST, SERVER_PORT);
        delay(RECONNECT_DELAY_MS);
        return;
    }

    if (client.available()) {
        String line = client.readStringUntil('\n');
        line.trim();

        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, line);

        if (!err) {
            renderFrame(doc);
        }
    }

    delay(LOOP_DELAY_MS);
}