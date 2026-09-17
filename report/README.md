# Academic Project Report: Virtualization Lab

**Title**: Virtualization Lab: Performance and Isolation Analysis of KVM/QEMU, VirtualBox, and Native LXC  
**Institution**: Indian Institute of Information Technology, Design and Manufacturing (IIITDM), Kurnool  
**Department**: Department of Computer Science and Engineering  
**Authors**: 
- Chakala Karthik (Roll No: 123CS0038)
- Shaik Venkat (Roll No: 123CS0037)  
**Faculty Guide**: Dr. Anil Kumar, Assistant Professor, Department of CSE  
**Academic Year**: 2025–2026 (September 2026)  
**Report Length**: **Exactly 22 Pages** (Strict requirement: 20–24 pages)  
**Output Document**: [`report/main.pdf`](file:///home/karthik-chakala/Downloads/CC2/report/main.pdf)

---

## 1. Directory Structure

```text
report/
├── main.tex                  # Master document: geometry, packages, cover page, TOC, includes
├── references.bib            # BibTeX bibliography with 12 authentic academic & tool citations
├── main.pdf                  # Compiled 22-page publication-grade PDF
├── README.md                 # Documentation and build instructions
├── figures/                  # High-resolution vector & raster visual assets
│   ├── iiitdm_logo.png       # Official bilingual IIITDM Kurnool emblem
│   ├── dashboard_overview.png   # Dashboard Overview & System Status
│   ├── dashboard_results.png    # Results Matrix with CSV export & JSON view
│   ├── dashboard_cpu.png        # CPU Microbenchmark Telemetry & Run Cards
│   ├── dashboard_scheduling.png # Thread Scheduling Latency & Pipe Ping-Pong
│   ├── dashboard_kvm.png        # KVM/QEMU Domain Inspector & XML config
│   └── dashboard_lxc.png        # Native LXC Container Inspector & cgroups v2
└── sections/                 # Modular LaTeX chapter inputs
    ├── 01_introduction.tex          # Sec 1: Motivation, Taxonomy, RQs, Scientific Integrity
    ├── 02_virtualization_concepts.tex # Sec 2: VT-x, VMCS, EPT, KVM/VBox TikZ, LXC, Table 1 Taxonomy
    ├── 03_system_architecture.tex    # Sec 3: E2E Architecture TikZ, Lifecycle Flowchart, Stats formulas
    ├── 04_experimental_environment.tex # Sec 4: Table 2 Testbed Topology, Table 3 Workload Invariants
    ├── 05_benchmark_methodology.tex # Sec 5: C99 microbenchmarks, FNV-1a hashes, syscall/context switch
    ├── 06_implementation.tex        # Sec 6: Runner, adapters, concurrency locking, process scavenging
    ├── 07_results_analysis.tex      # Sec 7: Table 4 Microbenchmarks, Table 5 Network/App, Table 6 Startup, Table 7 Isolation
    ├── 08_dashboard.tex             # Sec 8: React/Tailwind frontend, REST API, UI Walkthrough
    ├── 09_discussion.tex            # Sec 9: Table 8 Trade-off Matrix, Virtualization Tax, Type-1/2, Guidelines
    └── 10_conclusion.tex            # Sec 10: Contributions, Synthesis, Future Work (microVMs, TDX, eBPF)
```

---

## 2. Report Invariants and Structural Integrity

1. **Cover Page Invariant**:
   - **Page 1 ONLY**: Contains the bilingual IIITDM Kurnool insignia, institution and department titles, full report title, course subtitle, student details, faculty advisor details, and academic year.
2. **Table of Contents and Immediate Start**:
   - **Page 2**: Table of Contents followed immediately by Section 1: Introduction (no blank pages between cover and index).
3. **Page Budget**:
   - **Strict Requirement**: 20–24 pages.
   - **Compiled Count**: **22 pages**.
   - Dedicated References section occupying Page 22 with all 12 cited academic papers, manuals, and tool specifications.
4. **Academic Scientific Integrity**:
   - **Zero Synthetic Data Fabrication**: Every single number is drawn from real hardware measurements captured on the Intel Core i5-12450H testbed (`dashboard/src/data/runs.json`, `inventory.json`).
   - Missing interfaces (e.g. `kernel.perf_event_paranoid=4`) or absent packages (`iperf3`, `fio`) are transparently logged as `UNAVAILABLE` or `FAILED`.
   - **Zero Subjective Scoring**: No arbitrary "winner" declarations or weighting models; pure empirical descriptive reporting.

---

## 3. Compilation Instructions

The project provides a self-contained, static `Tectonic 0.17.0` modern XeTeX engine at `.tools/bin/tectonic` requiring zero external TeX Live installation.

### Compile PDF using Tectonic (Recommended)

From the project root:

```bash
.tools/bin/tectonic report/main.tex
```

Verify the generated PDF page count:

```bash
pdfinfo report/main.pdf | grep Pages
# Expected output: Pages: 22
```

### Alternative Compilation (TeX Live / XeLaTeX)

If compiling in standard TeX Live environments:

```bash
cd report
xelatex main.tex
bibtex main
xelatex main.tex
xelatex main.tex
pdfinfo main.pdf | grep Pages
```

---

## 4. Evaluated Workload Summary & Data Provenance

| Workload Identifier | Target Metric | Canonical Validation Checksum / Condition |
|:---|:---|:---|
| `cpu_deterministic` | Floating-Point Throughput (GFLOPS) | FNV-1a Hash: `0x7e83d4c61ad5adb8` |
| `memory_deterministic` | Sequential / Strided Memory Bandwidth (MB/s) | 128 MB buffer, 4 sequential passes |
| `syscall_deterministic` | Ring 3 $\to$ Ring 0 Transition Latency (ns) | 200,000 $\times$ `getpid()` system calls |
| `scheduling_deterministic` | Voluntary Context Switch Latency ($\mu$s) | 40,000 context switches via POSIX pipes |
| `network_ping` | Virtual Software Bridge RTT (ms) | 5 ICMP packets, 0% packet loss |
| `app_latency` | HTTP Request / Connect / TTFB Latency (ms) | 100 sequential requests, 100% HTTP 200 |
| `startup_lifecycle` | Cold-Start Lifecycle Breakdown (s) | $\Delta t_{\text{vmm}} + \Delta t_{\text{os}} + \Delta t_{\text{net}}$ |
| `isolation_audit` | Security Boundary Inspection | Namespace inodes, `uname -r`, cgroups v2 |
