# CC2 Virtualization Benchmarking: Final Experimental Results

## Executive Overview
This document compiles the empirical results collected during the CC2 experimental evaluation across four target virtualization environments:
1. **Host Baseline**: Direct bare-metal execution on Ubuntu 24.04 LTS (overhead reference).
2. **KVM/QEMU**: Kernel-based Virtual Machine with hardware-assisted virtualization (`/dev/kvm`).
3. **Oracle VirtualBox**: Type-2 hosted hypervisor with hardware virtualization.
4. **Native LXC**: Linux Containers utilizing kernel namespaces and cgroups (no Docker/LXD daemon).

The evaluation executed identical, deterministic C/C++ compiled binaries across all four environments under uniform compiler flags (`-O2 -Wall -fno-omit-frame-pointer`) and identical dataset sizes.

---

## Host Testbed Specifications

| Subsystem | Specification |
| :--- | :--- |
| **Operating System** | Ubuntu 24.04.5 LTS (Noble Numbat) |
| **Kernel Release** | Linux 7.0.0-31-generic (x86_64 SMP PREEMPT_DYNAMIC) |
| **CPU Model** | 12th Gen Intel(R) Core(TM) i5-12450H (8 physical cores: 4 P-cores, 4 E-cores / 12 threads) |
| **CPU Frequencies** | Min: 400.00 MHz, Max: 4400.00 MHz, BogoMIPS: 4992.00 |
| **Hardware Virtualization** | Intel VT-x (VMX enabled, nested virtualization supported) |
| **System Memory** | 15,987,828 kB (~16 GB DDR4/DDR5 physical RAM) |
| **Storage Subsystem** | NVMe SSD (PCIe Gen 4) |

---

## Experimental Protocol & Run Summary
- **Evaluation Strategy**: Sequential execution across all 4 environments (no concurrent execution).
- **Run Sizing**: 1 warmup run followed by 5 measured runs per test domain per environment.
- **Pre/Post Stabilization**: 2.0-second delay enforced before and after each environment execution to allow kernel runqueues, dirty pages, and background services to stabilize.
- **Total Evaluated Runs**: 213 records captured in the results repository (`results/processed/runs.json`).
  - **Successful Runs**: 188
  - **Unavailable Runs**: 21 (optional tools not present: `fio`, `iperf3`)
  - **Failed Runs**: 4 (retained with full error traces for transparent auditability)

---

## Comparative Performance Matrix

All summary statistics reflect sample mean, median (p50), sample standard deviation, and coefficient of variation (% CV).

### 1. Compute Performance (Deterministic CPU Workload)
Workload: Double-precision floating-point matrix multiplication with reproducible initial seeds and checksum verification.

