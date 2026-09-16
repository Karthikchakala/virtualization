#!/usr/bin/env python3
"""
stats.py - Statistical analysis and aggregation module for CC2 benchmark results.
Computes real summary statistics (mean, median, stdev, min, max) strictly from verified runs.
Never converts missing data to zero. Handles unavailable / failed runs gracefully.
"""

import sys
import json
import math
from pathlib import Path
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collector.common import STATUS_SUCCESS, STATUS_FAILED, STATUS_UNAVAILABLE

def compute_metric_stats(values: List[float]) -> Dict[str, Optional[float]]:
    """Calculates summary statistics for a list of numeric values."""
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "stdev": None,
            "min": None,
            "max": None
        }

    n = len(values)
    mean_val = sum(values) / n
    sorted_vals = sorted(values)
    
    # Median
    if n % 2 == 1:
        median_val = sorted_vals[n // 2]
    else:
        median_val = (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0

    # Sample Standard Deviation
    if n > 1:
        variance = sum((x - mean_val) ** 2 for x in values) / (n - 1)
        stdev_val = math.sqrt(variance)
    else:
        stdev_val = 0.0

    return {
        "count": n,
        "mean": round(mean_val, 4),
        "median": round(median_val, 4),
        "stdev": round(stdev_val, 4),
        "min": round(sorted_vals[0], 4),
        "max": round(sorted_vals[-1], 4)
    }

def analyze_runs(jsonl_path: Path) -> Dict[str, Any]:
    """
    Parses benchmark_runs.jsonl and generates structured summary analysis.
    Only successful runs are included in numerical metric calculations.
    """
    if not jsonl_path.exists():
        return {"error": f"File not found: {jsonl_path}", "summaries": {}}

    runs_by_env_bench = {}
    statuses_count = {STATUS_SUCCESS: 0, STATUS_FAILED: 0, STATUS_UNAVAILABLE: 0}

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line_s = line.strip()
            if not line_s:
                continue
            try:
                run = json.loads(line_s)
            except json.JSONDecodeError:
                continue

            status = run.get("status", STATUS_FAILED)
            statuses_count[status] = statuses_count.get(status, 0) + 1

            env = run.get("environment", "unknown")
            bench = run.get("benchmark", "unknown")
            key = f"{env}::{bench}"

            if key not in runs_by_env_bench:
                runs_by_env_bench[key] = {
                    "environment": env,
                    "benchmark": bench,
                    "successful_runs": [],
                    "failed_runs": [],
                    "unavailable_runs": []
                }

            if status == STATUS_SUCCESS:
                runs_by_env_bench[key]["successful_runs"].append(run)
            elif status == STATUS_UNAVAILABLE:
                runs_by_env_bench[key]["unavailable_runs"].append(run)
            else:
                runs_by_env_bench[key]["failed_runs"].append(run)

    # Compute metric distributions
    summaries = {}
    for key, group in runs_by_env_bench.items():
        succ = group["successful_runs"]
        summary = {
            "environment": group["environment"],
            "benchmark": group["benchmark"],
            "total_attempts": len(succ) + len(group["failed_runs"]) + len(group["unavailable_runs"]),
            "success_count": len(succ),
            "failed_count": len(group["failed_runs"]),
            "unavailable_count": len(group["unavailable_runs"]),
            "metrics": {}
        }

        if succ:
            # Extract common metrics dynamically
            first_metrics = succ[0].get("parsed_metrics", {})
            for mkey, val in first_metrics.items():
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    vals = [r["parsed_metrics"][mkey] for r in succ if mkey in r.get("parsed_metrics", {}) and isinstance(r["parsed_metrics"][mkey], (int, float))]
                    summary["metrics"][mkey] = compute_metric_stats(vals)
                elif mkey == "checksum":
                    # Verify deterministic checksum consistency
                    checksums = set(r["parsed_metrics"].get("checksum") for r in succ if "checksum" in r.get("parsed_metrics", {}))
                    summary["checksum_consistency"] = {
                        "is_deterministic": len(checksums) == 1,
                        "unique_checksums": list(checksums)
                    }

        summaries[key] = summary

    return {
        "status_distribution": statuses_count,
        "summaries": summaries
    }

if __name__ == "__main__":
    runs_file = PROJECT_ROOT / "results" / "benchmark_runs.jsonl"
    report = analyze_runs(runs_file)
    print(json.dumps(report, indent=2))
