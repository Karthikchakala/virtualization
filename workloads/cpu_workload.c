/*
 * cpu_workload.c - Deterministic CPU-bound benchmarking workload.
 * 
 * Computes deterministic integer and floating point matrix operations and 
 * polynomial iterations. Guarantees 100% reproducible results for identical inputs.
 * Zero fabricated data, zero random seeds.
 */

#define _POSIX_C_SOURCE 199309L
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <math.h>

#define DEFAULT_SIZE 400
#define DEFAULT_ITERATIONS 5

static inline double get_monotonic_time_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

/* Simple 32-bit FNV-1a checksum for validation */
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
    int size = DEFAULT_SIZE;
    int iterations = DEFAULT_ITERATIONS;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--size") == 0 && i + 1 < argc) {
            size = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--iterations") == 0 && i + 1 < argc) {
            iterations = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--help") == 0) {
            fprintf(stderr, "Usage: %s [--size <N>] [--iterations <I>]\n", argv[0]);
            return 0;
        }
    }

    if (size <= 0 || size > 2000) size = DEFAULT_SIZE;
    if (iterations <= 0 || iterations > 100) iterations = DEFAULT_ITERATIONS;

    size_t total_elements = (size_t)size * (size_t)size;
    double *A = (double *)malloc(total_elements * sizeof(double));
    double *B = (double *)malloc(total_elements * sizeof(double));
    double *C = (double *)malloc(total_elements * sizeof(double));

    if (!A || !B || !C) {
        fprintf(stderr, "{\"error\": \"Memory allocation failed\"}\n");
        free(A); free(B); free(C);
        return 1;
    }

    /* Initialize with deterministic values */
    for (size_t i = 0; i < total_elements; ++i) {
        A[i] = sin((double)(i % 360) * 0.017453292519943295);
        B[i] = cos((double)(i % 360) * 0.017453292519943295);
        C[i] = 0.0;
    }

    double start_time = get_monotonic_time_sec();

    for (int iter = 0; iter < iterations; ++iter) {
        for (int i = 0; i < size; ++i) {
            for (int k = 0; k < size; ++k) {
                double a_ik = A[i * size + k];
                for (int j = 0; j < size; ++j) {
                    C[i * size + j] += a_ik * B[k * size + j];
                }
            }
        }
    }

    double end_time = get_monotonic_time_sec();
    double elapsed_sec = end_time - start_time;

    uint32_t checksum = fnv1a_hash(C, total_elements * sizeof(double));

    /* Total floating-point ops: 2 * size^3 * iterations */
    double total_flops = 2.0 * (double)size * (double)size * (double)size * (double)iterations;
    double gflops = (elapsed_sec > 0.0) ? (total_flops / elapsed_sec / 1e9) : 0.0;

    printf("{\n");
    printf("  \"workload\": \"cpu_deterministic\",\n");
    printf("  \"matrix_size\": %d,\n", size);
    printf("  \"iterations\": %d,\n", iterations);
    printf("  \"total_flops\": %.0f,\n", total_flops);
    printf("  \"elapsed_sec\": %.6f,\n", elapsed_sec);
    printf("  \"gflops\": %.4f,\n", gflops);
    printf("  \"checksum\": \"0x%08x\",\n", checksum);
    printf("  \"status\": \"success\"\n");
    printf("}\n");

    free(A);
    free(B);
    free(C);
    return 0;
}
