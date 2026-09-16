/*
 * memory_workload.c - Deterministic, intensive memory benchmarking workload.
 *
 * Implements deterministic sequential write, read-accumulate, and stride access
 * across a dynamically allocated memory buffer. Enforces host memory safety
 * boundaries and releases all allocated resources cleanly upon completion.
 */

#include "common_workload.h"

#define WORKLOAD_VERSION "1.0.0"
#define DEFAULT_BUFFER_MB 128
#define DEFAULT_PASSES 4
#define DEFAULT_STRIDE 64
#define MAX_BUFFER_MB 4096
#define MAX_PASSES 100

int main(int argc, char *argv[]) {
    int buffer_mb = DEFAULT_BUFFER_MB;
    int passes = DEFAULT_PASSES;
    int stride = DEFAULT_STRIDE;

    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--buffer-mb") == 0 && i + 1 < argc) {
            buffer_mb = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--passes") == 0 && i + 1 < argc) {
            passes = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--stride") == 0 && i + 1 < argc) {
            stride = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            fprintf(stdout, "Usage: %s [options]\n", argv[0]);
            fprintf(stdout, "Options:\n");
            fprintf(stdout, "  --buffer-mb <N>    Buffer size in MB (default: %d, max: %d)\n", DEFAULT_BUFFER_MB, MAX_BUFFER_MB);
            fprintf(stdout, "  --passes <P>       Read/Write passes (default: %d, max: %d)\n", DEFAULT_PASSES, MAX_PASSES);
            fprintf(stdout, "  --stride <S>       Stride step in bytes (default: %d)\n", DEFAULT_STRIDE);
            return 0;
        } else {
            fprintf(stderr, "{\"error\": \"Unknown argument: %s\", \"status\": \"failed\"}\n", argv[i]);
            return 1;
        }
    }

    /* Input validation */
    if (buffer_mb <= 0 || buffer_mb > MAX_BUFFER_MB) {
        fprintf(stderr, "{\"error\": \"Invalid buffer_mb: %d. Allowed range: 1..%d\", \"status\": \"failed\"}\n", buffer_mb, MAX_BUFFER_MB);
        return 1;
    }
    if (passes <= 0 || passes > MAX_PASSES) {
        fprintf(stderr, "{\"error\": \"Invalid passes: %d. Allowed range: 1..%d\", \"status\": \"failed\"}\n", passes, MAX_PASSES);
        return 1;
    }
    if (stride < (int)sizeof(uint64_t) || stride > 65536) {
        fprintf(stderr, "{\"error\": \"Invalid stride: %d. Allowed range: %zu..65536\", \"status\": \"failed\"}\n", stride, sizeof(uint64_t));
        return 1;
    }

    /* Host Safety Guard: Check available memory to avoid OOM or destabilization */
    size_t avail_mb = get_available_memory_mb();
    if ((size_t)buffer_mb > (avail_mb * 8) / 10) {
        fprintf(stderr, "{\"error\": \"Requested buffer (%d MB) exceeds 80%% of available RAM (%zu MB). Safety guard abort.\", \"status\": \"failed\"}\n", buffer_mb, avail_mb);
        return 3;
    }

    size_t total_bytes = (size_t)buffer_mb * 1024 * 1024;
    size_t num_words = total_bytes / sizeof(uint64_t);
    size_t stride_words = (size_t)stride / sizeof(uint64_t);
    if (stride_words == 0) stride_words = 1;

    uint64_t *buffer = (uint64_t *)malloc(total_bytes);
    if (!buffer) {
        fprintf(stderr, "{\"error\": \"Failed to allocate %d MB buffer\", \"status\": \"failed\"}\n", buffer_mb);
        return 2;
    }

    double t_start = get_time_sec();
    uint64_t accumulator = 0;

    for (int p = 0; p < passes; ++p) {
        uint64_t pass_seed = ((uint64_t)(p + 1) * 0x9e3779b97f4a7c15ULL);

        /* 1. Deterministic Write Pass */
        for (size_t i = 0; i < num_words; ++i) {
            buffer[i] = pass_seed + (uint64_t)i;
        }
        PREVENT_OPTIMIZATION(buffer);

        /* 2. Sequential Read & Accumulate Pass */
        for (size_t i = 0; i < num_words; ++i) {
            accumulator ^= buffer[i] + (uint64_t)i;
        }
        PREVENT_OPTIMIZATION(&accumulator);

        /* 3. Stride Access Pass */
        for (size_t i = 0; i < num_words; i += stride_words) {
            accumulator += buffer[i];
            buffer[i] ^= (accumulator >> 17);
        }
        PREVENT_OPTIMIZATION(buffer);
    }

    double elapsed_sec = get_time_sec() - t_start;

    /* Total transferred: (writes + reads + stride touches) */
    double write_bytes = (double)total_bytes * (double)passes;
    double read_bytes = (double)total_bytes * (double)passes;
    double stride_bytes = ((double)num_words / (double)stride_words) * sizeof(uint64_t) * 2.0 * (double)passes;
    double total_transferred = write_bytes + read_bytes + stride_bytes;

    double throughput_mb_s = (elapsed_sec > 0.0) ? ((total_transferred / (1024.0 * 1024.0)) / elapsed_sec) : 0.0;

    /* Compute deterministic 64-bit checksum combining buffer hash and accumulator */
    size_t sample_bytes = (total_bytes > (1024 * 1024)) ? (1024 * 1024) : total_bytes;
    uint64_t checksum = fnv1a_64(buffer, sample_bytes) ^ accumulator;

    /* Machine-readable JSON output */
    printf("{\n");
    printf("  \"workload\": \"memory_deterministic\",\n");
    printf("  \"version\": \"%s\",\n", WORKLOAD_VERSION);
    printf("  \"parameters\": {\n");
    printf("    \"buffer_mb\": %d,\n", buffer_mb);
    printf("    \"passes\": %d,\n", passes);
    printf("    \"stride_bytes\": %d\n", stride);
    printf("  },\n");
    printf("  \"results\": {\n");
    printf("    \"allocated_bytes\": %zu,\n", total_bytes);
    printf("    \"transferred_bytes\": %.0f,\n", total_transferred);
    printf("    \"elapsed_sec\": %.6f,\n", elapsed_sec);
    printf("    \"throughput_mb_s\": %.2f,\n", throughput_mb_s);
    printf("    \"checksum\": \"0x%016" PRIx64 "\",\n", checksum);
    printf("    \"status\": \"success\"\n");
    printf("  }\n");
    printf("}\n");

    /* Release memory safely */
    free(buffer);
    return 0;
}
