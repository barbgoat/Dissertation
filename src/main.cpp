#include <Arduino.h>
#include <WiFi.h>

const char* SSID = "iPhone de Eduardo";
const char* PASS = "edu12345";

const char* HOST = "172.20.10.12";
const uint16_t PORT = 5000;

WiFiClient client;

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("BOOT");

  WiFi.mode(WIFI_STA);
  WiFi.begin(SSID, PASS);

  Serial.print("WiFi connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi OK");
  Serial.print("IP: ");
  Serial.println(WiFi.localIP());

  Serial.print("Connecting TCP...");
  if (client.connect(HOST, PORT)) {
    Serial.println("OK");
    client.println("{\"devaddr\":1,\"payload\":\"hello\",\"tx_end_ts\":123}");
  } else {
    Serial.println("FAIL");
  }
}

void loop() {
  if (!client.connected()) return;

  if (client.available()) {
    String line = client.readStringUntil('\n');
    line.trim();
    if (line.length()) {
      Serial.print("RX: ");
      Serial.println(line);
    }
  }
}