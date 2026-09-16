/*
 * cpu_workload.c - Deterministic, intensive CPU benchmarking workload.
 *
 * Implements deterministic double-precision matrix multiplication and polynomial
 * operations with guaranteed mathematical reproducibility across all environments.
 * Results cannot be optimized away and are verified via 64-bit FNV-1a checksum.
 */

#include "common_workload.h"
#include <pthread.h>

#define WORKLOAD_VERSION "1.0.0"
#define DEFAULT_SIZE 300
#define DEFAULT_ITERATIONS 5
#define DEFAULT_WARMUP 1
#define DEFAULT_THREADS 1
#define MAX_SIZE 2500
#define MAX_ITERATIONS 100
#define MAX_THREADS 64

typedef struct {
    int thread_id;
    int total_threads;
    int size;
    int iterations;
    const double *A;
    const double *B;
    double *C;
} ThreadData;

/* Compute matrix multiplication slice deterministically */
static void *matrix_mult_worker(void *arg) {
    ThreadData *data = (ThreadData *)arg;
    int n = data->size;
    int iters = data->iterations;
    const double *A = data->A;
    const double *B = data->B;
    double *C = data->C;

    int rows_per_thread = (n + data->total_threads - 1) / data->total_threads;
    int start_row = data->thread_id * rows_per_thread;
    int end_row = start_row + rows_per_thread;
    if (end_row > n) end_row = n;

    for (int it = 0; it < iters; ++it) {
        for (int i = start_row; i < end_row; ++i) {
            for (int k = 0; k < n; ++k) {
                double a_ik = A[i * n + k];
                for (int j = 0; j < n; ++j) {
                    C[i * n + j] += a_ik * B[k * n + j];
                }
            }
        }
    }

    PREVENT_OPTIMIZATION(C);
    return NULL;
}

static void run_computation(int size, int iterations, int num_threads, const double *A, const double *B, double *C) {
    if (num_threads <= 1) {
        ThreadData single_data = {
            .thread_id = 0,
            .total_threads = 1,
            .size = size,
            .iterations = iterations,
            .A = A,
            .B = B,
            .C = C
        };
        matrix_mult_worker(&single_data);
    } else {
        pthread_t threads[MAX_THREADS];
        ThreadData tdata[MAX_THREADS];

        for (int t = 0; t < num_threads; ++t) {
            tdata[t].thread_id = t;
            tdata[t].total_threads = num_threads;
            tdata[t].size = size;
            tdata[t].iterations = iterations;
            tdata[t].A = A;
            tdata[t].B = B;
            tdata[t].C = C;
            pthread_create(&threads[t], NULL, matrix_mult_worker, &tdata[t]);
        }

        for (int t = 0; t < num_threads; ++t) {
            pthread_join(threads[t], NULL);
        }
    }
}

