# CC2 Virtualization Benchmarking: Experimental Limitations & Threats to Validity

Understanding experimental limitations is vital for objective interpretation of virtualization benchmarks. This document details the constraints, external variables, and threats to validity identified in the CC2 benchmark suite.

---

## 1. Heterogeneous CPU Architecture (Alder Lake P-cores vs E-cores)
- **Host Processor**: 12th Gen Intel Core i5-12450H.
- **Physical Layout**: 4 Performance cores (P-cores with Golden Cove microarchitecture, 2 threads each) and 4 Efficient cores (E-cores with Gracemont microarchitecture, 1 thread each), totaling 12 logical threads.
- **Impact on Variance**:
  - The Linux kernel scheduler (`sched_ext` / CFS / EEVDF) migrates benchmark threads dynamically across P-cores (higher clock frequency, wider execution width) and E-cores (lower clock frequency, power-optimized).
  - This explains the observed Coefficient of Variation (% CV) in CPU arithmetic tests (23.7% on Host, 24.5% on KVM, 42.6% on VirtualBox, and 27.3% on LXC).
  - Virtual machines configured with 2 vCPUs may be scheduled across asymmetric physical core combinations (e.g. 1 P-core + 1 E-core vs 2 E-cores), causing run-to-run execution time variance.

---

## 2. Kernel Security & Performance Counter Access Restrictions
- **Security Parameter**: `/proc/sys/kernel/perf_event_paranoid` is set to `4` on Ubuntu 24.04.
- **Limitation**:
  - Unprivileged users cannot access low-level CPU performance monitoring units (PMU) such as hardware cycles, retired instructions, and hardware cache miss counters via `perf stat`.
- **Methodological Handling**:
  - CC2 strictly records `status: "unavailable"` and preserves the exact reason (`perf_event_paranoid=4 restricted`) rather than fabricating estimated or mock cycle counts.
  - Software telemetry (page faults, voluntary/involuntary context switches, wall clock time, RSS memory) is gathered via `/usr/bin/time -v` and `pidstat`.

---

## 3. Storage Layer & Disk Format Asymmetries
- **Host Baseline**: Direct file I/O on ext4 file system mounted on a PCIe Gen 4 NVMe SSD.
- **KVM/QEMU**: Virtual disk backed by a `qcow2` image with write-back caching.
- **VirtualBox**: Virtual disk backed by a dynamic `VDI` image with host I/O cache enabled.
- **Native LXC**: Directory-backed container root filesystem sharing the host's underlying ext4 page cache directly.
- **Limitation**:
  - Different virtualization formats introduce varying levels of metadata indirection and copy-on-write overhead.
  - While identical block sizes (4K, 1M) and sync modes (`O_DIRECT` or `fdatasync`) were applied when available, intrinsic hypervisor storage stack differences affect I/O latency profiles.

---

## 4. Host OS Daemon Interference & Thermal Throttling
- **Desktop Environment**: The host operates a full desktop environment (GNOME Shell, display server, background messaging and update daemons).
- **Thermal Governors**: Laptop form-factor dynamic frequency scaling (`intel_pstate`) reacts to CPU package temperatures.
- **Mitigation Applied**:
  - 2.0-second pre-run and post-run stabilization periods were strictly enforced.
  - Warmup iterations were executed before recording measured runs.
  - Run isolation checks verified that no competing virtual machines were running simultaneously.

---

## 5. Non-Destructive Benchmark Safety Constraints
- **Invariant**: In compliance with strict safety directives, all storage benchmarks operated strictly within regular files in user-space or scratch directories (`/tmp/cc2_storage_test.dat`).
- **Limitation**:
  - Direct raw block device write benchmarks (e.g., writing directly to unformatted partitions) were intentionally disallowed to prevent risk of host partition corruption or data loss.
  - Consequently, raw block-device throughput tests reflect file-system-mediated I/O rather than raw hardware device saturation.
