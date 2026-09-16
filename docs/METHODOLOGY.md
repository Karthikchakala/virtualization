# CC2 Virtualization Benchmarking: Experimental Methodology

## 1. Research Philosophy & Objective
The CC2 benchmarking suite is designed to conduct reproducible, empirical performance evaluations across three primary Linux virtualization and containerization paradigms alongside a native bare-metal host baseline:
- **Type-1 Hypervisor**: Linux KVM/QEMU via libvirt
- **Type-2 Hypervisor**: Oracle VirtualBox
- **Containerization**: Native Linux Containers (LXC)
- **Host Baseline**: Direct host execution on Ubuntu 24.04 LTS

The objective is to gather objective, empirical measurement data across compute, memory, storage, networking, startup, syscall, and scheduling domains without subjective bias or predetermined conclusions.

---

## 2. Invariant: Identical Deterministic Workloads
A fundamental flaw in comparative virtualization benchmarking is using disparate benchmarks or binaries across environments. CC2 enforces complete binary and algorithmic parity:
1. **Identical Binaries**: The exact same C/C++ source code is compiled once into self-contained statically-linked or distribution-compatible binaries inside `workloads/dist/`.
2. **Reproducible Compilation**: Built with `-O2 -Wall -fno-omit-frame-pointer -D_GNU_SOURCE` using GCC.
3. **SHA-256 Manifest Tracking**: Workload binaries are hashed before execution; checksums are embedded in execution metadata.
4. **Deterministic Algorithmic Checksums**:
   - The CPU benchmark generates a pseudo-random floating point matrix using seed `42` and computes a 64-bit checksum of the multiplied result matrix.
   - The memory benchmark walks buffers with deterministic linear-congruential pseudo-random access and returns an invariant verification checksum.
   - The scheduling benchmark passes known bit patterns over a pipe and computes an accumulating XOR/addition checksum.
5. **Anti-Optimization**: Checksums force the compiler to retain all memory writes and floating point arithmetic, preventing compiler dead-code elimination.

---

## 3. Strict Run Isolation & Stabilization Protocol

### Sequential Execution Enactment
Running hypervisors concurrently causes CPU cache thrashing, memory bus contention, and scheduler distortions. CC2 strictly prohibits concurrent execution:
- Environments are executed strictly one at a time.
- Before starting any environment, `IsolationManager.ensure_all_environments_stopped()` verifies that other VMs and containers are shut down.
- Active processes matching other hypervisors (`qemu-system-x86_64`, `VirtualBoxVM`, `lxc-start`) are checked and verified stopped.

### Thermal & Scheduler Stabilization Delays
1. **Pre-Run Stabilization**: A 2.0-second delay is enforced immediately before workload execution begins. Host load averages, free memory, and CPU frequency governors are recorded.
2. **Post-Run Cooldown**: A 2.0-second cooldown is enforced following environment shutdown to allow kernel background threads (`kswapd`, `kcompactd`, journaling threads) to settle.

---

## 4. Run Sizing: Warmup vs Measured Runs
To eliminate initialization noise (such as page faults on first touch, dynamic library relocation, and CPU frequency ramp-up), CC2 uses a structured two-phase execution cycle:
- **Warmup Run**: 1 execution iteration whose measurements are recorded separately or discarded from steady-state statistical aggregates.
- **Measured Runs**: 5 sequential iterations executed in steady state under identical parameters.

---

## 5. Anti-Fabrication & Traceability Invariants
CC2 adheres to strict provenance standards:
1. **Raw Output Retention**: Every run stores the complete raw command string, exit code, execution timestamp, standard output, and standard error.
2. **Zero Coercion Policy**: Missing tools, unsupported hardware counters, or skipped tests are **never** coerced to `0` or `0.0`. They are assigned `status: "unavailable"` with explicit explanatory text.
3. **Provable Traceability**: Any reported numeric metric in `runs.json` or `final_results.csv` must be directly parseable from the raw `stdout` or kernel telemetry captured in that specific run.

---

## 6. Statistical Computation Engine
Summary statistics are computed using standard sample formulas:

### Sample Mean ($\bar{x}$)
$$\bar{x} = \frac{1}{n}\sum_{i=1}^{n} x_i$$

### Sample Standard Deviation ($s$)
$$s = \sqrt{\frac{1}{n-1}\sum_{i=1}^{n} (x_i - \bar{x})^2} \quad (n > 1)$$

### Coefficient of Variation (% CV)
$$\text{CV} = \left(\frac{s}{|\bar{x}|}\right) \times 100\%$$
*Provides a scale-independent metric of run-to-run dispersion and measurement stability.*

### Percentiles ($p_{50}, p_{95}, p_{99}$)
Computed via linear interpolation between nearest ranks on sorted sample series $X = \{x_1, \dots, x_n\}$:
$$\text{Rank} = \frac{p}{100} \times (n - 1)$$
where $p_{50}$ represents the sample median.
