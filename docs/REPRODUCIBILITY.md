# CC2 Virtualization Benchmarking: Reproducibility Guide

This guide provides step-by-step instructions to reproduce the experimental benchmarks and statistical analysis from a fresh clone of the repository.

---

## 1. System Requirements & Prerequisites
- **Host OS**: Ubuntu Linux (22.04 LTS or 24.04 LTS recommended)
- **Architecture**: x86_64 with hardware virtualization enabled (Intel VT-x / AMD-V)
- **Compiler**: GCC (`build-essential`)
- **Runtime**: Python 3.10+, Node.js 18+ and npm
- **Virtualization Packages**:
  - KVM/libvirt: `qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils`
  - VirtualBox: `virtualbox` (6.x or 7.x)
  - Native LXC: `lxc lxc-utils`

---

## 2. Pre-Flight Verification
Before running any benchmark, verify that the virtualization subsystems and toolchains are present:

```bash
cd /home/karthik-chakala/Downloads/cc2
./benchmark/validate_environment.sh
```

Expected Output:
```text
[1/4] Checking Core & Benchmarking Tool Dependencies...
  [+] gcc: FOUND
  [+] python3: FOUND
  [+] perf: FOUND
  [+] strace: FOUND
  [+] pidstat: FOUND
  [+] mpstat: FOUND
  [+] curl: FOUND
[2/4] Validating Virtualization Subsystems...
  [+] KVM/QEMU: Available via libvirt
  [+] VirtualBox: Available via VBoxManage
  [+] Native LXC: Available
```

---

## 3. Workload Compilation
Compile the deterministic C/C++ workload binaries and compute their SHA-256 signatures:

```bash
make -C workloads all
```

Verify the compiled binaries in `workloads/dist/`:
```bash
ls -lh workloads/dist/
sha256sum workloads/dist/*
```

---

## 4. Running the Quality Assurance Test Suites
Execute the non-destructive automated test suite covering 15 validation domains:

```bash
./tests/run_all_tests.sh
```

All 15 test suites should pass with exit code `0`.

---

## 5. Executing the Experimental Benchmarks

### Option A: Complete Sequential Evaluation Across All Platforms
To run the full experimental protocol (1 warmup + 5 measured runs per test domain):

```bash
# 1. Host Baseline
./benchmark/runner.sh --environment host --full

# 2. KVM / QEMU
./benchmark/runner.sh --environment kvm --full

# 3. Oracle VirtualBox
./benchmark/runner.sh --environment virtualbox --full

# 4. Native LXC
./benchmark/runner.sh --environment lxc --full
```

### Option B: Quick Evaluation Mode
For rapid verification (1 warmup + 2 measured runs):

```bash
./benchmark/runner.sh --all --quick
```

### Option C: Targeted Test Domain Evaluation
To run specific test domains:

```bash
./benchmark/runner.sh --environment host --test cpu --test memory --quick
```

---

## 6. Computing Statistics & Generating Reports
Run the statistical analysis engine to aggregate runs and generate the summary reports:

```bash
python3 analysis/analyze.py
```

Generated outputs:
- `results/report_summary.json`
- `results/final_results.json`
- `results/final_results.csv`

---

## 7. Building and Previewing the Interactive Dashboard

```bash
cd dashboard
npm install
npm run typecheck
npm run lint
npm run build
npm run preview -- --host 127.0.0.1 --port 4173
```

Open your browser to:
`http://127.0.0.1:4173/`
