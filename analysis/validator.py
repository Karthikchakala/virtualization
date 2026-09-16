#!/usr/bin/env python3
"""
validator.py - Benchmark data validation and anti-fabrication engine for CC2.
Ensures:
1. Every reported metric strictly originates from raw command output.
2. No fabricated or mocked numbers are passed as real.
3. Missing data is never coerced to zero.
4. Schema invariants are enforced across all benchmark results.
"""

import sys
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collector.common import VALID_STATUSES, VALID_ENVIRONMENTS

class ResultValidationError(Exception):
    """Raised when benchmark result fails provenance or schema checks."""
    pass

def validate_single_result(record: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validates a single benchmark result dictionary.
    Returns (is_valid, list_of_errors).
    """
    errors = []

    # 1. Required fields
    required_keys = [
        "environment", "benchmark", "run_id", "timestamp",
        "command", "exit_code", "stdout", "stderr", "parsed_metrics", "status"
    ]
    for key in required_keys:
        if key not in record:
            errors.append(f"Missing required field: '{key}'")

    if errors:
        return False, errors

    # 2. Schema value checks
    if record["status"] not in VALID_STATUSES:
        errors.append(f"Invalid status '{record['status']}'. Must be in {VALID_STATUSES}")

    if record["environment"] not in VALID_ENVIRONMENTS:
        errors.append(f"Invalid environment '{record['environment']}'. Must be in {VALID_ENVIRONMENTS}")

    # 3. Traceability check
    stdout = record.get("stdout", "")
    metrics = record.get("parsed_metrics", {})

    if record["status"] == "success":
        if not stdout:
            errors.append("Successful run must have non-empty raw stdout.")
        if record["exit_code"] != 0:
            errors.append(f"Successful run cannot have non-zero exit_code ({record['exit_code']}).")

        # Verify parsed metrics originate in stdout
        for mkey, mval in metrics.items():
            if isinstance(mval, (int, float, str)):
                # Convert to string and search in stdout
                str_val = str(mval)
                # For floats, also check short prefix in case of formatting differences
                if isinstance(mval, float):
                    prefix = f"{mval:.2f}"
                    if prefix not in stdout and str_val not in stdout:
                        errors.append(f"Metric '{mkey}': value '{mval}' not traceable to raw stdout.")
                else:
                    if str_val not in stdout:
                        errors.append(f"Metric '{mkey}': value '{mval}' not traceable to raw stdout.")

    elif record["status"] == "unavailable":
        # Unavailable runs must NOT have fabricated numeric metrics
        for mkey, mval in metrics.items():
            if mval == 0 or mval == 0.0:
                errors.append(f"Unavailable run illegally coerced '{mkey}' to zero! Missing data must NOT be zero.")

    return len(errors) == 0, errors

def validate_results_file(jsonl_path: Path) -> Dict[str, Any]:
    """Validates an entire jsonl results file."""
    if not jsonl_path.exists():
        return {"valid": False, "error": f"File does not exist: {jsonl_path}"}

    total_records = 0
    passed_records = 0
    failures = []

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line_s = line.strip()
            if not line_s:
                continue
            total_records += 1
            try:
                rec = json.loads(line_s)
                valid, errors = validate_single_result(rec)
                if valid:
                    passed_records += 1
                else:
                    failures.append({"line": idx, "run_id": rec.get("run_id"), "errors": errors})
            except json.JSONDecodeError as e:
                failures.append({"line": idx, "errors": [f"Malformed JSON: {e}"]})

    return {
        "valid": len(failures) == 0,
        "total_records": total_records,
        "passed_records": passed_records,
        "failed_records": len(failures),
        "failures": failures
    }

def validate_execution_result(
    benchmark: str,
    exit_code: int,
    stdout: str,
    metrics: Dict[str, Any],
    status: str
) -> Tuple[bool, List[str]]:
    """
    Validates benchmark execution after completion:
    - exit_code == 0 for success
    - required metrics present for specific benchmark
    - units are valid positive numbers
    - checksum format is valid (0x...)
    """
    errors = []
    if status == "success":
        if exit_code != 0:
            errors.append(f"Expected exit_code 0 for successful run, got {exit_code}")
        
        # Benchmark-specific metric assertions
        if benchmark == "cpu_deterministic":
            if "gflops" not in metrics or metrics["gflops"] is None or metrics["gflops"] <= 0:
                errors.append(f"cpu_deterministic missing positive 'gflops': {metrics.get('gflops')}")
            if "checksum" not in metrics or not str(metrics["checksum"]).startswith("0x"):
                errors.append(f"cpu_deterministic missing valid hex checksum: {metrics.get('checksum')}")
        elif benchmark == "memory_deterministic":
            if "throughput_mb_s" not in metrics or metrics["throughput_mb_s"] is None or metrics["throughput_mb_s"] <= 0:
                errors.append(f"memory_deterministic missing positive 'throughput_mb_s': {metrics.get('throughput_mb_s')}")
            if "checksum" not in metrics or not str(metrics["checksum"]).startswith("0x"):
                errors.append(f"memory_deterministic missing valid hex checksum: {metrics.get('checksum')}")
        elif benchmark == "syscall_deterministic":
            if "ops_per_sec" not in metrics or metrics["ops_per_sec"] is None or metrics["ops_per_sec"] <= 0:
                errors.append(f"syscall_deterministic missing positive 'ops_per_sec': {metrics.get('ops_per_sec')}")
            if "checksum" not in metrics or not str(metrics["checksum"]).startswith("0x"):
                errors.append(f"syscall_deterministic missing valid hex checksum: {metrics.get('checksum')}")
        elif benchmark == "scheduling_deterministic":
            if "switches_per_sec" not in metrics or metrics["switches_per_sec"] is None or metrics["switches_per_sec"] <= 0:
                errors.append(f"scheduling_deterministic missing positive 'switches_per_sec': {metrics.get('switches_per_sec')}")
            if "checksum" not in metrics or not str(metrics["checksum"]).startswith("0x"):
                errors.append(f"scheduling_deterministic missing valid hex checksum: {metrics.get('checksum')}")
        elif benchmark == "network_ping":
            if "packet_loss_percent" not in metrics or metrics["packet_loss_percent"] is None:
                errors.append("network_ping missing 'packet_loss_percent'")
            if "rtt_avg_ms" not in metrics or metrics["rtt_avg_ms"] is None:
                errors.append("network_ping missing 'rtt_avg_ms'")
        elif benchmark == "app_latency":
            if "requests_completed" not in metrics or metrics["requests_completed"] <= 0:
                errors.append("app_latency missing positive 'requests_completed'")
            if "total_time_ms" not in metrics or not isinstance(metrics["total_time_ms"], dict):
                errors.append("app_latency missing 'total_time_ms' statistics dict")
    
    return len(errors) == 0, errors

if __name__ == "__main__":
    runs_file = PROJECT_ROOT / "results" / "benchmark_runs.jsonl"
    report = validate_results_file(runs_file)
    print(json.dumps(report, indent=2))
