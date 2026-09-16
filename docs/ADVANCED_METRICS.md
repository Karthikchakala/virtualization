# Advanced Performance Metrics & Kernel Telemetry Specification

This document details the advanced performance measurement methodologies, hardware performance counters, kernel tracing, thermal/frequency observability, and application latency evaluation implemented in CC2.

---

## 1. System Call Profiling (`strace -c`)

### 1.1 Methodology
System call tracing is performed on the common workloads using `strace -c`. This runs the target binary while attaching ptrace-based syscall entry/exit counting and timing.

### 1.2 Collected Metrics
- **Syscall Count**: Total number of system calls executed throughout the run.
- **Syscall Time (Seconds)**: Cumulative time spent by the kernel servicing syscalls.
- **Syscall Errors**: Count of system calls returning negative error codes (e.g. `ENOENT`, `EAGAIN`).
- **Top Syscalls**: Ranked breakdown of the top 10 system calls sorted by call frequency and cumulative time, detailing:
  - `% time`: Percentage of total syscall time.
  - `seconds`: Absolute seconds in syscall.
  - `usecs/call`: Average microseconds per invocation.
  - `calls`: Total invocations.
  - `errors`: Specific error count for this syscall.
  - `syscall`: Name of the system call (e.g., `write`, `getpid`, `mmap`, `openat`).

### 1.3 Missing / Restricted Invariants
If `strace` is missing from the environment or permissions restrict ptrace operations:
- `status`: `"unavailable"`
- `reason`: Explains the restriction (e.g., `"strace binary not found on system"`).
- Metric values remain `None`; **zeroes are never fabricated**.

---

## 2. Scheduling & Context Switches (`perf stat`, `/usr/bin/time -v`, `pidstat`)

### 2.1 Multi-Tool Coordination
Scheduling metrics are captured using three complementary Linux tools:
1. **`/usr/bin/time -v`**: Captures absolute process lifetime counts:
   - `voluntary_context_switches`: Task yielded CPU voluntarily (e.g. waiting for I/O, sleep, mutex).
   - `involuntary_context_switches`: Task was preempted by the scheduler (timeslice expiration or higher priority task).
   - `total_context_switches`: Sum of voluntary and involuntary switches.
   - `minor_page_faults`: Memory frame reclaimed without disk I/O.
   - `major_page_faults`: Page fault requiring disk/storage access.
   - `total_page_faults`: Sum of minor and major page faults.
2. **`pidstat -h -w -r -e`**: Captures scheduling and memory rates:
   - `cswch/s`: Voluntary context switches per second.
   - `nvcswch/s`: Involuntary context switches per second.
   - `minflt/s`: Minor page faults per second.
   - `majflt/s`: Major page faults per second.
   - `VSZ` and `RSS` memory allocations.
3. **`perf stat -x,`**: Captures kernel-level scheduling events:
   - `context-switches`
   - `cpu-migrations`: Migrations of threads across CPU cores.
   - `page-faults`

---

## 3. CPU Hardware Performance Counters (Cycles, Instructions, IPC)

### 3.1 Collected Hardware Counters
- **`cycles`**: Total CPU core clock cycles consumed.
- **`instructions`**: Total retired instructions executed.
- **`IPC` (Instructions Per Cycle)**: Calculated mathematically as:
  $$\text{IPC} = \frac{\text{instructions}}{\text{cycles}}$$

### 3.2 Linux Kernel Security Policy (`perf_event_paranoid`)
On Linux systems, access to uncore and CPU hardware performance counters is governed by `/proc/sys/kernel/perf_event_paranoid`:
- `-1`: Unrestricted access.
- `0`: Raw tracepoints disallowed without CAP_SYS_ADMIN.
- `1`: Kernel CPU events disallowed.
- `2`: Kernel profiling disallowed without CAP_PERFMON.
- `3` / `4`: Unprivileged access to hardware counters completely disallowed.

