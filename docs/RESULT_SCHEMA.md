# CC2 Versioned Result Schema & Data Model

## 1. Directory Structure

Results collected by the CC2 Benchmarking Suite are structured into three tiered directories to ensure strict separation between raw provenance logs and post-processed analytics:

```text
results/
├── raw/                 # Complete, individual JSON execution payloads (one per run)
│   ├── cpu_deterministic-host-b2ddb3b6.json
│   └── memory_deterministic-host-43d7086b.json
├── processed/           # Line-delimited JSON (.jsonl) grouped by environment and benchmark
│   ├── host_cpu_deterministic.jsonl
│   └── host_memory_deterministic.jsonl
└── statistics/          # Aggregated statistical summaries with percentiles and CV
    ├── host_cpu_deterministic_stats.json
    └── host_memory_deterministic_stats.json
```

---

## 2. Benchmark Result Schema (`Version 2.0.0`)

Every execution payload recorded in `results/raw/` and `results/processed/` must conform to the following schema:

| Field | Type | Description |
|:---|:---|:---|
| `schema_version` | String | Semantic version of the schema (e.g. `"2.0.0"`) |
| `experiment_id` | String | Identifier grouping a campaign of runs (e.g. `"exp-cc2-phase1"`) |
| `environment` | String | Target virtualization tier: `"host"`, `"kvm"`, `"virtualbox"`, `"lxc"` |
| `benchmark` | String | Benchmark identity: `"cpu_deterministic"`, `"memory_deterministic"`, `"syscall_deterministic"`, `"scheduling_deterministic"`, `"disk_fio"`, `"network_ping"`, `"network_iperf3"`, `"app_latency"`, `"startup_lifecycle"`, `"isolation_audit"` |
| `run_id` | String | Globally unique execution identifier (e.g. `"cpu_deterministic-host-b2ddb3b6"`) |
| `timestamp` | String | ISO 8601 UTC timestamp of execution completion |
| `command` | String | The exact shell command string executed |
| `exit_code` | Integer | Process termination code ($0$ for success, non-zero for failure) |
| `stdout` | String | Full lossless standard output emitted by the workload binary |
| `stderr` | String | Standard error output emitted by process or wrapper |
| `metrics` | Object | Combined workload calculation results, domain metrics, and kernel telemetry |
| `status` | String | Execution outcome: `"success"`, `"failed"`, `"unavailable"` |

---

## 3. Telemetry & Metrics Breakdown

The `metrics` dictionary combines computational output with low-level kernel telemetry captured via `/usr/bin/time -v` and `perf`:

```json
{
  "total_flops": 93750000,
  "elapsed_sec": 0.018207,
  "gflops": 5.1491,
  "checksum": "0xa05074ea2a890136",
  "status": "success",
  "parameters": {
    "matrix_size": 250,
    "iterations": 3,
    "warmup": 1,
    "threads": 1
  },
  "wall_time_sec": 0.03,
  "user_time_sec": 0.02,
  "system_time_sec": 0.0,
  "cpu_percentage": 100.0,
  "max_rss_kb": 2060,
  "telemetry": {
    "time_v": {
      "status": "success",
      "user_time_sec": 0.02,
      "system_time_sec": 0.0,
      "wall_time_sec": 0.03,
      "cpu_percentage": 100.0,
      "max_rss_kb": 2060,
      "minor_page_faults": 537,
      "major_page_faults": 0,
      "total_page_faults": 537,
      "voluntary_context_switches": 1,
      "involuntary_context_switches": 1,
      "total_context_switches": 2,
      "exit_code": 0
    },
    "perf": {
      "status": "unavailable",
      "reason": "Hardware counters restricted (perf_event_paranoid >= 1)",
      "cycles": null,
      "instructions": null,
      "context_switches": null,
      "cpu_migrations": null,
      "page_faults": null
    }
  }
}
```

### 3.1 Domain-Specific Primary Metrics

| Domain | Primary Metrics | Units / Format |
|:---|:---|:---|
| **CPU** | `gflops`, `wall_time_sec`, `cpu_percentage`, `checksum` | Double GFLOPS, seconds, %, `0x[0-9a-fA-F]+` |
| **Memory** | `throughput_mb_s`, `allocated_bytes`, `transferred_bytes`, `checksum` | MB/sec, bytes, bytes, `0x[0-9a-fA-F]+` |
| **Syscalls** | `ops_per_sec`, `latency_ns`, `total_syscalls`, `checksum` | Ops/sec, nanoseconds, count, `0x[0-9a-fA-F]+` |
| **Scheduling** | `switches_per_sec`, `latency_us`, `total_context_switches`, `checksum` | Switches/sec, microseconds, count, `0x[0-9a-fA-F]+` |
| **Storage (FIO)** | `read_iops`, `write_iops`, `read_throughput_mb_s`, `write_throughput_mb_s`, `read_latency_p95_us`, `write_latency_p95_us` | IOPS, IOPS, MB/s, MB/s, $\mu s$, $\mu s$ |
| **Network (Ping)** | `rtt_min_ms`, `rtt_avg_ms`, `rtt_max_ms`, `rtt_mdev_ms`, `packet_loss_percent` | Milliseconds, ms, ms, ms, % (target is local only) |
| **Network (iperf3)** | `sender_bandwidth_mbps`, `receiver_bandwidth_mbps`, `retransmits` | Mbps, Mbps, count (`null` if unavailable) |
| **App Latency** | `p50`, `p95`, `p99`, `min`, `max`, `stdev`, `connect_p50`, `ttfb_p50`, `requests_completed` | Milliseconds (100 HTTP GET `/health` requests) |
| **Startup** | `hypervisor_start_sec`, `guest_boot_sec`, `network_ready_sec`, `app_ready_sec`, `total_startup_sec` | Seconds (`null` / unavailable for Host baseline) |
| **Isolation** | `is_shared_kernel`, `systemd_detect_virt`, `kernel_release`, `cgroup_v2`, `namespaces` | Boolean, string, string, bool, dict |

---

## 4. Statistical Metrics Specification (`results/statistics/`)

The analysis engine evaluates distributions across repeated runs using the following formulas:

1. **Mean ($\bar{x}$)**:
   $$\bar{x} = \frac{1}{n} \sum_{i=1}^{n} x_i$$
2. **Median / 50th Percentile ($p_{50}$)**:
   Middle element of sorted sample data using linear interpolation between nearest ranks.
3. **Sample Standard Deviation ($s$)**:
   $$s = \sqrt{\frac{1}{n - 1} \sum_{i=1}^{n} (x_i - \bar{x})^2}$$
4. **Coefficient of Variation ($CV$)**:
   $$CV = \frac{s}{|\bar{x}|} \times 100\%$$
   Quantifies run-to-run dispersion normalized by the magnitude of the mean.
5. **Tail Latency Percentiles ($p_{95}, p_{99}$)**:
   $$\text{Rank}(p) = \frac{p}{100} \times (n - 1)$$

---

## 5. Anti-Fabrication & Missing Data Invariants

> [!IMPORTANT]
> **Fundamental Rules**:
> 1. **No Simulated Numbers**: Every number must be traceable to raw `stdout` or `/usr/bin/time -v` output.
> 2. **Missing Values Preserved as Null**: If an event or metric is unavailable (such as hardware performance counters blocked by kernel security), the metric must be explicitly set to `null` with `status: "unavailable"`.
> 3. **Never Coerce to Zero**: A missing or failed measurement must **NEVER** be replaced with $0$ or $0.0$, as this distorts statistical distributions (e.g. artificially lowering means and corrupting standard deviation calculations).
