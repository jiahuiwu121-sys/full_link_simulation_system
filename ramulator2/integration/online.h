#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define SSR_ABI_VERSION 1
#if defined(__GNUC__)
#define SSR_EXPORT __attribute__((visibility("default")))
#else
#define SSR_EXPORT
#endif
typedef struct ssr_memory ssr_memory;
typedef struct {
    uint32_t abi_version, struct_bytes, transaction_bytes, channels;
    uint64_t period_fs, capacity_bytes, read_latency, write_latency;
} ssr_info;
/* kind=1: actual issue, kind=2: data service. Maintenance has token=0. */
typedef struct {
    uint32_t abi_version, struct_bytes, kind, write;
    uint64_t token, cycle, issue_cycle, address;
    int32_t channel, command, levels, coordinates[8];
    char command_name[24];
} ssr_event;
SSR_EXPORT ssr_memory* ssr_create(const char* expanded_config, uint32_t max_children,
                       uint32_t clock_scale, const char* result_dir);
SSR_EXPORT const char* ssr_error(void);
SSR_EXPORT int ssr_get_info(ssr_memory*, ssr_info*);
/* 1 accepted, 0 backpressure, -1 error. Full aligned transactions only. */
SSR_EXPORT int ssr_submit(ssr_memory*, uint64_t token, uint64_t address, uint32_t write);
SSR_EXPORT int ssr_step(ssr_memory*);
SSR_EXPORT int ssr_poll_event(ssr_memory*, ssr_event*);
SSR_EXPORT int ssr_is_idle(ssr_memory*);
SSR_EXPORT int ssr_finish(ssr_memory*);
SSR_EXPORT void ssr_destroy(ssr_memory*);
#ifdef __cplusplus
}
#endif
