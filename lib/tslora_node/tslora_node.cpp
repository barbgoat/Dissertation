#include "tslora_node.h"
#include <ArduinoJson.h>
#include "clock_sync.h"
#include "slot_calc.h"

#define DEVADDR       1
#define NUM_SLOTS     8
#define SLOT_DURATION_MS 1000

// ── Novo: offset fixo de 100 ms (em microsegundos) ──────────────────────────
#define TX_OFFSET_US  100000ULL   // 100 ms

enum State {
    WAIT_BEACON,
    WAIT_SLOT,
    WAIT_SACK
};

static State    state              = WAIT_BEACON;
static uint64_t superframe_start   = 0;
static uint8_t  my_slot            = 0;

// ── Guarda o instante-alvo calculado para o log de erro ─────────────────────
static uint64_t tx_target_us       = 0;   // em tempo de rede (us)

// ────────────────────────────────────────────────────────────────────────────
static void send_uplink() {

    uint64_t tx_real = clock_sync_now();          // timestamp real (rede)
    int64_t  error   = (int64_t)tx_real
                     - (int64_t)tx_target_us;     // pode ser negativo

    // ── Log pedido ──────────────────────────────────────────────────────────
    Serial.print("LOG: TX_TARGET(us)=");
    Serial.print(tx_target_us);
    Serial.print(" TX_REAL(us)=");
    Serial.print(tx_real);
    Serial.print(" TX_ERROR(us)=");
    Serial.println(error);

    // ── Log original (mantido) ──────────────────────────────────────────────
    Serial.print("LOG: TX about to send | local(us)=");
    Serial.print((uint64_t)micros());
    Serial.print(" net(us)=");
    Serial.println(tx_real);

    JsonDocument doc;
    doc["devaddr"]   = DEVADDR;
    doc["payload"]   = "hello";
    doc["tx_end_ts"] = (uint64_t)micros();

    serializeJson(doc, Serial);
    Serial.println();
}

// ────────────────────────────────────────────────────────────────────────────
static void handle_beacon(JsonDocument &doc) {

    if (!doc["gw_ts"].is<uint64_t>())
        return;

    uint64_t gw_ts   = doc["gw_ts"].as<uint64_t>();
    uint64_t local_rx = (uint64_t)micros();

    Serial.print("LOG: Beacon RX | local(us)=");
    Serial.print(local_rx);
    Serial.print(" gw_ts(us)=");
    Serial.println(gw_ts);

    clock_sync_update(gw_ts, local_rx);

    // beacon_reference_time = instante de rede após sincronização
    uint64_t beacon_reference_time = clock_sync_now();

    superframe_start = beacon_reference_time;

    // ── Offset fixo: slot ignorado temporariamente ───────────────────────────
    // my_slot = calculate_slot(DEVADDR, NUM_SLOTS);  // suspenso
    my_slot   = 0;                                    // slot fixo (irrelevante)

    tx_target_us = beacon_reference_time + TX_OFFSET_US;

    Serial.print("LOG: Sync applied | net_now(us)=");
    Serial.print(beacon_reference_time);
    Serial.print(" tx_target(us)=");
    Serial.println(tx_target_us);

    state = WAIT_SLOT;
}

// ────────────────────────────────────────────────────────────────────────────
static void handle_sack(JsonDocument &doc) {

    if (!doc["acked_nodes"].is<JsonArray>())
        return;

    JsonArray arr      = doc["acked_nodes"].as<JsonArray>();
    bool      acked_me = false;

    for (JsonVariant v : arr) {
        if (v.as<uint32_t>() == DEVADDR) {
            acked_me = true;
            break;
        }
    }

    Serial.print("LOG: SACK RX | acked_me=");
    Serial.println(acked_me ? "yes" : "no");

    if (acked_me)
        state = WAIT_BEACON;
}

// ────────────────────────────────────────────────────────────────────────────
void tslora_init() {
    state = WAIT_BEACON;
}

void tslora_update() {

    // ── RX ──────────────────────────────────────────────────────────────────
    if (Serial.available()) {

        String line = Serial.readStringUntil('\n');
        line.trim();

        if (line.length() > 0) {

            JsonDocument doc;
            DeserializationError err = deserializeJson(doc, line);

            if (!err) {
                if (doc["gw_ts"].is<uint64_t>())
                    handle_beacon(doc);
                else if (doc["acked_nodes"].is<JsonArray>())
                    handle_sack(doc);
            }
        }
    }

    // ── State Machine ────────────────────────────────────────────────────────
    if (state == WAIT_SLOT) {

        // Condição: clock de rede atingiu o instante-alvo
        if (clock_sync_now() >= tx_target_us) {
            send_uplink();
            state = WAIT_SACK;
        }
    }
}