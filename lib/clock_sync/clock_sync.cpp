#include "clock_sync.h"

static int64_t offset_us = 0;

void clock_sync_update(uint64_t gw_ts, uint64_t rx_local_ts) {
    offset_us = (int64_t)gw_ts - (int64_t)rx_local_ts;
}

uint64_t clock_sync_now() {
    return (uint64_t)micros() + offset_us;
}