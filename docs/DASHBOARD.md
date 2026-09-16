# CC2 Virtualization Laboratory Dashboard

This document details the architecture, design philosophy, page index, and operation of the React + TypeScript + Vite laboratory dashboard for CC2.

---

## 1. Design & Scientific Philosophy

The CC2 Dashboard is engineered as a **professional technical virtualization laboratory instrument**, not a generic commercial admin template:
- **Theme**: High-contrast, dark technical aesthetic (`#090d16` background, `#0f172a` cards, monospaced telemetry fonts, precise cyan/emerald/indigo accents).
- **Zero Subjective Scoring**: Strictly avoids declaring an overall "winner", ranking technologies, or assigning artificial benchmark scores.
- **Neutral Language**: Uses precise scientific phrasing: *"Measured result"*, *"Observed difference"*, *"Median"*, *"Standard deviation"*.
- **Anti-Fabrication & Traceability**: Missing or restricted metrics are prominently labeled **UNAVAILABLE** alongside the explicit kernel/permission reason (e.g. `perf_event_paranoid=4`, `fio binary not found`). Every metric links directly to a **View Evidence** modal displaying the executed shell command, terminal standard output, standard error, exit code, and raw JSON payload.

---

## 2. Page Directory (16 Dedicated Pages)

The dashboard comprises 16 specialized laboratory views accessible via the responsive sidebar:

### System & Hypervisor Platforms
1. **`1. Overview`**:
   - High-level laboratory status and comparative virtualization matrix.
   - Summarizes KVM/QEMU, Oracle VirtualBox, and Native LXC: architecture, OS, kernel, CPU, RAM, storage, network, and execution completion status.
2. **`2. Host Baseline`**:
   - Detailed bare-metal Ubuntu 24.04 host hardware inventory.
   - Processor topology (Intel Core logical cores, microarchitecture flags, Intel VT-x hardware assist).
   - Memory capacity, available RAM, and swap accounting.
   - Read-only thermal and CPU scaling frequency telemetry (`scaling_cur_freq`, `scaling_governor`, thermal zone temperatures).
3. **`3. KVM / QEMU`**:
   - Kernel-based Virtual Machine architecture (Type-1-like).
   - Dynamic `virsh` domain discovery (`ubuntu24.04`), VirtIO SCSI disk, VirtIO net interfaces, and dynamic memory ballooning.
   - Host QEMU supervisor process telemetry (`qemu-system-x86_64` PID, RSS, and vCPU worker threads).
4. **`4. VirtualBox`**:
   - Oracle VirtualBox hosted hypervisor (Type-2).
   - Discovered VM (`Ubuntu-Server-VBox`) via `VBoxManage list vms`.
   - **Allocated vs. Actual RAM Distinction**: Contrasts static 2048 MB memory ceiling against physical `VBoxHeadless` resident set size.
   - AHCI SATA controller, Intel PRO/1000 MT network emulation, and ACPI graceful power button control.
5. **`5. Native LXC`**:
   - OS-level container virtualization via Linux cgroups v2 and 7 namespace boundaries (`pid`, `mnt`, `net`, `ipc`, `uts`, `user`, `cgroup`).
   - Shared host Linux kernel release observation.
   - Sub-second startup (~0.92s) and near-zero memory virtualization overhead.

### Workload Benchmarks
6. **`6. CPU Workload`**:
   - Deterministic double-precision matrix multiplication benchmark (static C99 binary with FNV-1a checksums).
   - Execution time, CPU utilization %, and context switches across environments.
   - Hardware performance counters (cycles, instructions, IPC) with transparent `perf_event_paranoid=4` restriction handling.
7. **`7. Memory & Cache`**:
   - Sequential write, read-accumulate, and cache stride benchmark passes.
   - Configured ceiling vs. actual active RAM utilization.
   - Peak resident set size (RSS), virtual memory size (VSZ), minor frame reclaims, and major I/O page faults.
8. **`8. Storage (FIO)`**:
   - File system I/O evaluation (sequential read/write, random 4K read/write, MB/s, IOPS, and p95/p99 tail latencies).
   - Storage safety enforcement: strictly rejects raw block devices (`/dev/*`), testing only on temporary regular files.
   - Unavailability transparency when `fio` is missing from the host.
9. **`9. Network Performance`**:
   - ICMP ping round-trip time (RTT min, avg, max, mdev, and packet loss).
   - Standardized `iperf3` bulk TCP throughput protocol (same duration, single stream, client-to-server direction, machine-readable JSON).
10. **`10. Startup Lifecycle`**:
    - Phased cold-start timeline breakdown:
      1. Hypervisor VMM / cgroup launch.
      2. Guest kernel network interface DHCP readiness.
      3. Guest HTTP application socket readiness.
