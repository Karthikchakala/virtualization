#define _GNU_SOURCE
#include "common_workload.h"
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    long iterations = 50000;
    long warmup = 5000;

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

    if (iterations <= 0) iterations = 10000;
    if (warmup < 0) warmup = 0;

    int p1[2], p2[2];
    if (pipe(p1) < 0 || pipe(p2) < 0) {
        perror("pipe");
        return 1;
    }

    pid_t pid = fork();
    if (pid < 0) {
        perror("fork");
        return 1;
    }

    if (pid == 0) {
        /* Child process: reads p1, writes p2 */
        close(p1[1]);
        close(p2[0]);
        char token = 0;
        long total = warmup + iterations;
        for (long i = 0; i < total; i++) {
            if (read(p1[0], &token, 1) != 1) break;
            token++;
            if (write(p2[1], &token, 1) != 1) break;
        }
        close(p1[0]);
        close(p2[1]);
        _exit(0);
    } else {
        /* Parent process: writes p1, reads p2 */
        close(p1[0]);
        close(p2[1]);
        char token = 1;
        uint64_t hash_acc = 0;

        /* Warmup */
        for (long i = 0; i < warmup; i++) {
            if (write(p1[1], &token, 1) != 1) break;
            if (read(p2[0], &token, 1) != 1) break;
            hash_acc += (uint64_t)token;
        }

        /* Measured */
        double t_start = get_time_sec();
        for (long i = 0; i < iterations; i++) {
            if (write(p1[1], &token, 1) != 1) break;
            if (read(p2[0], &token, 1) != 1) break;
            hash_acc += (uint64_t)token;
        }
        double t_end = get_time_sec();
        double elapsed_sec = t_end - t_start;
        if (elapsed_sec <= 0.0) elapsed_sec = 0.000001;

        close(p1[1]);
        close(p2[0]);
        waitpid(pid, NULL, 0);

        long total_switches = iterations * 2; /* 2 context switches per round trip */
        double switches_per_sec = (double)total_switches / elapsed_sec;
        double latency_us = (elapsed_sec * 1e6) / (double)total_switches;

        uint64_t final_checksum = fnv1a_64(&hash_acc, sizeof(hash_acc));

        printf("{\n");
        printf("  \"workload\": \"scheduling_deterministic\",\n");
        printf("  \"version\": \"1.0.0\",\n");
        printf("  \"parameters\": {\n");
        printf("    \"iterations\": %ld,\n", iterations);
        printf("    \"warmup\": %ld,\n", warmup);
        printf("    \"mechanism\": \"pipe_ping_pong\"\n");
        printf("  },\n");
        printf("  \"results\": {\n");
        printf("    \"total_context_switches\": %ld,\n", total_switches);
        printf("    \"elapsed_sec\": %.6f,\n", elapsed_sec);
        printf("    \"switches_per_sec\": %.2f,\n", switches_per_sec);
        printf("    \"latency_us\": %.3f,\n", latency_us);
        printf("    \"checksum\": \"0x%016" PRIx64 "\",\n", final_checksum);
        printf("    \"status\": \"success\"\n");
        printf("  }\n");
        printf("}\n");

        return 0;
    }
}
