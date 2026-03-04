#include "tslora_node.h"

#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoJson.h>

#include "clock_sync.h"
#include "slot_calc.h"
#include <secrets.h>

#define DEVADDR            1
#define NUM_SLOTS          8
#define SLOT_DURATION_MS   1000

// Offset dentro do slot (100 ms)
#define OFFSET_IN_SLOT_US  100000ULL

// (opcional) guard time dentro do slot
#define GUARD_TIME_US 10000ULL   // 10 ms

enum State { WAIT_BEACON, WAIT_TX, WAIT_SACK };
static State state = WAIT_BEACON;

static WiFiClient client;

static uint64_t sf_start_us    = 0;   // início do SF (tempo de rede)
static uint8_t  my_slot        = 0;
static uint64_t slot_start_us  = 0;
static uint64_t tx_target_us   = 0;

// ---------------- TCP / Wi-Fi ----------------
static void ensure_wifi_tcp() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);

    Serial.print("LOG: WiFi connecting");
    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - t0) < 15000) {
      delay(300);
      Serial.print(".");
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED) {
      Serial.print("LOG: WiFi OK IP=");
      Serial.println(WiFi.localIP());
    } else {
      Serial.println("LOG: WiFi FAIL");
      return;
    }
  }

  if (!client.connected()) {
    Serial.print("LOG: TCP connect ");
    Serial.print(GW_IP);
    Serial.print(":");
    Serial.println(GW_PORT);

    client.stop();
    if (client.connect(GW_IP, GW_PORT)) {
      Serial.println("LOG: TCP OK");
    } else {
      Serial.println("LOG: TCP FAIL");
    }
  }
}

static bool tcp_read_line(String &out) {
  if (!client.connected()) return false;
  if (!client.available()) return false;
  out = client.readStringUntil('\n');
  out.trim();
  return out.length() > 0;
}

static void tcp_send_json(const JsonDocument &doc) {
  if (!client.connected()) return;
  String out;
  serializeJson(doc, out);
  client.print(out);
  client.print('\n');
}

// ---------------- TS-LoRa ----------------
static void send_uplink() {
  const uint64_t tx_real_us = clock_sync_now(); // timestamp de quando a transmissão começa (tempo sincronizado)
  const int64_t error_us    = (int64_t)tx_real_us - (int64_t)tx_target_us;  // positivo = atrasado, negativo = adiantado


  JsonDocument doc;
  doc["devaddr"]   = DEVADDR;
  doc["payload"]   = "hello";
  doc["tx_end_ts"] = (uint64_t)tx_real_us;  // timestamp de quando a transmissão acabou (tempo local)

  tcp_send_json(doc);

  Serial.print("LOG: SF_START(us)=");   Serial.print(sf_start_us);
  Serial.print(" SLOT=");              Serial.print(my_slot);
  Serial.print(" SLOT_START(us)=");    Serial.print(slot_start_us);
  Serial.print(" OFFSET(us)=");        Serial.print((uint64_t)(GUARD_TIME_US + OFFSET_IN_SLOT_US));
  Serial.print(" TX_TARGET(us)=");     Serial.print(tx_target_us);
  Serial.print(" TX_REAL(us)=");       Serial.print(tx_real_us);
  Serial.print(" TX_ERROR(us)=");      Serial.println(error_us);
}

static void handle_beacon(JsonDocument &doc) {
  if (!doc["gw_ts"].is<uint64_t>()) return;

  const uint64_t gw_ts_us    = doc["gw_ts"].as<uint64_t>();  // tempo do gateway (assumir início SF)
  const uint64_t local_rx_us = (uint64_t)micros();

  Serial.print("LOG: Beacon RX | local(us)="); Serial.print(local_rx_us);
  Serial.print(" gw_ts(us)=");                 Serial.println(gw_ts_us);

  // Atualiza sincronização (mapeia local<->gateway)
  clock_sync_update(gw_ts_us, local_rx_us);

  // MODELO HÍBRIDO CORRETO:
  // SF_start em tempo de rede vem do próprio gw_ts (não de clock_sync_now())
  sf_start_us = gw_ts_us;

  my_slot = calculate_slot((uint32_t)DEVADDR, (uint8_t)NUM_SLOTS);

  slot_start_us = slot_start_time(sf_start_us, my_slot, (uint32_t)SLOT_DURATION_MS);

  tx_target_us = slot_start_us + GUARD_TIME_US + OFFSET_IN_SLOT_US;

  Serial.print("LOG: Sync applied | SF_START(us)="); Serial.print(sf_start_us);
  Serial.print(" slot=");                            Serial.print(my_slot);
  Serial.print(" slot_start(us)=");                  Serial.print(slot_start_us);
  Serial.print(" tx_target(us)=");                   Serial.println(tx_target_us);

  state = WAIT_TX;
}

static void handle_sack(JsonDocument &doc) {
  if (!doc["acked_nodes"].is<JsonArray>()) return;

  JsonArray arr = doc["acked_nodes"].as<JsonArray>();
  bool acked_me = false;

  for (JsonVariant v : arr) {
    if (v.as<uint32_t>() == (uint32_t)DEVADDR) { acked_me = true; break; }
  }

  Serial.print("LOG: SACK RX | acked_me=");
  Serial.println(acked_me ? "yes" : "no");

  state = WAIT_BEACON;
}

void tslora_init() {
  state = WAIT_BEACON;
  sf_start_us = 0;
  my_slot = 0;
  slot_start_us = 0;
  tx_target_us = 0;

  ensure_wifi_tcp();
}

void tslora_update() {
  ensure_wifi_tcp();

  // RX via TCP (beacon/sack)
  String line;
  if (tcp_read_line(line)) {
    JsonDocument doc;
    if (deserializeJson(doc, line) == DeserializationError::Ok) {

      // BEACON
      if (doc["gw_ts"].is<uint64_t>()) {
        handle_beacon(doc);
      }
      // SACK (ignorar se ainda estamos à espera de beacon)
      else if (doc["acked_nodes"].is<JsonArray>()) {
        if (state != WAIT_BEACON) {
          handle_sack(doc);
        } else {
          // SACK antigo/fora de contexto (ex.: buffer TCP no arranque)
          Serial.println("LOG: SACK ignored (WAIT_BEACON)");
        }
      }
    }
  }

  // Espera pelo alvo e transmite
  if (state == WAIT_TX) {
    if (clock_sync_now() >= tx_target_us) {
      send_uplink();
      state = WAIT_SACK;
    }
  }
}