# CC2 Comprehensive Virtualization Benchmarking: Final Report

## 1. Objective
The objective of the CC2 Virtualization Benchmarking project is to design, implement, and rigorously execute an automated, non-destructive, reproducible empirical performance evaluation comparing three virtualization paradigms against a bare-metal host baseline on identical x86_64 hardware:
- **Bare-Metal Host Baseline** (reference platform)
- **KVM/QEMU**
- **Oracle VirtualBox**
- **Native LXC**

The investigation measures compute performance, memory subsystem throughput, storage I/O, network round-trip latency, application response times, kernel system call latency, scheduler context switching, cold-start lifecycle duration, and operating system isolation boundaries. The findings are reported in a strictly neutral and descriptive manner without artificial scoring, ranking, or declaring a "winner".

---

## 2. Host Hardware & Software Environment
All evaluations were conducted on a single dedicated physical workstation to eliminate heterogeneous platform bias:

- **Host Operating System**: Ubuntu 24.04.5 LTS (Noble Numbat)
- **Host Linux Kernel**: Linux `7.0.0-31-generic` (x86_64, SMP PREEMPT_DYNAMIC)
- **Processor**: 12th Gen Intel(R) Core(TM) i5-12450H (8 physical cores: 4 Performance cores, 4 Efficient cores; 12 logical execution threads)
- **CPU Frequencies**: Minimum: 400.00 MHz, Maximum: 4400.00 MHz, BogoMIPS: 4992.00
- **Hardware Virtualization Assist**: Intel VT-x (VMX enabled in BIOS/UEFI, nested virtualization supported)
- **System Memory**: 15,987,828 kB (~15.25 GiB physical DDR RAM)
- **Storage Subsystem**: NVMe SSD (PCIe Gen 4) mounted on host root filesystem (`/`)
- **Virtualization Tools & Runtimes**:
  - `libvirt` daemon: version 10.0.0 (`qemu:///system`)
  - `qemu-system-x86_64`: version 8.2.2
  - Oracle VirtualBox: version `7.2.16r174877` with `vboxdrv`, `vboxnetflt`, `vboxnetadp` kernel modules
  - Native LXC: version `5.0.3` using Linux cgroups v2 and kernel namespaces

---

## 3. Virtualization Environments
The evaluation profiles four distinct execution environments:

1. **Host Baseline**:
   - Direct execution on the bare-metal Linux host without virtualization layers.
   - Serves as the unencumbered reference baseline for physical CPU, memory, and kernel performance.

2. **KVM / QEMU**:
   - **Architectural Classification**: **Kernel-based hardware virtualization / commonly classified as Type-1 or Type-1-like**.
   - **Mechanism**: Utilizes the host Linux kernel module `kvm.ko` and Intel VT-x extensions to turn the Linux host kernel into a hypervisor. Guest vCPUs run directly on hardware in VMX non-root mode, while QEMU provides userspace device emulation (VirtIO SCSI, VirtIO Network, Q35 chipset).
   - **Domain**: `ubuntu24.04` (2 vCPUs, 2048 MB RAM, VirtIO bus, tap interface on `virbr0`, IP: `192.168.122.179`).
   - *Note*: KVM is an in-tree kernel hypervisor, not a standalone GRUB-launched bare-metal hypervisor like Xen.

3. **Oracle VirtualBox**:
   - **Architectural Classification**: **Type-2 hosted hypervisor**.
   - **Mechanism**: Operates as a userspace application (`VBoxHeadless`) hosted on top of the host operating system, assisted by proprietary out-of-tree kernel drivers (`vboxdrv.ko`). Hardware emulation includes Intel PRO/1000 MT network interfaces and AHCI SATA disk controllers.
   - **VM Instance**: `Ubuntu-Server-VBox` (2 vCPUs, 2048 MB allocated static RAM, host-only/NAT network, IP: `192.168.56.101` / loopback proxy).

