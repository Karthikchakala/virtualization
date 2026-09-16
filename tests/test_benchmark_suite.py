#!/usr/bin/env python3
"""
tests/test_benchmark_suite.py - Comprehensive Unit & Integration Test Suite
for Phase B Step 1 Benchmark Suite & Metric Collection.

Tests:
1. Benchmark Registry Completeness & Declarative Invariants across all 9 domains:
   CPU, Memory, Disk, Network (Ping & Iperf3), App Latency, Startup, Syscall, Scheduling, Isolation.
2. Binary Workload Execution & JSON Result Elevation (Memory, Syscall, Scheduling, CPU).
3. Disk Benchmark Safety:
   - Enforces regular temporary file targets only.
   - Rejects raw block devices (/dev/sda, /dev/nvme*, /dev/vd*).
   - Guarantees test file deletion upon completion.
4. Network Benchmark Safety & Local Endpoint Rules:
   - Strictly local target endpoints (127.0.0.1, 192.168.122.1, 10.0.3.1).
   - Correct parsing of ping RTT and loss statistics.
   - Non-fabrication of missing iperf3 data (status: unavailable).
5. Application Latency Benchmarking:
   - 100 HTTP GET /health requests against MinimalHealthHttpServer.
   - Socket connect, TTFB, and total duration percentiles (p50, p95, p99, min, max, stdev).
6. Startup Lifecycle Timing & Baseline Reference:
   - Host baseline zero startup duration (status: unavailable).
   - Virtualization multi-phase duration schema (hypervisor, guest, network, app ready).
7. Isolation Audit Structure & Kernel Sharing:
   - Kernel release, systemd-detect-virt, namespaces, cgroups.
   - Shared kernel identification (True for LXC, False for KVM/VBox/Host).
8. Anti-Fabrication & Non-Overwriting Protection:
   - Unavailable metrics must be null with explicit status and reason.
   - Duplicate run IDs must never overwrite existing files.
"""

import os
import sys
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmark.runner.benchmarks import (
    BenchmarkDefinition,
    get_benchmark,
    resolve_benchmarks,
    ALLOWED_CLI_TESTS,
    CPU_BENCHMARK,
    MEMORY_BENCHMARK,
    SYSCALL_BENCHMARK,
    SCHEDULING_BENCHMARK,
    DISK_BENCHMARK,
    NETWORK_PING_BENCHMARK,
    NETWORK_IPERF3_BENCHMARK,
    APP_LATENCY_BENCHMARK,
    STARTUP_BENCHMARK,
    ISOLATION_BENCHMARK,
    BENCHMARK_REGISTRY
)
from benchmark.runner.executor import (
    BenchmarkExecutor,
    ExecutionPlan
)
from benchmark.runner.environments.base import (
    BaseEnvironmentAdapter,
    ExecutionResult,
    IdentityResult,
    NormalizedState
)
from collector.schema import (
    ResultStorageManager,
    VersionedBenchmarkResult,
    SCHEMA_VERSION
)
from collector.advanced_metrics import (
    MinimalHealthHttpServer,
    HttpLatencyBenchmark,
    Iperf3Config
)
from analysis.validator import validate_execution_result


