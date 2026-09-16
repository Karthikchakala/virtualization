/*
 * memory_workload.c - Deterministic memory throughput & bandwidth workload.
 * 
 * Allocates a fixed buffer size and executes deterministic sequential read/write
 * and stride access passes. Zero fabricated metrics, zero random numbers.
 */

#define _POSIX_C_SOURCE 199309L
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>

#define DEFAULT_BUFFER_MB 128
#define DEFAULT_PASSES 4

static inline double get_monotonic_time_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static uint32_t fnv1a_hash(const void *data, size_t len) {
    const uint8_t *bytes = (const uint8_t *)data;
    uint32_t hash = 2166136261u;
    for (size_t i = 0; i < len; ++i) {
        hash ^= bytes[i];
        hash *= 16777619u;
    }
    return hash;
}

int main(int argc, char *argv[]) {
    int buffer_mb = DEFAULT_BUFFER_MB;
    int passes = DEFAULT_PASSES;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--buffer-mb") == 0 && i + 1 < argc) {
            buffer_mb = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--passes") == 0 && i + 1 < argc) {
            passes = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--help") == 0) {
            fprintf(stderr, "Usage: %s [--buffer-mb <N>] [--passes <P>]\n", argv[0]);
            return 0;
        }
    }

    if (buffer_mb <= 0 || buffer_mb > 2048) buffer_mb = DEFAULT_BUFFER_MB;
    if (passes <= 0 || passes > 50) passes = DEFAULT_PASSES;

    size_t total_bytes = (size_t)buffer_mb * 1024 * 1024;
    size_t num_words = total_bytes / sizeof(uint64_t);

    uint64_t *buffer = (uint64_t *)malloc(total_bytes);
    if (!buffer) {
        fprintf(stderr, "{\"error\": \"Buffer allocation failed\"}\n");
        return 1;
    }

    double start_time = get_monotonic_time_sec();

    /* Deterministic write phase */
    for (int p = 0; p < passes; ++p) {
        uint64_t seed = (uint64_t)(p + 1) * 0x517cc1b727220a95ULL;
        for (size_t i = 0; i < num_words; ++i) {
            buffer[i] = seed + (uint64_t)i;
        }
    }

    /* Deterministic read and accumulate phase */
    uint64_t accumulator = 0;
    for (int p = 0; p < passes; ++p) {
        for (size_t i = 0; i < num_words; ++i) {
            accumulator ^= buffer[i];
        }
    }

    double end_time = get_monotonic_time_sec();
    double elapsed_sec = end_time - start_time;

    /* Total transferred: (writes + reads) = 2 * buffer_bytes * passes */
    double total_transferred_bytes = 2.0 * (double)total_bytes * (double)passes;
    double throughput_mb_s = (elapsed_sec > 0.0) ? (total_transferred_bytes / (1024.0 * 1024.0)) / elapsed_sec : 0.0;
    uint32_t checksum = fnv1a_hash(buffer, (total_bytes > 65536) ? 65536 : total_bytes) ^ (uint32_t)(accumulator & 0xFFFFFFFF);

    printf("{\n");
    printf("  \"workload\": \"memory_deterministic\",\n");
    printf("  \"buffer_mb\": %d,\n", buffer_mb);
    printf("  \"passes\": %d,\n", passes);
    printf("  \"total_transferred_bytes\": %.0f,\n", total_transferred_bytes);
    printf("  \"elapsed_sec\": %.6f,\n", elapsed_sec);
    printf("  \"throughput_mb_s\": %.2f,\n", throughput_mb_s);
    printf("  \"checksum\": \"0x%08x\",\n", checksum);
    printf("  \"status\": \"success\"\n");
    printf("}\n");

    free(buffer);
    return 0;
}
