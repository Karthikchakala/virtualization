# CC2 Virtualization & Container Benchmarking Platform

An empirical, non-destructive systems benchmarking suite comparing three fundamental virtualization paradigms on an Ubuntu Linux host:

1. **KVM / QEMU**: Kernel-based hardware virtualization (commonly classified as **Type-1 / Type-1-like**).
2. **VirtualBox**: Hosted hypervisor (**Type-2**).
3. **Native Linux LXC**: Linux **OS-level virtualization / containerization**.

> [!IMPORTANT]
> **Experimental Integrity Guarantee**:
> - **100% Real Experimental Measurements**: Zero synthetic demo metrics, zero fabricated performance data.
> - **Traceable Provenance**: Every displayed result is directly mapped to an exact shell command, timestamp, exit code, and raw `stdout`/`stderr`.
> - **Honest Statuses**: Environments that are offline or unavailable are recorded as `unavailable`. Missing data is **NEVER converted to zero**.

---

## 1. Virtualization Technology Taxonomy

- **KVM (Kernel-based Virtual Machine)**: Turns the Linux host kernel into a hypervisor via loadable kernel modules (`kvm_intel.ko`). Leverages CPU hardware extensions (Intel VT-x) so guest code executes directly in VMX non-root mode. Widely classified as Type-1 or Type-1-like because the hypervisor operates directly at the core operating kernel layer.
- **QEMU (Quick Emulator)**: Works in conjunction with KVM as the user-space Virtual Machine Monitor (VMM) and device emulator (providing paravirtualized `virtio` block/net devices, ACPI, and interrupt handling).
- **VirtualBox**: A traditional Type-2 hosted hypervisor running as a user-space application relying on out-of-tree host kernel drivers (`vboxdrv.ko`). Mediates all guest CPU execution, storage access, and memory paging through its own VMM process on top of the host OS scheduler.
- **Native LXC (LinuX Containers)**: Operating system-level virtualization sharing the host Linux kernel. Achieves process isolation via kernel **namespaces** (`pid`, `net`, `mnt`, `ipc`, `uts`, `user`) and fine-grained resource accounting via **cgroups v2** (`/sys/fs/cgroup`), introducing virtually zero hypervisor overhead.

---

## 2. Directory Architecture

```text
cc2/
├── benchmark/        # Execution driver and guest environment state probes
├── workloads/        # Deterministic C/C++ CPU and memory compute kernels
│   ├── cpu_workload.c
│   ├── memory_workload.c
│   └── Makefile
├── collector/        # Safe host introspection and discovery engine
│   ├── common.py             # Result schemas, safety validators, safe subprocess wrappers
│   ├── inventory_collector.py # Automated host and virtualization discovery agent
│   └── env_discovery.sh      # Safe discovery shell runner
├── analysis/         # Statistical processing and anti-fabrication validator
│   ├── stats.py              # Real statistical aggregation (mean, median, stdev, IQR)
│   └── validator.py          # Provenance verification against raw stdout
├── results/          # Machine-readable artifacts
│   ├── host_inventory.json   # Full host hardware, kernel, network, and hypervisor specs
│   └── benchmark_runs.jsonl  # Append-only traceable execution log
├── dashboard/        # React + TypeScript + Vite interactive visualization UI
│   ├── src/
│   │   ├── App.tsx           # Dashboard layout, metrics cards, provenance drilldown
│   │   ├── data/             # Live synchronized inventory and benchmark logs
│   │   └── index.css         # High-tech dark-theme UI styles
│   ├── package.json
│   └── vite.config.ts
├── docs/             # Technical specifications & documentation
│   ├── HOST_INVENTORY.md     # Host hardware, kernel, and hypervisor inventory
│   ├── ARCHITECTURE.md       # Architectural blueprints and isolation theory
│   ├── SAFETY.md             # Non-destructive safety boundaries and guardrails
│   └── EXPERIMENT_PLAN.md    # Scientific protocol, identical parameters, and roadmap
├── tests/            # Automated non-destructive unit and integration test suite
│   ├── test_structure.py     # Verifies directory layout and key files
│   ├── test_safety.py        # Verifies rejection of dangerous disk commands
│   ├── test_workloads.py     # Verifies C workloads compile and yield deterministic output
│   ├── test_collector.py     # Verifies integrity of host discovery data
│   ├── test_result_schema.py # Verifies provenance, schema, and anti-zeroing rules
│   └── run_all_tests.sh      # Master test suite runner
└── README.md
```

---

## 3. Host System Summary (Discovered Live)