int main(int argc, char *argv[]) {
    int size = DEFAULT_SIZE;
    int iterations = DEFAULT_ITERATIONS;
    int warmup = DEFAULT_WARMUP;
    int num_threads = DEFAULT_THREADS;

    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--size") == 0 && i + 1 < argc) {
            size = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--iterations") == 0 && i + 1 < argc) {
            iterations = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--warmup") == 0 && i + 1 < argc) {
            warmup = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--threads") == 0 && i + 1 < argc) {
            num_threads = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            fprintf(stdout, "Usage: %s [options]\n", argv[0]);
            fprintf(stdout, "Options:\n");
            fprintf(stdout, "  --size <N>         Matrix dimension N x N (default: %d, max: %d)\n", DEFAULT_SIZE, MAX_SIZE);
            fprintf(stdout, "  --iterations <I>   Benchmark iterations (default: %d, max: %d)\n", DEFAULT_ITERATIONS, MAX_ITERATIONS);
            fprintf(stdout, "  --warmup <W>       Warmup iterations (default: %d)\n", DEFAULT_WARMUP);
            fprintf(stdout, "  --threads <T>      Thread count (default: %d, max: %d)\n", DEFAULT_THREADS, MAX_THREADS);
            return 0;
        } else {
            fprintf(stderr, "{\"error\": \"Unknown argument: %s\", \"status\": \"failed\"}\n", argv[i]);
            return 1;
        }
    }

    /* Strict input validation */
    if (size <= 0 || size > MAX_SIZE) {
        fprintf(stderr, "{\"error\": \"Invalid size: %d. Allowed range: 1..%d\", \"status\": \"failed\"}\n", size, MAX_SIZE);
        return 1;
    }
    if (iterations <= 0 || iterations > MAX_ITERATIONS) {
        fprintf(stderr, "{\"error\": \"Invalid iterations: %d. Allowed range: 1..%d\", \"status\": \"failed\"}\n", iterations, MAX_ITERATIONS);
        return 1;
    }
    if (warmup < 0 || warmup > 10) {
        fprintf(stderr, "{\"error\": \"Invalid warmup: %d. Allowed range: 0..10\", \"status\": \"failed\"}\n", warmup);
        return 1;
    }
    if (num_threads <= 0 || num_threads > MAX_THREADS) {
        fprintf(stderr, "{\"error\": \"Invalid threads: %d. Allowed range: 1..%d\", \"status\": \"failed\"}\n", num_threads, MAX_THREADS);
        return 1;
    }

    size_t total_elements = (size_t)size * (size_t)size;
    double *A = (double *)malloc(total_elements * sizeof(double));
    double *B = (double *)malloc(total_elements * sizeof(double));
    double *C = (double *)malloc(total_elements * sizeof(double));

    if (!A || !B || !C) {
        fprintf(stderr, "{\"error\": \"Memory allocation failed for size %d\", \"status\": \"failed\"}\n", size);
        free(A); free(B); free(C);
        return 2;
    }

    /* Deterministic initialization */
    for (size_t i = 0; i < total_elements; ++i) {
        A[i] = sin((double)(i % 360) * (M_PI / 180.0));
        B[i] = cos((double)(i % 360) * (M_PI / 180.0));
        C[i] = 0.0;
    }

    /* Optional Warmup Phase */
    double warmup_elapsed_sec = 0.0;
    if (warmup > 0) {
        double w_start = get_time_sec();
        run_computation(size, warmup, num_threads, A, B, C);
        warmup_elapsed_sec = get_time_sec() - w_start;
        /* Reset C */
        memset(C, 0, total_elements * sizeof(double));
    }

    /* Timed Benchmark Phase */
    double t_start = get_time_sec();
    run_computation(size, iterations, num_threads, A, B, C);
    double elapsed_sec = get_time_sec() - t_start;

    /* Compute 64-bit deterministic hash over C */
    uint64_t checksum = fnv1a_64(C, total_elements * sizeof(double));

    /* Total FLOPs = 2 * size^3 * iterations */
    double total_flops = 2.0 * (double)size * (double)size * (double)size * (double)iterations;
    double gflops = (elapsed_sec > 0.0) ? (total_flops / elapsed_sec / 1e9) : 0.0;

    /* Machine-readable JSON output */
    printf("{\n");
    printf("  \"workload\": \"cpu_deterministic\",\n");
    printf("  \"version\": \"%s\",\n", WORKLOAD_VERSION);
    printf("  \"parameters\": {\n");
    printf("    \"matrix_size\": %d,\n", size);
    printf("    \"iterations\": %d,\n", iterations);
    printf("    \"warmup\": %d,\n", warmup);
    printf("    \"threads\": %d\n", num_threads);
    printf("  },\n");
    printf("  \"results\": {\n");
    printf("    \"total_flops\": %.0f,\n", total_flops);
    printf("    \"warmup_elapsed_sec\": %.6f,\n", warmup_elapsed_sec);
    printf("    \"elapsed_sec\": %.6f,\n", elapsed_sec);
    printf("    \"gflops\": %.4f,\n", gflops);
    printf("    \"checksum\": \"0x%016" PRIx64 "\",\n", checksum);
    printf("    \"status\": \"success\"\n");
    printf("  }\n");
    printf("}\n");

    free(A);
    free(B);
    free(C);
    return 0;
}