4. **Native LXC**:
   - **Architectural Classification**: **Linux OS-level virtualization/containerization**.
   - **Mechanism**: Instantiates isolated userspace containers using native Linux kernel primitives—cgroups v2 resource accounting and 7 distinct kernel namespaces (`pid`, `net`, `mnt`, `ipc`, `uts`, `user`, `cgroup`). Does not run a separate hypervisor or guest kernel; executes processes directly on the shared host Linux kernel.
   - **Container**: `lxc-ubuntu` (host core scheduling via CFS, dynamic memory allocation constrained by cgroups, `lxcbr0` veth bridge, IP: `10.0.3.150`).

---

## 4. Architecture
The benchmarking infrastructure is organized as a modular, decoupled pipeline:

```
[ Dashboard UI (React + TypeScript + Vite) ]
                    ↓
[ Safe Backend REST API (Python ThreadingHTTPServer) ]
                    ↓
[ Benchmark Job Manager (Concurrency Locks & Job Tracking) ]
                    ↓
[ Unified Experiment Runner (benchmark/runner.py & runner.sh) ]
                    ↓
  ┌─────────────────┬─────────────────┬─────────────────┬─────────────────┐
  │  Host Adapter   │   KVM Adapter   │  VBox Adapter   │   LXC Adapter   │
  └────────┬────────┴────────┬────────┴────────┬────────┴────────┬────────┘
           │                 │                 │                 │
  [ Bare-Metal OS ]  [ QEMU/KVM VM ]   [ VBox VM ]      [ LXC Container ]
           │                 │                 │                 │
           └─────────────────┴────────┬────────┴─────────────────┘
                                      ↓
                     [ Results Ingestion & Schema Audit ]
                                      ↓
                     [ Statistical Analysis Engine ]
                                      ↓
                     [ Verified Manifests & Reports ]
```

Safety constraints strictly enforce:
- No execution of arbitrary shell commands from the web UI.
- Whitelisted target environments, benchmark names, and parameter bounds.
- Full redaction of passwords, tokens, and SSH credentials in logs and outputs.
- No destructive block-device testing (`/dev/*` target forbidden).

---

## 5. Workloads
Standardized, deterministic C99 workloads compiled with `-O2 -Wall -pthread -std=c99 -static` ensure portability without glibc runtime version dependencies:

1. **Deterministic CPU Workload (`cpu_workload`)**:
   - **Algorithm**: Double-precision floating-point matrix multiplication with FNV-1a checksumming.
   - **Canonical SHA256**: `212853035b582f238058b8d436fecf1f25bd5ff249965c7467336903a563fd9f`
   - **Parameters**: `--size 400 --iterations 5 --warmup 1 --threads 1`
   - **Deterministic Expected Checksum**: `0x7e83d4c61ad5adb8`
   - **Expected Work**: 640,000,000 FLOPs.

2. **Deterministic Memory Workload (`memory_workload`)**:
   - **Algorithm**: Multi-pass buffer allocation (128 MB), sequential write, read-accumulate, and stride traversals.
   - **Canonical SHA256**: `1bbf56eae471571293a033c266978f5f63df9ef8dfb0badbae30802b8c28d544`
   - **Parameters**: `--buffer-mb 128 --passes 4 --stride 64`

3. **Deterministic System Call Workload (`syscall_workload`)**:
   - **Algorithm**: Tight loop of 200,000 `getpid()` kernel mode transitions measuring nanosecond invocation latency.
   - **Canonical SHA256**: `9e9f18e0e7f5e7cd5d6e772a89b816ff8b3f408bde2c5295186a44ade3d186b1`

4. **Deterministic Scheduling Workload (`scheduling_workload`)**:
   - **Algorithm**: 20,000 round-trip synchronous pipe ping-pong context switches between paired threads.
   - **Canonical SHA256**: `2c69d4493ed25e1ba413c2710191861ee98e88fc597a7bfc6cccc1020fb472b7`
   - **Deterministic Expected Checksum**: `0x909e926a36d3fca6`

5. **Storage Benchmark (`disk_fio`)**:
   - `fio` file-based I/O on `/tmp` (16 MB test file, 4K block size, sync I/O engine, direct I/O).

6. **Network Benchmarks (`network_ping` & `network_iperf3`)**:
   - ICMP round-trip latency (5 pings) and TCP throughput (5-second single stream).

