#!/usr/bin/env python3
"""
test_result_schema.py - Validates that benchmark results adhere to the rigorous schema:
environment, benchmark, run_id, timestamp, command, exit_code, stdout, stderr,
parsed_metrics, status.
Verifies statuses: success, failed, unavailable.
Verifies missing data is NEVER turned into zero.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collector.common import (
    BenchmarkResult,
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_UNAVAILABLE,
    ENV_HOST,
    ENV_KVM
)
from analysis.validator import validate_single_result

class TestResultSchema(unittest.TestCase):

    def test_valid_successful_result(self):
        res = BenchmarkResult(
            environment=ENV_HOST,
            benchmark="cpu_deterministic",
            run_id="run-1234",
            timestamp="2026-09-16T12:00:00Z",
            command="/path/to/cpu_workload --size 100",
            exit_code=0,
            stdout='{"gflops": 3.14, "status": "success"}',
            stderr="",
            parsed_metrics={"gflops": 3.14, "status": "success"},
            status=STATUS_SUCCESS
        )
        valid, errors = validate_single_result(res.to_dict())
        self.assertTrue(valid, f"Validation failed with errors: {errors}")

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            BenchmarkResult(
                environment=ENV_HOST,
                benchmark="cpu_deterministic",
                run_id="run-1234",
                timestamp="2026-09-16T12:00:00Z",
                command="cmd",
                exit_code=0,
                stdout="out",
                stderr="",
                parsed_metrics={},
                status="pending"  # Invalid status!
            )

    def test_never_turns_missing_data_into_zero(self):
        # A result marked 'unavailable' must NOT report 0.0 for missing performance metrics!
        bad_unavailable_rec = {
            "environment": ENV_KVM,
            "benchmark": "cpu_deterministic",
            "run_id": "run-kvm-123",
            "timestamp": "2026-09-16T12:00:00Z",
            "command": "virsh dominfo",
            "exit_code": -1,
            "stdout": "",
            "stderr": "VM shut off",
            "parsed_metrics": {"gflops": 0.0},  # ILLEGAL: zero coerced
            "status": STATUS_UNAVAILABLE
        }
        valid, errors = validate_single_result(bad_unavailable_rec)
        self.assertFalse(valid)
        self.assertTrue(any("Missing data must NOT be zero" in err for err in errors))

    def test_untraceable_metrics_rejected(self):
        fabricated_rec = {
            "environment": ENV_HOST,
            "benchmark": "cpu_deterministic",
            "run_id": "run-fab-123",
            "timestamp": "2026-09-16T12:00:00Z",
            "command": "/bin/true",
            "exit_code": 0,
            "stdout": "done",
            "stderr": "",
            "parsed_metrics": {"gflops": 999.99},  # FABRICATED: not in stdout!
            "status": STATUS_SUCCESS
        }
        valid, errors = validate_single_result(fabricated_rec)
        self.assertFalse(valid)
        self.assertTrue(any("not traceable to raw stdout" in err for err in errors))

if __name__ == "__main__":
    unittest.main()
