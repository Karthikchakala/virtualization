#ifndef COMMON_WORKLOAD_H
#define COMMON_WORKLOAD_H

#define _GNU_SOURCE
#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <inttypes.h>
#include <string.h>
#include <time.h>
#include <math.h>
#include <unistd.h>
#include <sys/sysinfo.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846264338327950288
#endif

/* Compiler memory barrier to prevent optimization elimination */
#define PREVENT_OPTIMIZATION(ptr) __asm__ __volatile__("" : : "g"(ptr) : "memory")

/* High-precision monotonic timer in fractional seconds */
static inline double get_time_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

/* 64-bit FNV-1a Hash */
static inline uint64_t fnv1a_64(const void *data, size_t len) {
    const uint8_t *bytes = (const uint8_t *)data;
    uint64_t hash = 14695981039346656037ULL;
    for (size_t i = 0; i < len; ++i) {
        hash ^= bytes[i];
        hash *= 1099511628211ULL;
    }
    return hash;
}

/* 32-bit FNV-1a Hash */
static inline uint32_t fnv1a_32(const void *data, size_t len) {
    const uint8_t *bytes = (const uint8_t *)data;
    uint32_t hash = 2166136261U;
    for (size_t i = 0; i < len; ++i) {
        hash ^= bytes[i];
        hash *= 16777619U;
    }
    return hash;
}

/* Retrieve available host RAM in Megabytes safely */
static inline size_t get_available_memory_mb(void) {
    struct sysinfo si;
    if (sysinfo(&si) == 0) {
        unsigned long long avail_bytes = (unsigned long long)si.freeram * si.mem_unit;
        return (size_t)(avail_bytes / (1024 * 1024));
    }
    return 1024;
}

#endif /* COMMON_WORKLOAD_H */
