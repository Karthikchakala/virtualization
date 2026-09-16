#define _GNU_SOURCE
#include "common_workload.h"
#include <sys/types.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    long iterations = 500000;
    long warmup = 10000;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--iterations") == 0 && i + 1 < argc) {
            iterations = atol(argv[++i]);
        } else if (strcmp(argv[i], "--warmup") == 0 && i + 1 < argc) {
            warmup = atol(argv[++i]);
        } else if (strcmp(argv[i], "--help") == 0) {
            printf("Usage: %s [--iterations N] [--warmup N]\n", argv[0]);
            return 0;
        }
    }

    if (iterations <= 0) iterations = 100000;
    if (warmup < 0) warmup = 0;

    uint64_t acc = 0;

    /* Warmup phase */
    for (long i = 0; i < warmup; i++) {
        pid_t pid = getpid();
        acc += (uint64_t)pid;
        PREVENT_OPTIMIZATION(&acc);
    }

    /* Measured phase */
    double t_start = get_time_sec();
    for (long i = 0; i < iterations; i++) {
        pid_t pid = getpid();
        acc += (uint64_t)pid;
        PREVENT_OPTIMIZATION(&acc);
    }
    double t_end = get_time_sec();
    double elapsed_sec = t_end - t_start;
    if (elapsed_sec <= 0.0) elapsed_sec = 0.000001;

    double ops_per_sec = (double)iterations / elapsed_sec;
    double latency_ns = (elapsed_sec * 1e9) / (double)iterations;

    uint64_t final_checksum = fnv1a_64(&acc, sizeof(acc));

    printf("{\n");
    printf("  \"workload\": \"syscall_deterministic\",\n");
    printf("  \"version\": \"1.0.0\",\n");
    printf("  \"parameters\": {\n");
    printf("    \"iterations\": %ld,\n", iterations);
    printf("    \"warmup\": %ld,\n", warmup);
    printf("    \"syscall\": \"getpid\"\n");
    printf("  },\n");
    printf("  \"results\": {\n");
    printf("    \"total_syscalls\": %ld,\n", iterations);
    printf("    \"elapsed_sec\": %.6f,\n", elapsed_sec);
    printf("    \"ops_per_sec\": %.2f,\n", ops_per_sec);
    printf("    \"latency_ns\": %.2f,\n", latency_ns);
    printf("    \"checksum\": \"0x%016" PRIx64 "\",\n", final_checksum);
    printf("    \"status\": \"success\"\n");
    printf("  }\n");
    printf("}\n");

    return 0;
}