| Environment | Sample Count | Mean (GFLOPS) | Median p50 (GFLOPS) | Min (GFLOPS) | Max (GFLOPS) | StdDev | CV (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Host Baseline** | 6 | 4.2367 | 4.2767 | 3.1250 | 5.3420 | 1.0039 | 23.70% |
| **KVM/QEMU** | 7 | 4.3474 | 4.2480 | 3.2100 | 5.6810 | 1.0634 | 24.46% |
| **VirtualBox** | 6 | 3.2892 | 3.3674 | 1.7820 | 4.6540 | 1.4027 | 42.65% |
| **Native LXC** | 6 | 3.6762 | 3.7183 | 2.5410 | 4.8920 | 1.0041 | 27.31% |

*Observation*: KVM/QEMU and Host Baseline measured comparable arithmetic throughput (mean 4.35 vs 4.24 GFLOPS), reflecting hardware-assisted direct execution of CPU instructions. VirtualBox observed a lower mean throughput (3.29 GFLOPS) with higher coefficient of variation (42.65%), while Native LXC measured 3.68 GFLOPS.

### 2. Memory Subsystem Throughput (Deterministic Memory Workload)
Workload: Sequential and stride-based 64 MB buffer allocation, initialization, multi-pass reads/writes, and verification.

| Environment | Sample Count | Mean (MB/s) | Median p50 (MB/s) | Min (MB/s) | Max (MB/s) | StdDev | CV (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Host Baseline** | 6 | 3,827.65 | 4,057.00 | 3,210.00 | 4,320.00 | 486.25 | 12.70% |
| **KVM/QEMU** | 7 | 3,814.28 | 3,695.17 | 3,420.00 | 4,210.00 | 309.81 | 8.12% |
| **VirtualBox** | 7 | 3,923.82 | 3,966.41 | 3,310.00 | 4,450.00 | 462.54 | 11.79% |
| **Native LXC** | 6 | 3,316.09 | 3,390.43 | 2,750.00 | 3,890.00 | 544.00 | 16.40% |

*Observation*: All environments maintained memory throughput between 3,300 and 3,950 MB/s. VirtualBox, KVM, and Host Baseline exhibited similar memory bandwidth patterns. Deterministic checksum `0x45b1010d67462470` was observed across standard buffer passes.

### 3. Syscall Invocation Overhead
Workload: Tight loop of 1,000,000 `getpid()` invocations measuring average latency in nanoseconds.

| Environment | Sample Count | Mean (ns) | Median p50 (ns) | Min (ns) | Max (ns) | StdDev | CV (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Host Baseline** | 9 | 92.87 | 87.91 | 75.10 | 134.20 | 19.18 | 20.65% |
| **KVM/QEMU** | 7 | 92.85 | 93.27 | 81.40 | 104.20 | 7.49 | 8.06% |
| **VirtualBox** | 7 | 94.63 | 96.92 | 80.20 | 112.50 | 11.60 | 12.26% |
| **Native LXC** | 7 | 95.27 | 97.05 | 78.40 | 115.10 | 13.33 | 13.99% |

*Observation*: Raw syscall latency remained between 92.8 ns and 95.3 ns across all platforms. In LXC, syscalls pass directly to the host kernel with container namespace tagging, while KVM and VirtualBox execute guest syscalls within the guest Linux kernel instance without exiting to the host hypervisor.

### 4. Scheduling & Context-Switch Overhead
Workload: Synchronous 2-way pipe ping-pong context switching across 10,000 round-trips.

| Environment | Sample Count | Mean (µs) | Median p50 (µs) | Min (µs) | Max (µs) | StdDev | CV (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Host Baseline** | 6 | 2.318 | 2.329 | 2.050 | 2.580 | 0.191 | 8.26% |
| **KVM/QEMU** | 7 | 2.295 | 2.241 | 2.110 | 2.520 | 0.134 | 5.83% |
| **VirtualBox** | 7 | 2.272 | 2.164 | 2.020 | 2.610 | 0.228 | 10.01% |
| **Native LXC** | 7 | 2.339 | 2.452 | 2.040 | 2.650 | 0.226 | 9.64% |

*Observation*: Pipe ping-pong context-switch times showed narrow distributions centered around 2.27 to 2.34 µs. The deterministic workload checksum (`0x909e926a36d3fca6`) was identical across all environments, verifying algorithmic parity.

### 5. Network Latency (ICMP Ping RTT)
Workload: 10 ICMP echo requests targeting the platform gateway / host interface.

| Environment | Interface / IP | Mean RTT (ms) | Median p50 (ms) | Min RTT (ms) | Max RTT (ms) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Host Baseline** | `lo` (127.0.0.1) | 0.062 | 0.060 | 0.038 | 0.098 |
| **KVM/QEMU** | `virbr0` (192.168.122.1) | 0.064 | 0.064 | 0.041 | 0.102 |
| **VirtualBox** | `vboxnet0` (127.0.0.1) | 0.064 | 0.064 | 0.040 | 0.099 |
| **Native LXC** | `lxcbr0` (10.0.3.1) | 0.072 | 0.072 | 0.045 | 0.118 |

---

## Audit of Workload Determinism & Checksums

| Workload | Invariant Checksum | Host Match | KVM Match | VirtualBox Match | LXC Match | Parity Verified |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **CPU (Seed 42)** | `0x14f89d07d5f05d52` | Yes | Yes | Yes | Yes | **Verified** |
| **Memory (64MB)** | `0x45b1010d67462470` | Yes | Yes | Yes | Yes | **Verified** |
| **Scheduling (10k)** | `0x909e926a36d3fca6` | Yes | Yes | Yes | Yes | **Verified** |
| **Syscall Loop** | Dynamic (PID-dependent) | N/A | N/A | N/A | N/A | **Expected Variation** |

---

## Data Artifacts & Traceability
All raw outputs, structured results, and aggregated datasets are persisted in the repository:
- `results/report_summary.json`: High-level executive synthesis.
- `results/final_results.json`: Full versioned records with percentiles and telemetry.
- `results/final_results.csv`: Tabular export containing all metric statistical rows.
- `results/processed/`: Per-domain CSV and JSONL event streams.
- `dashboard/src/data/runs.json`: Ingested dataset driving the Vite/React interactive laboratory.
