#include "slot_calc.h"

uint8_t calculate_slot(uint32_t devaddr, uint8_t num_slots) {
    return devaddr % num_slots;
}

uint64_t slot_start_time(uint64_t sf_start, uint8_t slot, uint32_t slot_duration_ms) {
    return sf_start + (uint64_t)slot * slot_duration_ms * 1000ULL;
}