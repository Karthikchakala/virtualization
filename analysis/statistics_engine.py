#!/usr/bin/env python3
"""
statistics_engine.py - Rigorous statistical calculation engine for CC2.
Computes:
- mean, median, min, max
- sample standard deviation
- coefficient of variation (% CV)
- latency / performance percentiles: p50, p95, p99

Strict Invariant: Missing or None values are filtered out.
Never substitutes 0 for missing values.
"""

import math
from typing import List, Dict, Any, Optional, Union

def calculate_percentile(sorted_data: List[float], p: float) -> Optional[float]:
    """
    Calculates the p-th percentile of a sorted list of numbers (0 <= p <= 100)
    using linear interpolation between nearest ranks.
    """
    if not sorted_data:
        return None
    if p < 0.0 or p > 100.0:
        raise ValueError(f"Percentile must be between 0 and 100, got {p}")

    n = len(sorted_data)
    if n == 1:
        return round(float(sorted_data[0]), 6)

    rank = (p / 100.0) * (n - 1)
    low_idx = int(math.floor(rank))
    high_idx = int(math.ceil(rank))
    fraction = rank - low_idx

    if low_idx == high_idx:
        return round(float(sorted_data[low_idx]), 6)

    val = sorted_data[low_idx] + fraction * (sorted_data[high_idx] - sorted_data[low_idx])
    return round(float(val), 6)

def compute_statistics(raw_values: List[Optional[Union[int, float]]]) -> Dict[str, Any]:
    """
    Computes comprehensive statistics over a list of numeric values.
    Filters out None/missing entries cleanly without coercing them to zero.
    """
    total_count = len(raw_values)
    valid_values = [
        float(v) for v in raw_values 
        if v is not None and not (isinstance(v, float) and math.isnan(v))
    ]
    valid_count = len(valid_values)
    missing_count = total_count - valid_count

    if valid_count == 0:
        return {
            "total_count": total_count,
            "valid_count": 0,
            "missing_count": missing_count,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
            "stdev": None,
            "cv_percent": None,
            "p50": None,
            "p95": None,
            "p99": None
        }

    sorted_vals = sorted(valid_values)
    min_val = sorted_vals[0]
    max_val = sorted_vals[-1]

    # Mean
    mean_val = sum(sorted_vals) / valid_count

    # Median (p50)
    median_val = calculate_percentile(sorted_vals, 50.0)

    # Sample standard deviation
    if valid_count > 1:
        variance = sum((x - mean_val) ** 2 for x in sorted_vals) / (valid_count - 1)
        stdev_val = math.sqrt(variance)
    else:
        stdev_val = 0.0

    # Coefficient of variation (% CV = stdev / abs(mean) * 100)
    if mean_val != 0.0 and stdev_val is not None:
        cv_percent = (stdev_val / abs(mean_val)) * 100.0
    else:
        cv_percent = None

    p95_val = calculate_percentile(sorted_vals, 95.0)
    p99_val = calculate_percentile(sorted_vals, 99.0)

    return {
        "total_count": total_count,
        "valid_count": valid_count,
        "missing_count": missing_count,
        "mean": round(mean_val, 6),
        "median": median_val,
        "min": round(min_val, 6),
        "max": round(max_val, 6),
        "stdev": round(stdev_val, 6) if stdev_val is not None else None,
        "cv_percent": round(cv_percent, 4) if cv_percent is not None else None,
        "p50": median_val,
        "p95": p95_val,
        "p99": p99_val
    }

def aggregate_benchmark_results(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Groups benchmark execution payloads by (environment, benchmark) and
    computes full statistical distributions for each numerical metric.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}

    for run in runs:
        env = run.get("environment", "unknown")
        bench = run.get("benchmark", "unknown")
        key = f"{env}::{bench}"
        if key not in groups:
            groups[key] = []
        groups[key].append(run)

    summaries = {}

    for key, group_runs in groups.items():
        env, bench = key.split("::", 1)
        successful_runs = [r for r in group_runs if r.get("status") == "success"]
        unavailable_runs = [r for r in group_runs if r.get("status") == "unavailable"]
        failed_runs = [r for r in group_runs if r.get("status") == "failed"]

        # Collect metrics from successful runs
        numeric_series: Dict[str, List[float]] = {}
        checksums = []

        for r in successful_runs:
            metrics = r.get("metrics", {})
            # Top-level parsed metrics
            for mkey, mval in metrics.items():
                if mkey == "checksum":
                    checksums.append(str(mval))
                elif isinstance(mval, (int, float)) and not isinstance(mval, bool):
                    numeric_series.setdefault(mkey, []).append(float(mval))
                elif isinstance(mval, dict):
                    # Nested metrics like telemetry or results
                    for subkey, subval in mval.items():
                        if subkey == "checksum":
                            checksums.append(str(subval))
                        elif isinstance(subval, (int, float)) and not isinstance(subval, bool):
                            full_key = f"{mkey}.{subkey}"
                            numeric_series.setdefault(full_key, []).append(float(subval))

        stats_by_metric = {}
        for mname, vals in numeric_series.items():
            stats_by_metric[mname] = compute_statistics(vals)

        # Checksum determinism check
        unique_checksums = list(set(checksums))
        checksum_deterministic = (len(unique_checksums) == 1) if checksums else None

        summaries[key] = {
            "environment": env,
            "benchmark": bench,
            "run_counts": {
                "total": len(group_runs),
                "success": len(successful_runs),
                "unavailable": len(unavailable_runs),
                "failed": len(failed_runs)
            },
            "checksum_analysis": {
                "is_deterministic": checksum_deterministic,
                "unique_checksums": unique_checksums
            },
            "metrics": stats_by_metric
        }

    return summaries

if __name__ == "__main__":
    sample_data = [10.0, 12.0, 11.0, 10.5, 11.5, 12.5, None, 10.2]
    stats = compute_statistics(sample_data)
    print("Sample Statistics Computation:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
