#if defined(ARDUINO_ARCH_ESP32)
#include <WiFi.h>
#elif defined(ARDUINO_UNOR4_WIFI)
#include <WiFiS3.h>
#else
#include <WiFi.h>
#endif

const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* PHANTOM_HOST = "192.168.1.50";
const uint16_t PHANTOM_PORT = 8790;
const char* PHANTOM_TOKEN = "phantom";

// For microcontroller-friendly presets the bridge exposes /preset/<name> endpoints
// We use the "quick" preset which requires no JSON body.
const char* COMMAND_JSON = "";

WiFiClient client;

String httpRequest(const char* method, const String& path, const String& body = "") {
  if (!client.connect(PHANTOM_HOST, PHANTOM_PORT)) {
    return "";
  }

  client.print(String(method) + " " + path + " HTTP/1.1\r\n");
  client.print(String("Host: ") + PHANTOM_HOST + ":" + String(PHANTOM_PORT) + "\r\n");
  client.print("Connection: close\r\n");
  client.print(String("X-Phantom-Token: ") + PHANTOM_TOKEN + "\r\n");
  if (body.length() > 0) {
    client.print("Content-Type: application/json\r\n");
    client.print(String("Content-Length: ") + String(body.length()) + "\r\n");
  }
  client.print("\r\n");
  if (body.length() > 0) {
    client.print(body);
  }

  String response;
  unsigned long deadline = millis() + 8000;
  while (client.connected() && millis() < deadline) {
    while (client.available()) {
      response += char(client.read());
    }
    delay(10);
  }
  while (client.available()) {
    response += char(client.read());
  }
  client.stop();

  int separator = response.indexOf("\r\n\r\n");
  if (separator >= 0) {
    return response.substring(separator + 4);
  }
  return response;
}

String extractJsonString(const String& json, const char* key) {
  String pattern = String("\"") + key + "\":\"";
  int start = json.indexOf(pattern);
  if (start < 0) {
    return "";
  }
  start += pattern.length();
  int end = json.indexOf('"', start);
  if (end < 0) {
    return "";
  }
  return json.substring(start, end);
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print('.');
  }
  Serial.println();
  Serial.print("Connected. IP: ");
  Serial.println(WiFi.localIP());
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  connectWifi();

  // Use the compact /preset/quick endpoint (no body) for board-friendly invocation
  String queued = httpRequest("POST", "/preset/quick");
  Serial.println("Queue response:");
  Serial.println(queued);

  String jobId = extractJsonString(queued, "job_id");
  if (jobId.length() == 0) {
    Serial.println("No job_id returned; stopping.");
    return;
  }

  Serial.print("Polling job: ");
  Serial.println(jobId);
  String jobPath = String("/job/") + jobId;

  for (int attempt = 0; attempt < 120; ++attempt) {
    String job = httpRequest("GET", jobPath);
    Serial.println(job);
    if (job.indexOf("\"status\":\"done\"") >= 0 || job.indexOf("\"status\":\"failed\"") >= 0) {
      Serial.println("Job finished.");
      break;
    }
    delay(1000);
  }
}

void loop() {
  delay(1000);
}