### 3.3 Strict Anti-Fabrication Guarantee
When `/proc/sys/kernel/perf_event_paranoid` is set to `4` (or unprivileged users lack `CAP_PERFMON` / `CAP_SYS_ADMIN`):
- `status`: `"unavailable"`
- `reason`: `"Hardware counters restricted: /proc/sys/kernel/perf_event_paranoid is 4 (requires CAP_PERFMON or CAP_SYS_ADMIN)"`
- `cycles`: `None`
- `instructions`: `None`
- `ipc`: `None`
- **Zeroes or mock numbers are strictly forbidden and never emitted.**

---

## 4. Thermal & System State Telemetry (Read-Only Safety)

### 4.1 Strict Safety Invariants
- **NEVER modify scaling governor**: The system governor is observed only. No write operations are ever performed on `/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor`.
- **NEVER disable thermal protection**: Thermal trip points, cooling devices, and emergency shutdown ceilings are strictly untouched.
- **Read-Only Inspection**: All sysfs inspections use read-only file descriptors (`open(..., "r")`).

### 4.2 Telemetry Data Collected
- **CPU Frequency**:
  - Captured from `/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq` (or `/proc/cpuinfo` fallback).
  - Metrics: `per_core_khz`, `min_khz`, `max_khz`, `avg_khz`.
- **CPU Governor**:
  - Captured from `/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor`.
  - Metrics: `per_core`, `governors` list, `dominant_governor`.
- **Load Average**:
  - Captured from `os.getloadavg()`.
  - Metrics: `load_1m`, `load_5m`, `load_15m`.
- **Thermal Zones**:
  - Captured from `/sys/class/thermal/thermal_zone*` and `/sys/class/hwmon`.
  - Metrics: `zones` array (`zone`, `type`, `temperature_c`), `max_temp_c`, `package_temp_c` (`x86_pkg_temp` / `TCPU`).

---

## 5. Application Latency Benchmark

### 5.1 Minimal Identical Application (`GET /health`)
To evaluate application-layer networking overhead across Host, KVM, VirtualBox, and LXC without third-party frameworks:
- **Application**: Lightweight Python standard library HTTP server (`MinimalHealthHttpServer` / `workloads/src/http_health_app.py`).
- **Endpoint**: `GET /health`
- **Response**: `HTTP/1.1 200 OK`, `Content-Type: application/json`, Body: `{"status":"healthy","version":"1.0.0"}`.
- **Request Count**: Exactly 100 sequential requests.

### 5.2 Microsecond Socket-Level Breakdown
For every request, socket lifecycle timestamps are measured:
1. **Connect Time (`connect_ms`)**: TCP three-way handshake time ($t_{\text{connect}} - t_{\text{start}}$).
2. **Time to First Byte (`ttfb_ms`)**: Latency from initiating connection through transmitting request to receiving the first response byte from the server ($t_{\text{first\_byte}} - t_{\text{start}}$).
3. **Total Time (`total_ms`)**: Complete round-trip duration until the full HTTP response body is received and socket closed ($t_{\text{total}} - t_{\text{start}}$).

### 5.3 Statistical Aggregates
For each metric (`connect_ms`, `ttfb_ms`, `total_ms`), the statistical engine computes:
- `mean`
- `median`
- `p50` (50th percentile rank)
- `p95` (95th percentile rank)
- `p99` (99th percentile rank)
- `min`
- `max`
- `stdev` (sample standard deviation)

---

## 6. Network Standardization (`iperf3`)

### 6.1 Standardized Parameters
All `iperf3` executions across all environments are strictly locked to:
- **Duration**: Identical duration (3s for quick, 10s for standard runs).
- **Stream Count**: Exactly 1 stream (`-P 1`).
- **Direction**: Client-to-server (upload).
- **Protocol**: Standard TCP.
- **Output Format**: Machine-readable JSON (`-J`).

### 6.2 Data Schema
When executed, the parser extracts:
- `sender_bandwidth_mbps`: Throughput reported by the client sender.
- `receiver_bandwidth_mbps`: Throughput measured by the receiving server.
- `retransmits`: Number of TCP segments retransmitted due to packet loss or congestion.
- `protocol`: `"TCP"`
- `direction`: `"client-to-server"`
- `stream_count`: `1`
- `raw_json`: Full uncompressed iperf3 JSON dictionary.
- If iperf3 is missing: `status: "unavailable"`, with clear non-zero explanation.