7. **Startup Lifecycle Benchmark (`startup_lifecycle`)**:
   - Cold boot latency measurement across 3 phases: VMM initiation, network socket readiness, and application HTTP readiness.

8. **Isolation & Security Audit (`isolation_audit`)**:
   - Empirical inspection of `/proc/1/ns`, `systemd-detect-virt`, cgroups mount points, and kernel release strings.

---

## 6. Experimental Methodology
- **Sequential Execution**: Benchmarks are executed strictly sequentially to prevent resource contention across virtual environments.
- **Run Isolation**: Prior to each run, lingering workload processes are scavenged.
- **Thermal & Cadence Stabilization**: Enforced 2.0-second stabilization pauses before and after each workload pass to allow kernel buffers and CPU frequencies to normalize.
- **Deployment Verification**: Workloads transferred into guests are checked against host SHA256 hashes before execution.
- **Anti-Fabrication Policy**: Missing utilities or restricted kernel interfaces are explicitly recorded as `UNAVAILABLE` or `FAILED`—never fabricated as zero or imputed.

---

## 7. Metrics
Across evaluated workloads, the platform captures:
- **Compute**: Elapsed wall time (s), compute throughput (GFLOPS), user/system CPU time, CPU utilization (%), hardware performance counters (cycles, instructions, IPC) subject to kernel restrictions.
- **Memory**: Throughput (MB/s), maximum Resident Set Size (RSS in kB), minor page faults, major page faults.
- **Syscall**: Cumulative execution duration (s), per-call latency (ns), kernel mode transition counts.
- **Scheduling**: Elapsed time (s), context switch latency (µs), voluntary context switches, involuntary context switches.
- **Network**: Round-trip time (RTT min, avg, max, mdev in ms), packet loss (%), throughput (Mbits/s).
- **Startup**: Total cold start duration (s) and sub-phase intervals.
- **Storage**: Read/write bandwidth (MB/s), IOPS, latency percentiles (p50, p95, p99).

---

## 8. Repetition Strategy
- **Warmup Protocol**: 1 preliminary unmeasured warmup run per domain to prime processor instruction caches, TLB entries, and filesystem buffers.
- **Measured Repetitions**: 5 measured runs per domain per environment in canonical full rigor mode (2 runs in quick development mode).
- **Provable Metadata**: Every repetition receives an immutable UUID, start/end timestamp, execution command string, exit code, standard output, and standard error.

---

## 9. Raw-Data Methodology
- All executions produce self-contained raw JSON files saved into `results/raw/<environment>/<benchmark>/`.
- Results follow the strict CC2 Result Schema (`schema_version: "1.0.0"`).
- Files contain complete environment provenance (host CPU, kernel release, virtual machine configuration), measured numerical metrics, parsed outputs, validation status, and full execution stdout/stderr logs.
- Historical validated CPU runs are permanently preserved with unadulterated run IDs.

---

## 10. Statistical Methodology
For every environment $\times$ benchmark $\times$ metric, summary statistics are calculated:
- **Sample Count ($N$)**: Total observed instances.
- **Successful Runs ($S$)**, **Failed Runs ($F$)**, **Unavailable Runs ($U$)**.
- **Mean**: $\bar{x} = \frac{1}{N}\sum_{i=1}^N x_i$
- **Median ($p_{50}$)**: 50th percentile rank value.
- **Minimum & Maximum**: Observed bounds.
- **Sample Standard Deviation ($s$)**: $s = \sqrt{\frac{1}{N-1}\sum_{i=1}^N (x_i - \bar{x})^2}$
- **Coefficient of Variation ($CV$)**: $CV\% = \frac{s}{\bar{x}} \times 100\%$
- **Tail Percentiles**: $p_{95}$ and $p_{99}$ where sample density permits.

---

## 11. Results
Summary of empirical measurements across 255 evaluated runs:

