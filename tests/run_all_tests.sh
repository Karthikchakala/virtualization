#!/usr/bin/env bash
# ==============================================================================
# run_all_tests.sh - Comprehensive Non-Destructive Test Runner for CC2
# Executes all unit, integration, and verification suites.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=================================================="
echo "RUNNING CC2 COMPREHENSIVE TEST SUITE (22 SUITES)"
echo "=================================================="

cd "$PROJECT_ROOT"

echo "[1/22] Verifying Project Layout & File Integrity..."
python3 -m unittest tests/test_structure.py

echo "[2/22] Verifying Safety Boundaries & Dangerous Command Interceptors..."
python3 -m unittest tests/test_safety.py

echo "[3/22] Testing Deterministic CPU Workload..."
python3 -m unittest tests/test_cpu_workload.py

echo "[4/22] Testing Deterministic Memory Workload..."
python3 -m unittest tests/test_memory_workload.py

echo "[5/22] Testing Measurement Engine & Telemetry Parser..."
python3 -m unittest tests/test_measurement_parser.py

echo "[6/22] Testing Statistics Engine, Percentiles & Missing Values..."
python3 -m unittest tests/test_statistics.py

echo "[7/22] Testing Workloads Package Manifest & Binary SHA256..."
python3 -m unittest tests/test_manifest.py

echo "[8/22] Testing Host Inventory Collector..."
python3 -m unittest tests/test_collector.py

echo "[9/22] Testing Result Schema & Provability..."
python3 -m unittest tests/test_result_schema.py

echo "[10/22] Testing Invalid & Malformed Output Handling..."
python3 -m unittest tests/test_invalid_output.py

echo "[11/22] Testing KVM/QEMU Benchmark & Lifecycle Adapter..."
python3 -m unittest tests/test_kvm_adapter.py

echo "[12/22] Testing VirtualBox Benchmark & Lifecycle Adapter..."
python3 -m unittest tests/test_vbox_adapter.py

echo "[13/22] Testing Native LXC Benchmark & Lifecycle Adapter..."
python3 -m unittest tests/test_lxc_adapter.py

echo "[14/22] Testing Unified Experiment Runner (runner.py & runner.sh)..."
python3 -m unittest tests/test_runner.py

echo "[15/22] Testing Advanced Performance Metrics (Strace, Scheduling, Thermal, Latency)..."
python3 -m unittest tests/test_advanced_metrics.py

echo "[16/22] Testing Configuration & Secret Management Subsystem..."
python3 -m unittest tests/test_configuration.py

echo "[17/22] Testing Unified Environment Adapters Subsystem..."
python3 -m unittest tests/test_adapters.py

echo "[18/22] Testing Common Workload Deployment & Verification Subsystem..."
python3 -m unittest tests/test_workload.py

echo "[19/22] Testing Unified Benchmark Execution Engine & Registry..."
python3 -m unittest tests/test_executor.py

echo "[20/22] Testing Full Benchmark Suite Domains & Metric Collection..."
python3 -m unittest tests/test_benchmark_suite.py

echo "[21/22] Testing Full Experiment Automation & Manifest Generation..."
python3 -m unittest tests/test_experiment_automation.py

echo "[22/23] Testing Dataset Validation, Anti-Fabrication & Quality Flags..."
python3 -m unittest tests/test_dataset_validation.py

echo "[23/23] Testing Backend REST API, Job Manager & Log Sanitization..."
python3 -m unittest tests/test_api_backend.py

echo ""
echo "=================================================="
echo "ALL 23 TEST SUITES PASSED CLEANLY WITH ZERO ERRORS!"
echo "=================================================="
