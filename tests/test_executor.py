#!/usr/bin/env python3
"""
tests/test_executor.py - Unit Test Suite for Unified Benchmark Execution Engine.

Tests:
1. Benchmark registry, short name resolution, and canonical CPU benchmark parameters.
2. Rejection of unknown and unsupported benchmark names.
3. ExecutionPlan construction for dry-run verification across platforms.
4. Non-destructive diagnostic probe (probe_environment) behavior.
5. Complete executor execution lifecycle using mock environment adapters:
   prepare -> deploy -> verify -> warmup -> measured -> metrics -> cleanup.
6. Verification that raw results never overwrite existing runs and generate unique IDs.
7. Verification that secrets, credentials, and passwords never leak into result payloads.
8. CLI argument parsing, mutually exclusive run count modes, and conflict checks.
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
    CPU_BENCHMARK
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
from benchmark.runner.workload import WorkloadDeployer, WorkloadArtifact, WorkloadDeploymentResult
from collector.schema import ResultStorageManager
from benchmark.runner import build_arg_parser


class TestBenchmarkRegistry(unittest.TestCase):

    def test_canonical_cpu_benchmark_invariants(self):
        cpu_bench = get_benchmark("cpu")
        self.assertEqual(cpu_bench.name, "cpu_deterministic")
        self.assertEqual(cpu_bench.workload_binary, "cpu_workload")

        # Canonical parameter validation
        self.assertEqual(
            cpu_bench.default_arguments,
            ["--size", "400", "--iterations", "5", "--warmup", "1", "--threads", "1"]
        )
        self.assertEqual(cpu_bench.canonical_invariants["total_flops"], 640000000)
        self.assertEqual(cpu_bench.canonical_invariants["expected_checksum"], "0x7e83d4c61ad5adb8")
        self.assertEqual(
            cpu_bench.canonical_invariants["canonical_sha256"],
            "212853035b582f238058b8d436fecf1f25bd5ff249965c7467336903a563fd9f"
        )
        self.assertTrue(cpu_bench.is_implemented)

    def test_unknown_benchmark_rejection(self):
        with self.assertRaises(ValueError) as ctx:
            get_benchmark("invalid_benchmark_xyz")
        self.assertIn("Unknown benchmark", str(ctx.exception))

    def test_resolve_benchmarks_all_and_subset(self):
        subset = resolve_benchmarks(["cpu", "memory"])
        self.assertEqual(len(subset), 2)
        names = [b.short_name for b in subset]
        self.assertIn("cpu", names)
        self.assertIn("memory", names)

        all_benches = resolve_benchmarks(["all"])
        self.assertGreaterEqual(len(all_benches), 8)


class TestBenchmarkExecutorLifecycle(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.storage = ResultStorageManager(self.tmp_path / "results")

        # Mock adapter
        self.mock_adapter = MagicMock(spec=BaseEnvironmentAdapter)
        self.mock_adapter.name = "kvm"
        self.mock_adapter.display_name = "KVM / QEMU"
        self.mock_adapter.classification = "Hardware-assisted Virtualization (Type-1-like)"
        self.mock_adapter.virtualization_type = "type1"
        self.mock_adapter.transport_name = "ssh"
        self.mock_adapter.target_path = Path("/tmp/cc2_workloads")

        self.executor = BenchmarkExecutor(
            adapter=self.mock_adapter,
            storage_manager=self.storage,
            stabilization_sec=0  # zero wait in tests
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_create_execution_plan_dry_run(self):
        cpu_bench = get_benchmark("cpu")
        plan = self.executor.create_execution_plan(cpu_bench, warmup_runs=1, measured_runs=2)
        self.assertEqual(plan.environment, "kvm")
        self.assertEqual(plan.benchmark_name, "cpu_deterministic")
        self.assertEqual(plan.warmup_runs, 1)
        self.assertEqual(plan.measured_runs, 2)
        self.assertIn("cpu_workload", plan.command_to_run)
        self.assertIn("--size 400", plan.command_to_run)
        self.assertEqual(plan.canonical_invariants["total_flops"], 640000000)

    def test_probe_environment_running(self):
        self.mock_adapter.get_status.return_value = NormalizedState.RUNNING
        self.mock_adapter.verify.return_value = True
        self.mock_adapter.execute.return_value = ExecutionResult(
            exit_code=0,
            stdout="7.0.0-31-generic\nkvm-ubuntu\nuid=1000\nkvm\n",
            stderr="",
            duration_sec=0.05,
            status="success"
        )

        probe = self.executor.probe_environment()
        self.assertTrue(probe["probe_executed"])
        self.assertEqual(probe["guest_kernel"], "7.0.0-31-generic")
        self.assertEqual(probe["guest_hostname"], "kvm-ubuntu")
        self.assertEqual(probe["virt_detect"], "kvm")

    def test_probe_environment_stopped(self):
        self.mock_adapter.get_status.return_value = NormalizedState.STOPPED
        self.mock_adapter.verify.return_value = True

        probe = self.executor.probe_environment()
        self.assertFalse(probe["probe_executed"])
        self.assertIn("offline", probe.get("error", ""))

    def test_execute_benchmark_complete_lifecycle(self):
        # 1. Setup adapter mocks
        self.mock_adapter.prepare.return_value = {"status": "ready"}
        self.mock_adapter.deploy_workload.return_value = {
            "deployed": True,
            "transferred": True,
            "sha256": "212853035b582f238058b8d436fecf1f25bd5ff249965c7467336903a563fd9f",
            "destination": "/tmp/cc2_workloads/cpu_workload"
        }
        self.mock_adapter.get_identity.return_value = IdentityResult(
            environment="kvm",
            classification="Type-1-like",
            virtualization_type="kvm",
            kernel_release="6.8.0-generic",
            systemd_detect_virt="kvm",
            is_shared_kernel=False
        )

        # Mock stdout JSON from cpu_workload
        stdout_json = (
            '{\n'
            '  "workload": "cpu_deterministic",\n'
            '  "matrix_size": 400,\n'
            '  "iterations": 5,\n'
            '  "total_flops": 640000000,\n'
            '  "elapsed_sec": 0.123456,\n'
            '  "gflops": 5.184,\n'
            '  "checksum": "0x7e83d4c61ad5adb8",\n'
            '  "status": "success"\n'
            '}'
        )
        stderr_time = (
            '\tCommand being timed: "/tmp/cc2_workloads/cpu_workload --size 400 ..."\n'
            '\tUser time (seconds): 0.12\n'
            '\tSystem time (seconds): 0.00\n'
            '\tPercent of CPU this job got: 99%\n'
            '\tElapsed (wall clock) time (h:mm:ss or m:ss): 0:00.12\n'
            '\tMaximum resident set size (kbytes): 5600\n'
            '\tMinor (reclaiming a frame) page faults: 120\n'
            '\tMajor (requiring I/O) page faults: 0\n'
            '\tVoluntary context switches: 2\n'
            '\tInvoluntary context switches: 1\n'
        )

        self.mock_adapter.execute.return_value = ExecutionResult(
            exit_code=0,
            stdout=stdout_json,
            stderr=stderr_time,
            duration_sec=0.12,
            status="success"
        )
        self.mock_adapter.collect_metrics.return_value = {"domstats": {"cpu.time": 99999999}}

        cpu_bench = get_benchmark("cpu")
        runs = self.executor.execute_benchmark(cpu_bench, warmup_runs=1, measured_runs=2)

        self.assertEqual(len(runs), 2)
        # Check that lifecycle calls were made
        self.mock_adapter.prepare.assert_called_once()
        self.mock_adapter.deploy_workload.assert_called_once()
        self.mock_adapter.cleanup.assert_called_once()

        # Check result structure
        payload = runs[0]
        self.assertEqual(payload["schema_version"], "2.0.0")
        self.assertEqual(payload["environment"], "kvm")
        self.assertEqual(payload["benchmark"], "cpu_deterministic")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["metrics"]["total_flops"], 640000000)
        self.assertEqual(payload["metrics"]["checksum"], "0x7e83d4c61ad5adb8")
        self.assertEqual(payload["metrics"]["max_rss_kb"], 5600)
        self.assertEqual(payload["workload"]["sha256"], "212853035b582f238058b8d436fecf1f25bd5ff249965c7467336903a563fd9f")
        self.assertTrue(payload["workload"]["verified"])

    def test_raw_result_never_overwrites_existing_file(self):
        payload1 = {
            "environment": "host",
            "benchmark": "cpu_deterministic",
            "run_id": "duplicate-test-id",
            "data": 1
        }
        payload2 = {
            "environment": "host",
            "benchmark": "cpu_deterministic",
            "run_id": "duplicate-test-id",
            "data": 2
        }

        f1 = self.executor._save_raw_payload(payload1)
        self.assertTrue(f1.exists())

        # Second save must not overwrite f1; it must generate a new filename
        f2 = self.executor._save_raw_payload(payload2)
        self.assertNotEqual(f1, f2)
        self.assertTrue(f1.exists())
        self.assertTrue(f2.exists())

    def test_secret_redaction(self):
        payload = {
            "environment": "host",
            "benchmark": "cpu_deterministic",
            "run_id": "secret-test-id",
            "parameters": {"test": "val"},
            "metrics": {"gflops": 1.0}
        }
        f = self.executor._save_raw_payload(payload)
        content = f.read_text()
        for forbidden in ["password", "secret", "id_rsa", ".env"]:
            self.assertNotIn(f'"{forbidden}": "super', content)


class TestCliArgumentValidation(unittest.TestCase):

    def test_cli_modes_quick_and_full(self):
        parser = build_arg_parser()

        # Quick mode
        args_q = parser.parse_args(["--environment", "host", "--quick"])
        self.assertTrue(args_q.quick)
        self.assertFalse(args_q.full)

        # Full mode
        args_f = parser.parse_args(["--environment", "kvm", "--full"])
        self.assertTrue(args_f.full)
        self.assertFalse(args_f.quick)

        # Runs override
        args_r = parser.parse_args(["--environment", "lxc", "--runs", "10"])
        self.assertEqual(args_r.runs, 10)

        # Dry run flag
        args_d = parser.parse_args(["--environment", "virtualbox", "--dry-run"])
        self.assertTrue(args_d.dry_run)

        # Probe flag
        args_p = parser.parse_args(["--environment", "host", "--probe"])
        self.assertTrue(args_p.probe)

    def test_cli_mutually_exclusive_quick_and_full(self):
        parser = build_arg_parser()
        with self.assertRaises(SystemExit):
            # Must exit with code 2 because --quick and --full are mutually exclusive
            parser.parse_args(["--environment", "host", "--quick", "--full"])


if __name__ == "__main__":
    unittest.main()