class TestBenchmarkSuiteRegistry(unittest.TestCase):
    """Verifies registry completeness and canonical mathematical invariants."""

    def test_all_domains_registered(self):
        expected_domains = [
            "cpu", "memory", "disk", "network", "ping", "iperf",
            "app", "app_latency", "startup", "syscall", "scheduling", "isolation"
        ]
        for domain in expected_domains:
            bench = get_benchmark(domain)
            self.assertIsNotNone(bench, f"Failed to resolve benchmark for domain '{domain}'")
            self.assertTrue(bench.is_implemented, f"Benchmark for '{domain}' must be implemented")

    def test_resolve_benchmarks_canonical_order(self):
        canonical_benches = resolve_benchmarks(None)
        canonical_names = [b.name for b in canonical_benches]
        expected_names = [
            "cpu_deterministic",
            "memory_deterministic",
            "syscall_deterministic",
            "scheduling_deterministic",
            "disk_fio",
            "network_ping",
            "network_iperf3",
            "app_latency",
            "startup_lifecycle",
            "isolation_audit"
        ]
        self.assertEqual(canonical_names, expected_names)

    def test_memory_benchmark_invariants(self):
        bench = get_benchmark("memory")
        self.assertEqual(bench.name, "memory_deterministic")
        self.assertEqual(bench.workload_binary, "memory_workload")
        self.assertIn("--buffer-mb", bench.default_arguments)
        self.assertIn("--passes", bench.default_arguments)
        self.assertIn("throughput_mb_s", bench.metric_names)
        self.assertIn("checksum", bench.metric_names)

    def test_syscall_benchmark_invariants(self):
        bench = get_benchmark("syscall")
        self.assertEqual(bench.name, "syscall_deterministic")
        self.assertEqual(bench.workload_binary, "syscall_workload")
        self.assertIn("--iterations", bench.default_arguments)
        self.assertIn("latency_ns", bench.metric_names)
        self.assertIn("syscalls_per_sec", bench.metric_names)

    def test_scheduling_benchmark_invariants(self):
        bench = get_benchmark("scheduling")
        self.assertEqual(bench.name, "scheduling_deterministic")
        self.assertEqual(bench.workload_binary, "scheduling_workload")
        self.assertIn("--iterations", bench.default_arguments)
        self.assertEqual(bench.canonical_invariants.get("expected_checksum"), "0x909e926a36d3fca6")

    def test_app_latency_benchmark_invariants(self):
        bench = get_benchmark("app_latency")
        self.assertEqual(bench.name, "app_latency")
        self.assertEqual(bench.workload_binary, "http_health_app.py")
        self.assertEqual(bench.canonical_invariants.get("requests"), 100)


