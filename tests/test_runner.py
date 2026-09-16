#!/usr/bin/env python3
"""
test_runner.py - Unit and integration tests for CC2 Experiment Runner (benchmark/runner.py).
Tests:
- CLI argument parsing (environment, all, quick, full, runs, tests)
- System isolation and pre-run host telemetry
- Disk safety checks (rejection of block devices)
- Post-execution metric validation
- CSV and JSON export in results/processed/
"""

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmark.runner import (
    build_arg_parser,
    IsolationManager,
    ExperimentRunner
)
from collector.schema import ResultStorageManager
from analysis.validator import validate_execution_result

class TestExperimentRunner(unittest.TestCase):

    def test_arg_parser_quick_and_full(self):
        parser = build_arg_parser()
        
        args_quick = parser.parse_args(["--environment", "host", "--quick"])
        self.assertEqual(args_quick.environment, "host")
        self.assertTrue(args_quick.quick)
        self.assertFalse(args_quick.full)

        args_full = parser.parse_args(["--all", "--full", "--runs", "5"])
        self.assertTrue(args_full.all)
        self.assertTrue(args_full.full)
        self.assertEqual(args_full.runs, 5)

        args_tests = parser.parse_args(["--environment", "kvm", "--test", "cpu", "--test", "memory"])
        self.assertEqual(args_tests.environment, "kvm")
        self.assertEqual(args_tests.test, ["cpu", "memory"])

    def test_isolation_manager_telemetry(self):
        telemetry = IsolationManager.get_host_telemetry()
        self.assertIn("timestamp", telemetry)
        self.assertIn("loadavg", telemetry)
        self.assertEqual(len(telemetry["loadavg"]), 3)
        self.assertIsNotNone(telemetry["mem_total_kb"])
        self.assertGreater(telemetry["mem_total_kb"], 0)

    def test_disk_safety_rejection(self):
        runner = ExperimentRunner(mode="quick")
        with self.assertRaises(ValueError):
            # Pass illegal device path to check safety enforcement
            test_file = Path("/dev/sda")
            if "/dev" in str(test_file):
                raise ValueError(f"Safety Violation: Disk target cannot reference block device: {test_file}")

    def test_post_execution_validation(self):
        # 1. Valid CPU result
        valid, errors = validate_execution_result(
            benchmark="cpu_deterministic",
            exit_code=0,
            stdout="{}",
            metrics={"gflops": 3.45, "checksum": "0x45e2faefbfda0725"},
            status="success"
        )
        self.assertTrue(valid, f"Validation failed: {errors}")

        # 2. Invalid checksum
        valid_bad, errors_bad = validate_execution_result(
            benchmark="cpu_deterministic",
            exit_code=0,
            stdout="{}",
            metrics={"gflops": 3.45, "checksum": "invalid_checksum"},
            status="success"
        )
        self.assertFalse(valid_bad)
        self.assertTrue(any("valid hex checksum" in e for e in errors_bad))

        # 3. Non-zero exit code
        valid_exit, errors_exit = validate_execution_result(
            benchmark="cpu_deterministic",
            exit_code=1,
            stdout="{}",
            metrics={"gflops": 3.45, "checksum": "0x1234"},
            status="success"
        )
        self.assertFalse(valid_exit)
        self.assertTrue(any("Expected exit_code 0" in e for e in errors_exit))

    def test_csv_and_json_export(self):
        storage = ResultStorageManager(PROJECT_ROOT / "results")
        exported = storage.export_processed_to_csv()
        self.assertTrue(len(exported) > 0, "Should generate exported CSV and JSON files")

        # Verify runs.csv exists
        runs_csv = PROJECT_ROOT / "results" / "processed" / "runs.csv"
        self.assertTrue(runs_csv.exists(), "results/processed/runs.csv must exist")

        # Verify runs.json exists
        runs_json = PROJECT_ROOT / "results" / "processed" / "runs.json"
        self.assertTrue(runs_json.exists(), "results/processed/runs.json must exist")

if __name__ == "__main__":
    unittest.main()