- **Host Processor**: 12th Gen Intel(R) Core(TM) i5-12450H (12 Logical CPUs, 8 Cores)
- **Virtualization Flags**: VT-x (Intel VMX) Enabled
- **Host Memory**: 15.6 GiB Physical RAM | 4.0 GiB Swap
- **Host OS**: Ubuntu 24.04.5 LTS | Kernel `7.0.0-31-generic` (x86_64)
- **Discovered KVM Domain**: `ubuntu24.04` (2 vCPUs, 2048 MB RAM)
- **Discovered VirtualBox VM**: `Ubuntu-Server-VBox` (2 vCPUs, 2048 MB RAM)
- **Discovered Native LXC**: Version 5.0.3, bridge `lxcbr0`, container `lxc-ubuntu`

---

## 4. Execution & Reproducibility Guide

### 4.1 Run Pre-Flight Environment Validation
```bash
./benchmark/validate_environment.sh
```
Checks for GCC, Python 3, perf, strace, pidstat, mpstat, curl, libvirt/KVM, VirtualBox, and Native LXC. Missing optional tools (`fio`, `iperf3`) are recorded with `status=unavailable` without error.

### 4.2 Compile & Verify Deterministic Workload Binaries
```bash
make -C workloads all
```

### 4.3 Run Quality Assurance & Safety Tests
```bash
./tests/run_all_tests.sh
```
Executes 15 comprehensive unit, integration, schema, safety, and parser validation suites.

### 4.4 Execute Full Experimental Benchmarking (Phase 8 Protocol)
Execute sequentially with 1 warmup and 5 measured runs per test domain:
```bash
# 1. Bare-metal Host Baseline
./benchmark/runner.sh --environment host --full

# 2. Type-1 Hypervisor (KVM/QEMU)
./benchmark/runner.sh --environment kvm --full

# 3. Type-2 Hypervisor (Oracle VirtualBox)
./benchmark/runner.sh --environment virtualbox --full

# 4. Native Linux Container (LXC)
./benchmark/runner.sh --environment lxc --full
```

Or run rapid smoke test across all environments:
```bash
./benchmark/runner.sh --all --quick
```

### 4.5 Compute Statistical Distributions & Generate Reports
```bash
python3 analysis/analyze.py
```
Outputs:
- `results/report_summary.json`: Executive synthesis and comparative metric matrix.
- `results/final_results.json`: Full versioned records with percentiles (p50, p95, p99), mean, median, min, max, stdev, and CV%.
- `results/final_results.csv`: Tabular metric summary.

### 4.6 Launch the 16-Page Technical Virtualization Laboratory Dashboard
```bash
cd dashboard
npm install
npm run build
npm run preview -- --host 127.0.0.1 --port 4173
```
Preview at: `http://127.0.0.1:4173/`

---

## 5. Technical Documentation Index

Comprehensive documentation is provided in the `docs/` directory:
- [FINAL_RESULTS.md](file:///home/karthik-chakala/Downloads/CC2/docs/FINAL_RESULTS.md): Empirical measurement numbers, statistical tables, and comparative observations.
- [METHODOLOGY.md](file:///home/karthik-chakala/Downloads/CC2/docs/METHODOLOGY.md): Scientific experimental design, binary parity, warmup sizing, and statistical formulations.
- [REPRODUCIBILITY.md](file:///home/karthik-chakala/Downloads/CC2/docs/REPRODUCIBILITY.md): Step-by-step reproduction instructions from a clean environment.
- [LIMITATIONS.md](file:///home/karthik-chakala/Downloads/CC2/docs/LIMITATIONS.md): Technical constraints, Alder Lake asymmetric CPU scheduling, and perf counter security levels.
- [EXPERIMENTAL_VALIDATION.md](file:///home/karthik-chakala/Downloads/CC2/docs/EXPERIMENTAL_VALIDATION.md): Quality assurance audit, safety interceptors, and determinism verification.
- [ADVANCED_METRICS.md](file:///home/karthik-chakala/Downloads/CC2/docs/ADVANCED_METRICS.md): Profiling specifications for strace, pidstat, HTTP latency, and thermal collectors.
- [DASHBOARD.md](file:///home/karthik-chakala/Downloads/CC2/docs/DASHBOARD.md): Architecture of the 16-page React/TypeScript technical dashboard.
- [SAFETY.md](file:///home/karthik-chakala/Downloads/CC2/docs/SAFETY.md): Non-destructive safety boundaries and guardrails.
- [HOST_INVENTORY.md](file:///home/karthik-chakala/Downloads/CC2/docs/HOST_INVENTORY.md): Host hardware and virtualization environment specs.

---

## 6. Non-Destructive Safety Guarantees

All CC2 software adheres to strict safety boundaries documented in [docs/SAFETY.md](file:///home/karthik-chakala/Downloads/CC2/docs/SAFETY.md). Direct disk formatting, block device overwriting, partition manipulation, and VM deletions are permanently blocked at the software level by `collector/common.py:SafetyValidator`.