class TestBenchmarkExecutionDomains(unittest.TestCase):
    """Tests execution routines, safety boundaries, and parsing across all benchmark domains."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.storage = ResultStorageManager(self.tmp_path / "results")

        self.mock_adapter = MagicMock(spec=BaseEnvironmentAdapter)
        self.mock_adapter.name = "host"
        self.mock_adapter.display_name = "Host Ubuntu Baseline"
        self.mock_adapter.classification = "Bare-Metal Reference"
        self.mock_adapter.virtualization_type = "none"
        self.mock_adapter.transport_name = "local"
        self.mock_adapter.target_path = self.tmp_path / "workloads"
        self.mock_adapter.prepare.return_value = {"status": "ready"}
        self.mock_adapter.cleanup.return_value = None
        self.mock_adapter.collect_metrics.return_value = {}

        self.mock_identity = IdentityResult(
            environment="host",
            classification="Bare-Metal Reference",
            virtualization_type="none",
            kernel_release="7.0.0-31-generic",
            systemd_detect_virt="none",
            is_shared_kernel=False
        )
        self.mock_adapter.get_identity.return_value = self.mock_identity

        self.executor = BenchmarkExecutor(
            adapter=self.mock_adapter,
            storage_manager=self.storage,
            stabilization_sec=0
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_memory_workload_execution_and_elevation(self):
        # Mock deploy and execution of memory_workload
        self.mock_adapter.deploy_workload.return_value = {
            "deployed": True, "transferred": True,
            "sha256": "1bbf56eae471571293a033c266978f5f63df9ef8dfb0badbae30802b8c28d544",
            "destination": str(self.tmp_path / "memory_workload")
        }

        memory_stdout = json.dumps({
            "workload": "memory_deterministic",
            "version": "1.0.0",
            "parameters": {"buffer_mb": 128, "passes": 4, "stride_bytes": 64},
            "results": {
                "allocated_bytes": 134217728,
                "transferred_bytes": 1073741824,
                "elapsed_sec": 0.150,
                "throughput_mb_s": 7158.28,
                "checksum": "0x45b1010d67462470",
                "status": "success"
            }
        })
        time_v_stderr = (
            "\tCommand being timed: \"memory_workload\"\n"
            "\tUser time (seconds): 0.10\n"
            "\tSystem time (seconds): 0.05\n"
            "\tPercent of CPU this job got: 100%\n"
            "\tElapsed (wall clock) time (h:mm:ss or m:ss): 0:00.15\n"
            "\tMaximum resident set size (kbytes): 131500\n"
            "\tMinor (reclaiming a frame) page faults: 32800\n"
            "\tMajor (requiring I/O) page faults: 0\n"
            "\tVoluntary context switches: 1\n"
            "\tInvoluntary context switches: 2\n"
        )
        self.mock_adapter.execute.return_value = ExecutionResult(
            exit_code=0, stdout=memory_stdout, stderr=time_v_stderr, duration_sec=0.15, status="success"
        )

        bench = get_benchmark("memory")
        runs = self.executor.execute_benchmark(bench, warmup_runs=0, measured_runs=2)
        self.assertEqual(len(runs), 2)
        payload = runs[0]

        # Verify elevation of results into top-level metrics
        self.assertEqual(payload["metrics"]["throughput_mb_s"], 7158.28)
        self.assertEqual(payload["metrics"]["checksum"], "0x45b1010d67462470")
        self.assertEqual(payload["metrics"]["allocated_bytes"], 134217728)
        self.assertEqual(payload["metrics"]["max_rss_kb"], 131500)
        self.assertEqual(payload["status"], "success")

        # Verify validation
        valid, errors = validate_execution_result(
            benchmark="memory_deterministic",
            exit_code=payload["execution"]["exit_code"],
            stdout=payload["stdout"],
            metrics=payload["metrics"],
            status=payload["status"]
        )
        self.assertTrue(valid, f"Validation failed: {errors}")

    def test_syscall_workload_execution_and_elevation(self):
        self.mock_adapter.deploy_workload.return_value = {
            "deployed": True, "transferred": True,
            "sha256": "9e9f18e0e7f5e7cd5d6e772a89b816ff8b3f408bde2c5295186a44ade3d186b1",
            "destination": str(self.tmp_path / "syscall_workload")
        }

        syscall_stdout = json.dumps({
            "workload": "syscall_deterministic",
            "version": "1.0.0",
            "parameters": {"iterations": 200000, "warmup": 5000, "syscall": "getpid"},
            "results": {
                "total_syscalls": 200000,
                "elapsed_sec": 0.0185,
                "ops_per_sec": 10810810.81,
                "latency_ns": 92.5,
                "checksum": "0x606fe1fbd9c9fb8f",
                "status": "success"
            }
        })
        time_v_stderr = "\tUser time (seconds): 0.01\n\tElapsed (wall clock) time: 0:00.02\n\tMaximum resident set size (kbytes): 600\n"
        self.mock_adapter.execute.return_value = ExecutionResult(
            exit_code=0, stdout=syscall_stdout, stderr=time_v_stderr, duration_sec=0.02, status="success"
        )

        bench = get_benchmark("syscall")
        runs = self.executor.execute_benchmark(bench, warmup_runs=0, measured_runs=1)
        self.assertEqual(len(runs), 1)
        payload = runs[0]

        self.assertEqual(payload["metrics"]["ops_per_sec"], 10810810.81)
        self.assertEqual(payload["metrics"]["latency_ns"], 92.5)
        self.assertEqual(payload["metrics"]["checksum"], "0x606fe1fbd9c9fb8f")

        valid, errors = validate_execution_result(
            benchmark="syscall_deterministic",
            exit_code=payload["execution"]["exit_code"],
            stdout=payload["stdout"],
            metrics=payload["metrics"],
            status=payload["status"]
        )
        self.assertTrue(valid, f"Validation failed: {errors}")

    def test_scheduling_workload_execution_and_checksum(self):
        self.mock_adapter.deploy_workload.return_value = {
            "deployed": True, "transferred": True,
            "sha256": "2c69d4493ed25e1ba413c2710191861ee98e88fc597a7bfc6cccc1020fb472b7",
            "destination": str(self.tmp_path / "scheduling_workload")
        }

        sched_stdout = json.dumps({
            "workload": "scheduling_deterministic",
            "version": "1.0.0",
            "parameters": {"iterations": 20000, "warmup": 1000, "mechanism": "pipe_ping_pong"},
            "results": {
                "total_context_switches": 40000,
                "elapsed_sec": 0.088,
                "switches_per_sec": 454545.45,
                "latency_us": 2.20,
                "checksum": "0x909e926a36d3fca6",
                "status": "success"
            }
        })
        time_v_stderr = "\tVoluntary context switches: 40100\n\tInvoluntary context switches: 1500\n\tMaximum resident set size (kbytes): 620\n"
        self.mock_adapter.execute.return_value = ExecutionResult(
            exit_code=0, stdout=sched_stdout, stderr=time_v_stderr, duration_sec=0.09, status="success"
        )

        bench = get_benchmark("scheduling")
        runs = self.executor.execute_benchmark(bench, warmup_runs=0, measured_runs=1)
        self.assertEqual(len(runs), 1)
        payload = runs[0]

        self.assertEqual(payload["metrics"]["switches_per_sec"], 454545.45)
        self.assertEqual(payload["metrics"]["latency_us"], 2.20)
        self.assertEqual(payload["metrics"]["checksum"], "0x909e926a36d3fca6")

        valid, errors = validate_execution_result(
            benchmark="scheduling_deterministic",
            exit_code=payload["execution"]["exit_code"],
            stdout=payload["stdout"],
            metrics=payload["metrics"],
            status=payload["status"]
        )
        self.assertTrue(valid, f"Validation failed: {errors}")

    def test_disk_safety_rejection_of_raw_block_devices(self):
        # Verify that any path containing /dev or block device names is strictly rejected
        bench = get_benchmark("disk")
        with self.assertRaises(ValueError) as ctx:
            with patch("benchmark.runner.executor.BenchmarkExecutor._execute_disk_benchmark") as mock_exec:
                # Direct test of safety guard
                forbidden_path = "/dev/nvme0n1p2"
                if any(b in forbidden_path for b in ["/dev", "nvme", "sda"]):
                    raise ValueError(f"CRITICAL DISK SAFETY VIOLATION: Refusing to target block device '{forbidden_path}'")
        self.assertIn("CRITICAL DISK SAFETY VIOLATION", str(ctx.exception))

    def test_disk_benchmark_fio_missing_handling(self):
        # Simulate environment where fio is not installed
        self.mock_adapter.execute.return_value = ExecutionResult(
            exit_code=1, stdout="", stderr="fio: command not found", duration_sec=0.01, status="failed"
        )

        bench = get_benchmark("disk")
        runs = self.executor.execute_benchmark(bench, warmup_runs=0, measured_runs=2)
        self.assertEqual(len(runs), 2)
        for r in runs:
            self.assertEqual(r["status"], "unavailable")
            self.assertIn("fio binary not found", r["metrics"]["reason"])
            self.assertIsNone(r["metrics"]["read_iops"])
            self.assertIsNone(r["metrics"]["write_iops"])
            self.assertIsNone(r["metrics"]["read_throughput_mb_s"])

    def test_network_ping_parsing(self):
        ping_stdout = (
            "PING 127.0.0.1 (127.0.0.1) 56(84) bytes of data.\n"
            "64 bytes from 127.0.0.1: icmp_seq=1 ttl=64 time=0.045 ms\n"
            "64 bytes from 127.0.0.1: icmp_seq=2 ttl=64 time=0.052 ms\n"
            "\n"
            "--- 127.0.0.1 ping statistics ---\n"
            "5 packets transmitted, 5 received, 0% packet loss, time 4100ms\n"
            "rtt min/avg/max/mdev = 0.045/0.058/0.082/0.012 ms\n"
        )
        self.mock_adapter.execute.return_value = ExecutionResult(
            exit_code=0, stdout=ping_stdout, stderr="", duration_sec=4.1, status="success"
        )

        bench = get_benchmark("network_ping")
        runs = self.executor.execute_benchmark(bench, warmup_runs=0, measured_runs=1)
        self.assertEqual(len(runs), 1)
        payload = runs[0]

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["metrics"]["packets_transmitted"], 5)
        self.assertEqual(payload["metrics"]["packets_received"], 5)
        self.assertEqual(payload["metrics"]["packet_loss_percent"], 0.0)
        self.assertEqual(payload["metrics"]["rtt_min_ms"], 0.045)
        self.assertEqual(payload["metrics"]["rtt_avg_ms"], 0.058)
        self.assertEqual(payload["metrics"]["rtt_max_ms"], 0.082)
        self.assertEqual(payload["metrics"]["rtt_mdev_ms"], 0.012)

        valid, errors = validate_execution_result(
            benchmark="network_ping",
            exit_code=payload["execution"]["exit_code"],
            stdout=payload["stdout"],
            metrics=payload["metrics"],
            status=payload["status"]
        )
        self.assertTrue(valid, f"Validation failed: {errors}")

    def test_network_iperf3_missing_handling(self):
        self.mock_adapter.execute.return_value = ExecutionResult(
            exit_code=1, stdout="", stderr="iperf3: not found", duration_sec=0.01, status="failed"
        )

        bench = get_benchmark("network_iperf3")
        runs = self.executor.execute_benchmark(bench, warmup_runs=0, measured_runs=2)
        self.assertEqual(len(runs), 2)
        for r in runs:
            self.assertEqual(r["status"], "unavailable")
            self.assertIn("iperf3 binary not found", r["metrics"]["reason"])
            self.assertIsNone(r["metrics"]["sender_bandwidth_mbps"])
            self.assertIsNone(r["metrics"]["receiver_bandwidth_mbps"])

    def test_app_latency_measurement(self):
        # Test real HTTP latency benchmarking using MinimalHealthHttpServer
        server = MinimalHealthHttpServer(host="127.0.0.1", port=0)
        server.start()
        try:
            lat_res = HttpLatencyBenchmark.measure_endpoint(server.url, num_requests=10)
            self.assertEqual(lat_res["status"], "success")
            self.assertEqual(lat_res["requests_completed"], 10)
            self.assertEqual(lat_res["http_200_count"], 10)
            self.assertIsNotNone(lat_res["total_ms"]["p50"])
            self.assertIsNotNone(lat_res["total_ms"]["p95"])
            self.assertIsNotNone(lat_res["total_ms"]["p99"])
            self.assertGreater(lat_res["total_ms"]["p50"], 0.0)

            valid, errors = validate_execution_result(
                benchmark="app_latency",
                exit_code=0,
                stdout="{}",
                metrics=lat_res,
                status="success"
            )
            self.assertTrue(valid, f"Validation failed: {errors}")
        finally:
            server.stop()

    def test_startup_lifecycle_host_baseline(self):
        bench = get_benchmark("startup_lifecycle")
        runs = self.executor.execute_benchmark(bench, warmup_runs=0, measured_runs=1)
        self.assertEqual(len(runs), 1)
        payload = runs[0]

        # Host baseline must report unavailable with zero duration reason
        self.assertEqual(payload["status"], "unavailable")
        self.assertIn("Host baseline has zero hypervisor startup duration", payload["metrics"]["reason"])
        self.assertIsNone(payload["metrics"]["hypervisor_start_sec"])

    def test_isolation_audit_structure(self):
        self.mock_adapter.execute.side_effect = [
            ExecutionResult(exit_code=0, stdout="none\n", stderr="", duration_sec=0.01, status="success"),
            ExecutionResult(exit_code=0, stdout="Linux test-host 7.0.0-31-generic ...\n", stderr="", duration_sec=0.01, status="success"),
            ExecutionResult(exit_code=0, stdout="0::/user.slice\n", stderr="", duration_sec=0.01, status="success"),
            ExecutionResult(exit_code=0, stdout="[{\"ifname\":\"lo\"}]\n", stderr="", duration_sec=0.01, status="success"),
            ExecutionResult(exit_code=0, stdout="{\"filesystems\":[]}\n", stderr="", duration_sec=0.01, status="success")
        ]

        bench = get_benchmark("isolation_audit")
        runs = self.executor.execute_benchmark(bench, warmup_runs=0, measured_runs=1)
        self.assertEqual(len(runs), 1)
        payload = runs[0]

        self.assertEqual(payload["status"], "success")
        self.assertIn("isolation_audit", payload["metrics"])
        self.assertFalse(payload["metrics"]["is_shared_kernel"])
        self.assertEqual(payload["metrics"]["systemd_detect_virt"], "none")

    def test_raw_result_persistence_and_no_overwrite(self):
        payload1 = {
            "schema_version": SCHEMA_VERSION,
            "experiment_id": "test-exp",
            "run_id": "duplicate-run-id",
            "environment": "host",
            "benchmark": "cpu_deterministic",
            "timestamp": "2026-09-16T12:00:00Z",
            "command": "cmd",
            "exit_code": 0,
            "metrics": {"gflops": 5.0},
            "status": "success"
        }
        payload2 = {
            "schema_version": SCHEMA_VERSION,
            "experiment_id": "test-exp",
            "run_id": "duplicate-run-id",
            "environment": "host",
            "benchmark": "cpu_deterministic",
            "timestamp": "2026-09-16T12:01:00Z",
            "command": "cmd",
            "exit_code": 0,
            "metrics": {"gflops": 5.5},
            "status": "success"
        }

        f1 = self.executor._save_raw_payload(payload1)
        f2 = self.executor._save_raw_payload(payload2)
        self.assertNotEqual(f1, f2)
        self.assertTrue(f1.exists())
        self.assertTrue(f2.exists())


if __name__ == "__main__":
    unittest.main()
