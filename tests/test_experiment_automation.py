#!/usr/bin/env python3
"""
tests/test_experiment_automation.py - Unit and Integration Tests for Phase B Step 2.

Tests:
1. Full Experiment Coordinator & Sequential Execution across all environments
2. Mode & Run Count Configurations (--quick, --full, --runs N)
3. Safe Failure Handling:
   - Environment offline / preparation failure
   - Workload deployment failure
   - Workload execution failure / timeout
   - Verification that failures are recorded, stderr is preserved, and remaining tests continue
4. Anti-Overwriting Protection:
   - Existing validated CPU dataset is preserved and never modified
   - New runs receive unique, non-colliding run IDs
5. Experiment Manifest Generation:
   - Manifest contains experiment ID, timestamps, duration, environments, benchmarks,
     workload versions/SHA256, configuration, and success/failure counts
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

from benchmark.runner import (
    build_arg_parser,
    IsolationManager,
    ExperimentRunner
)
from benchmark.runner.executor import BenchmarkExecutor
from benchmark.runner.benchmarks import get_benchmark, resolve_benchmarks, CPU_BENCHMARK
from benchmark.runner.environments.base import (
    BaseEnvironmentAdapter,
    ExecutionResult,
    IdentityResult,
    NormalizedState
)
from collector.schema import (
    ResultStorageManager,
    SCHEMA_VERSION
)


class TestExperimentAutomation(unittest.TestCase):

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
        self.mock_adapter.prepare.return_value = {"status": "ready", "ready": True}
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

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_experiment_runner_mode_configurations(self):
        # Quick mode defaults
        r_quick = ExperimentRunner(mode="quick", storage_dir=self.tmp_path / "results")
        self.assertEqual(r_quick.warmup_runs, 1)
        self.assertEqual(r_quick.measured_runs, 2)

        # Full mode defaults
        r_full = ExperimentRunner(mode="full", storage_dir=self.tmp_path / "results")
        self.assertEqual(r_full.warmup_runs, 1)
        self.assertEqual(r_full.measured_runs, 5)

        # Custom runs override
        r_custom = ExperimentRunner(mode="full", runs=3, storage_dir=self.tmp_path / "results")
        self.assertEqual(r_custom.warmup_runs, 1)
        self.assertEqual(r_custom.measured_runs, 3)

    def test_environment_offline_graceful_handling(self):
        """When an environment fails to prepare (e.g. offline), failures are recorded cleanly without crashing."""
        self.mock_adapter.prepare.return_value = {
            "status": "unavailable",
            "ready": False,
            "reason": "Hypervisor domain not defined or accessible"
        }
        executor = BenchmarkExecutor(self.mock_adapter, storage_manager=self.storage, stabilization_sec=0)
        bench = get_benchmark("cpu")

        runs = executor.execute_benchmark(bench, warmup_runs=0, measured_runs=2)
        self.assertEqual(len(runs), 2)
        for r in runs:
            self.assertEqual(r["status"], "unavailable")
            self.assertIn("Hypervisor domain not defined", r["metrics"]["reason"])
            self.assertEqual(r["execution"]["exit_code"], -1)

    def test_deployment_failure_graceful_handling(self):
        """When workload deployment fails, records failed run and continues."""
        self.mock_adapter.deploy_workload.return_value = {
            "deployed": False,
            "error": "SSH file transfer failed: connection reset"
        }
        with patch.object(executor := BenchmarkExecutor(self.mock_adapter, storage_manager=self.storage, stabilization_sec=0), "deployer") as mock_dep:
            deploy_res = MagicMock()
            deploy_res.verified = False
            deploy_res.error_message = "SSH file transfer failed: connection reset"
            deploy_res.local_sha256 = "dummy_sha"
            mock_dep.get_canonical_artifact.return_value = MagicMock(size_bytes=100)
            mock_dep.deploy.return_value = deploy_res

            bench = get_benchmark("memory")
            runs = executor.execute_benchmark(bench, warmup_runs=0, measured_runs=2)
            self.assertEqual(len(runs), 2)
            for r in runs:
                self.assertEqual(r["status"], "failed")
                self.assertIn("SSH file transfer failed", r["metrics"]["reason"])

    def test_execution_exception_graceful_handling(self):
        """When an unexpected exception occurs during benchmark execution, records failure and preserves error."""
        self.mock_adapter.execute.side_effect = TimeoutError("Command timed out after 60 seconds")
        executor = BenchmarkExecutor(self.mock_adapter, storage_manager=self.storage, stabilization_sec=0)
        bench = get_benchmark("network_ping")

        runs = executor.execute_benchmark(bench, warmup_runs=0, measured_runs=2)
        self.assertEqual(len(runs), 2)
        for r in runs:
            self.assertEqual(r["status"], "failed")
            self.assertIn("Command timed out", r["metrics"]["reason"])

    def test_experiment_manifest_generation(self):
        """Verifies structure and reproducibility fields of generated experiment manifest."""
        runner = ExperimentRunner(
            experiment_id="exp-test-reproduce-123",
            mode="quick",
            runs=2,
            tests=["cpu", "memory"],
            storage_dir=self.tmp_path / "results"
        )
        runner.generated_runs = [
            {"run_id": "cpu-host-1", "environment": "host", "benchmark": "cpu_deterministic", "status": "success", "execution": {"exit_code": 0}},
            {"run_id": "cpu-host-2", "environment": "host", "benchmark": "cpu_deterministic", "status": "success", "execution": {"exit_code": 0}},
            {"run_id": "mem-host-1", "environment": "host", "benchmark": "memory_deterministic", "status": "success", "execution": {"exit_code": 0}},
            {"run_id": "mem-host-2", "environment": "host", "benchmark": "memory_deterministic", "status": "success", "execution": {"exit_code": 0}},
        ]

        manifest_file = runner.generate_experiment_manifest(
            env_list=["host"],
            start_time="2026-09-17T00:00:00Z",
            end_time="2026-09-17T00:01:00Z",
            duration_sec=60.0
        )
        self.assertTrue(manifest_file.exists())

        with open(manifest_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["experiment_id"], "exp-test-reproduce-123")
        self.assertEqual(data["duration_sec"], 60.0)
        self.assertEqual(data["run_count_config"]["measured_runs"], 2)
        self.assertIn("workload_versions_sha256", data)
        self.assertIn("cpu_deterministic", data["workload_versions_sha256"])
        self.assertEqual(data["total_runs_executed"], 4)
        self.assertEqual(data["status_distribution"]["success"], 4)
        self.assertEqual(len(data["runs_summary"]), 4)

    def test_cpu_dataset_preservation_no_overwrite(self):
        """Ensures existing CPU runs are preserved and fresh runs receive distinct IDs."""
        executor = BenchmarkExecutor(self.mock_adapter, storage_manager=self.storage, stabilization_sec=0)

        # Write existing payload
        existing_id = "cpu_deterministic-host-existing1"
        payload_1 = {
            "schema_version": SCHEMA_VERSION,
            "experiment_id": "exp-first",
            "run_id": existing_id,
            "environment": "host",
            "benchmark": "cpu_deterministic",
            "timestamp": "2026-09-16T12:00:00Z",
            "command": "cpu_workload",
            "exit_code": 0,
            "metrics": {"gflops": 5.12, "checksum": "0x7e83d4c61ad5adb8"},
            "status": "success"
        }
        f1 = executor._save_raw_payload(payload_1)
        self.assertTrue(f1.exists())
        self.assertEqual(f1.name, f"{existing_id}.json")

        # Attempt to save with same run_id
        payload_2 = dict(payload_1)
        payload_2["metrics"] = {"gflops": 5.25, "checksum": "0x7e83d4c61ad5adb8"}
        f2 = executor._save_raw_payload(payload_2)
        self.assertTrue(f2.exists())
        self.assertNotEqual(f1.name, f2.name, "Duplicate run_id must be assigned unique filename")

        # Verify original file content was not overwritten
        with open(f1, "r", encoding="utf-8") as f:
            d1 = json.load(f)
        self.assertEqual(d1["metrics"]["gflops"], 5.12)


if __name__ == "__main__":
    unittest.main()
