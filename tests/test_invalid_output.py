#!/usr/bin/env python3
"""
test_invalid_output.py - Verifies system behavior on invalid or corrupted output.
Ensures:
- Malformed JSON outputs are detected without crashes
- Provenance checker rejects fabricated or mismatched metrics
- Schema validator enforces field requirements
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collector.schema import (
    VersionedBenchmarkResult,
    create_versioned_result,
    SCHEMA_VERSION
)
from analysis.validator import validate_single_result

class TestInvalidOutputHandling(unittest.TestCase):

    def test_invalid_json_stdout_handled_gracefully(self):
        measured = {
            "command": "bad_command",
            "exit_code": 1,
            "timed_out": False,
            "stdout": "Corrupted garbage output {not_json: ...",
            "stderr": "Error encountered",
            "telemetry": {}
        }
        res = create_versioned_result(
            experiment_id="exp-test",
            environment="host",
            benchmark="cpu_deterministic",
            command="bad_command",
            measured_output=measured,
            workload_parsed_json=None
        )
        self.assertEqual(res.status, "failed")
        self.assertEqual(res.exit_code, 1)

    def test_untraceable_values_rejected_by_validator(self):
        bogus_res = {
            "schema_version": SCHEMA_VERSION,
            "experiment_id": "exp-fake",
            "environment": "host",
            "benchmark": "cpu_deterministic",
            "run_id": "fake-1",
            "timestamp": "2026-09-16T12:00:00Z",
            "command": "cpu_workload",
            "exit_code": 0,
            "stdout": "result: ok",
            "stderr": "",
            "parsed_metrics": {"gflops": 99999.99},  # NOT in stdout
            "status": "success"
        }
        is_valid, errors = validate_single_result(bogus_res)
        self.assertFalse(is_valid)
        self.assertTrue(any("not traceable" in e for e in errors))

    def test_missing_data_not_zero_in_schema(self):
        unavailable_res = {
            "schema_version": SCHEMA_VERSION,
            "experiment_id": "exp-test",
            "environment": "kvm",
            "benchmark": "cpu_deterministic",
            "run_id": "unavail-1",
            "timestamp": "2026-09-16T12:00:00Z",
            "command": "probe",
            "exit_code": -1,
            "stdout": "",
            "stderr": "VM is shut off",
            "parsed_metrics": {"gflops": 0.0},  # Coerced to 0
            "status": "unavailable"
        }
        is_valid, errors = validate_single_result(unavailable_res)
        self.assertFalse(is_valid)
        self.assertTrue(any("Missing data must NOT be zero" in e for e in errors))

if __name__ == "__main__":
    unittest.main()