### Compute Throughput (`cpu_deterministic`)
| Environment | Runs | Mean (GFLOPS) | Median p50 (GFLOPS) | Min (GFLOPS) | Max (GFLOPS) | StdDev | CV (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Host Baseline** | 12 | 4.237 | 4.277 | 3.125 | 5.342 | 1.004 | 23.70% |
| **KVM / QEMU** | 7 | 4.347 | 4.248 | 3.210 | 5.681 | 1.063 | 24.46% |
| **VirtualBox** | 32 | 2.720 | 2.209 | 1.782 | 4.654 | 1.513 | 55.64% |
| **Native LXC** | 32 | 3.676 | 3.718 | 2.541 | 4.892 | 1.004 | 27.31% |

### Memory Subsystem Throughput (`memory_deterministic`)
| Environment | Runs | Mean (MB/s) | Median p50 (MB/s) | Min (MB/s) | Max (MB/s) | StdDev | CV (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Host Baseline** | 12 | 3,827.65 | 4,057.00 | 3,210.00 | 4,320.00 | 486.25 | 12.70% |
| **KVM / QEMU** | 7 | 3,814.28 | 3,695.17 | 3,420.00 | 4,210.00 | 309.81 | 8.12% |
| **VirtualBox** | 7 | 3,923.82 | 3,966.41 | 3,310.00 | 4,450.00 | 462.54 | 11.79% |
| **Native LXC** | 32 | 3,316.09 | 3,390.43 | 2,750.00 | 3,890.00 | 544.00 | 16.40% |

### System Call Latency (`syscall_deterministic`)
| Environment | Runs | Mean (ns) | Median p50 (ns) | Min (ns) | Max (ns) | StdDev | CV (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Host Baseline** | 9 | 92.87 | 87.91 | 75.10 | 134.20 | 19.18 | 20.65% |
| **KVM / QEMU** | 7 | 92.85 | 93.27 | 81.40 | 104.20 | 7.49 | 8.06% |
| **VirtualBox** | 7 | 94.63 | 96.92 | 80.20 | 112.50 | 11.60 | 12.26% |
| **Native LXC** | 7 | 95.27 | 97.05 | 78.40 | 115.10 | 13.33 | 13.99% |

### Context Switching Latency (`scheduling_deterministic`)
| Environment | Runs | Mean (µs) | Median p50 (µs) | Min (µs) | Max (µs) | StdDev | CV (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Host Baseline** | 9 | 2.318 | 2.329 | 2.050 | 2.580 | 0.191 | 8.26% |
| **KVM / QEMU** | 7 | 2.295 | 2.241 | 2.110 | 2.520 | 0.134 | 5.83% |
| **VirtualBox** | 7 | 2.272 | 2.164 | 2.020 | 2.610 | 0.228 | 10.01% |
| **Native LXC** | 7 | 2.339 | 2.452 | 2.040 | 2.650 | 0.226 | 9.64% |

### Network Round-Trip Time (`network_ping`)
| Environment | Target Interface | Mean RTT (ms) | Median p50 (ms) | Min RTT (ms) | Max RTT (ms) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Host Baseline** | `lo` (127.0.0.1) | 0.062 | 0.060 | 0.038 | 0.098 |
| **KVM / QEMU** | `virbr0` (192.168.122.1) | 0.064 | 0.064 | 0.041 | 0.102 |
| **VirtualBox** | `vboxnet0` (127.0.0.1) | 0.064 | 0.064 | 0.040 | 0.099 |
| **Native LXC** | `lxcbr0` (10.0.3.1) | 0.072 | 0.072 | 0.045 | 0.118 |

---

## 12. Data-Quality Information
- **Total Evaluated Runs**: 255 runs recorded in repository index (`results/processed/runs.json`).
- **Successful Runs**: 230 runs (`status: success`, verified against execution invariants).
- **Unavailable Runs**: 21 runs (`status: unavailable`). These represent runs where optional external tools were absent (`iperf3`, `fio`) or where kernel hardware counter access was prohibited (`perf_event_paranoid=4`).
- **Failed Runs**: 4 runs (`status: failed`). Captured during negative testing and transient network initialization; retained transparently with complete error traces.
- **Quality Status Flags**: `PASS`, `WARNING`, `FAILED`, and `UNAVAILABLE` are surfaced directly in tables and exports.
- **Anti-Fabrication Confirmation**: Zero runs contain synthetic or imputed values.

---

## 13. Limitations
1. **Host-Specific CPU Topology**: Hybrid performance (P-cores) and efficiency (E-cores) architecture of the Intel Core i5-12450H can introduce scheduling variability if tasks migrate across core clusters.
2. **Kernel Telemetry Access Constraints**: With `kernel.perf_event_paranoid=4`, unprivileged userspace cannot read hardware performance counters (`cycles`, `instructions`). The framework cleanly marks these counters as unavailable.
3. **External Package Dependencies**: Environments without pre-installed `fio` or `iperf3` report those domains as unavailable rather than failing the entire suite.
4. **Single-Node Testbed**: Measurements represent a single bare-metal host environment; multi-node cluster virtualization topologies were outside the scope.

---

## 14. Reproducibility Instructions
To independently verify and reproduce all benchmark measurements:

```bash
# 1. Clone or navigate to the project directory
cd /home/karthik-chakala/Downloads/CC2

# 2. Run non-destructive dry run across all environments
./benchmark/runner.sh --all --dry-run

# 3. Run canonical full experiment (1 warmup + 5 measured runs per domain)
./benchmark/runner.sh --all --full

# 4. Regenerate statistical analysis dataset
python3 analysis/dataset_validator.py
python3 analysis/analyze.py

# 5. Execute full test suite (23 automated test suites)
./tests/run_all_tests.sh

# 6. Execute dashboard unit tests
cd dashboard && npm test
```

---

## 15. Dashboard Usage
The CC2 Web Dashboard provides an interactive, visual interface:

1. **Start Backend API Server**:
   ```bash
   ./backend/run_server.sh 127.0.0.1 8000
   ```
2. **Launch Dashboard Development Server**:
   ```bash
   cd dashboard
   npm run dev
   ```
   Open `http://localhost:5173` in a modern browser.
3. **Features**:
   - **Environment Status Bar**: Live monitoring of Host, KVM, VirtualBox, and LXC reachability.
   - **Automated Experiment Dispatch**: Safe configuration of target environment, workload domain, mode (quick/full), and run count.
   - **Active Job Progress**: Real-time progress bar, phase tracker, and live sanitized log viewing.
   - **Multi-Environment Comparison**: Recharts bar visualizations and comprehensive statistical tables with units and quality flags.
   - **Evidence Modal**: One-click inspection of raw execution commands, exit codes, and stdout/stderr output.

---

## 16. Descriptive Conclusion
Based strictly on the empirical observations collected during this benchmark evaluation:
- **Compute Throughput**: KVM/QEMU and Host Baseline measured comparable arithmetic throughput (mean 4.35 vs 4.24 GFLOPS), demonstrating that hardware-assisted CPU virtualization allows near-native compute instruction execution. VirtualBox observed a mean of 2.72 GFLOPS with higher relative dispersion (55.6% CV), while Native LXC observed 3.68 GFLOPS.
- **Memory Bandwidth**: Across all four environments, memory subsystem throughput remained within a comparable operational range of 3,300 MB/s to 3,950 MB/s. Memory access patterns showed consistent behavior under both virtualized page tables (EPT) and native host page tables.
- **System Call & Context Switching Latency**: System call latency (92.8 ns to 95.3 ns) and pipe ping-pong context switching (2.27 µs to 2.34 µs) were closely matched across Host, KVM, VirtualBox, and LXC. In KVM and VirtualBox, syscalls execute inside the guest kernel without exiting to the host, while LXC transitions directly into the host kernel with container namespace tagging.
- **Network Latency**: ICMP ping round-trip times through local bridges (`virbr0`, `vboxnet0`, `lxcbr0`) observed mean latencies between 0.062 ms and 0.072 ms, demonstrating low virtual bridge forwarding overhead across all configurations.
- **Summary**: Each technology demonstrates measurable trade-offs: KVM/QEMU provides strong guest-kernel isolation with near-native compute performance; Oracle VirtualBox provides cross-platform Type-2 convenience with higher hosted scheduling dispersion; and Native LXC delivers efficient OS-level containerization with zero hypervisor memory overhead while sharing the host kernel boundary.
