#pragma once
#include <stdint.h>
/* A control page, not target DRAM traffic. 1=task begin, 2=verified task end.
 * Configurations using this header must map the marker page uncacheably.
 * Hosted programs enable it only when SS_METRICS_MARKERS is set by run_xpu.
 */
static inline void ss_metrics_mark(uint32_t marker) {
    *(volatile uint32_t*)(uintptr_t)0x70000000 = marker;
}
