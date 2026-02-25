#ifndef CLOCK_SYNC_H
#define CLOCK_SYNC_H

#include <Arduino.h>

void clock_sync_update(uint64_t gw_ts, uint64_t rx_local_ts);
uint64_t clock_sync_now();

#endif