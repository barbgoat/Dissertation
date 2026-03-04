// src/main.cpp
#include <Arduino.h>
#include "tslora_node.h"

void setup() {
  Serial.begin(115200);
  delay(300);

  // Inicializa Wi-Fi/TCP e estado TS-LoRa (tudo dentro do tslora_node)
  tslora_init();
}

void loop() {
  // Executa a máquina de estados TS-LoRa (RX beacon/sack, agendamento e TX UL)
  tslora_update();

  // Pequena cedência para evitar busy-loop (mantém boa prática no ESP32)
  delay(1);
}