11. **`11. Syscalls & strace`**:
    - Kernel mode transition profiling using `strace -c` on common workloads.
    - Syscall counts, cumulative execution time, negative error code traps, and top 10 system call breakdown.

### Empirical Audit & Methodology
12. **`12. Isolation & Kernel`**:
    - Visual execution layer diagrams (Hardware $\to$ Hypervisor $\to$ Guest OS vs. Hardware $\to$ Linux Kernel $\to$ Container).
    - Empirical evidence: `systemd-detect-virt`, `uname -r`, namespace IDs (`/proc/1/ns`), and cgroups hierarchy.
13. **`13. Neutral Comparison`**:
    - Side-by-side comparative matrices across Host, KVM, VirtualBox, and LXC.
    - Objective trade-off analysis without artificial rankings.
14. **`14. Traceable Evidence`**:
    - Central forensic evidence engine indexing all benchmark runs.
    - Filter by environment, benchmark domain, or execution status.
    - Full-text search across run IDs, commands, and terminal stdout.
15. **`15. Scientific Method`**:
    - Documentation of experimental standards: run isolation, lingering process scavenging, stabilization pauses, and static C99 compilation.
16. **`16. Raw Datasets`**:
    - Access to machine-readable JSON (`runs.json`) and CSV exports (`runs.csv`, domain-specific CSVs).
    - Live in-memory JSON inspector and one-click JSON dataset downloader.

---

## 3. Data Pipeline & File Sync

The dashboard consumes pre-processed datasets compiled by `benchmark/runner.py`:
- `results/processed/runs.json` $\to$ `dashboard/src/data/runs.json`
- `results/host_inventory.json` $\to$ `dashboard/src/data/inventory.json`
- Tabular exports: `results/processed/*.csv`

Both quick mode (2 measured runs) and full rigor mode (5 measured runs) datasets are fully supported. When datasets are empty, clean empty-state fallback UI is rendered without runtime exceptions.

---

## 4. Build, Typecheck & Development Instructions

All dependencies and build scripts are standard npm commands:

```bash
# Navigate to dashboard directory
cd /home/karthik-chakala/Downloads/cc2/dashboard

# Install dependencies
npm install

# Verify strict TypeScript typing
npm run typecheck

# Lint codebase
npm run lint

# Run dashboard test suite
npm test

# Build production bundle (Vite + Rollup)
npm run build

# Preview production build locally on port 4173
npm run preview
```

---

## 5. Live Backend API Integration & Job Dispatch Engine

Phase D introduces live real-time integration with the safe backend API (`http://127.0.0.1:8000`):

1. **Live Environment Status Bar (`EnvironmentStatusBar.tsx`)**:
   - Continuously monitors hypervisor and container reachability via `GET /api/benchmarks/health`.
   - Displays real-time operational states (`available`, `running`, `stopped`, `unavailable`, `error`) for Host, KVM/QEMU, VirtualBox, and Native LXC.

2. **Automated Experiment Dispatch Engine (`ExperimentControls.tsx`)**:
   - Enables operators to dispatch benchmark experiments via `POST /api/benchmarks/run`.
   - Whitelist validation prevents command injection: accepts only target environments (`host`, `kvm`, `virtualbox`, `lxc`, `all`), workloads (`cpu`, `memory`, `disk`, `network`, `startup`, `syscall`, `scheduling`, `isolation`, `all`), modes (`quick`, `full`), and integer run bounds (1–20).
   - Zero arbitrary shell command entry fields exist in the UI.

3. **Active Job Progress & Monitoring (`JobProgressCard.tsx`)**:
   - Real-time job lifecycle tracking (`queued`, `running`, `completed`, `failed`, `cancelled`).
   - Displays current environment, active benchmark workload, current iteration, total iterations, and current execution phase.
   - Allows live viewing of execution logs and job cancellation.

4. **Sanitized Terminal Execution Logs Modal (`JobLogsModal.tsx`)**:
   - Secure inspection of standard output and standard error from `GET /api/benchmarks/jobs/:id/logs`.
   - All sensitive data (passwords, tokens, credentials) is strictly redacted server-side before delivery.

5. **Multi-Environment Comparative Results View (`ResultsComparisonView.tsx`)**:
   - **Interactive Charts**: Recharts visualizations for CPU elapsed time, compute GFLOPS, memory throughput (MB/s), and system call latency.
   - **Detailed Metrics Table**: Comprehensive table showing Mean, Median, Min, Max, Std Dev, p50, p95, p99, and Run Counts per metric.
   - **Scientific Quality Indicators**: Prominently tags runs as `PASS`, `WARNING`, `FAILED`, or `UNAVAILABLE` without masking failures or fabricating values.

