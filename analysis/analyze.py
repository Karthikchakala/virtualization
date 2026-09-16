#!/usr/bin/env python3
"""
analyze.py - Statistical analysis and reporting engine for CC2 benchmark results.
Reads all processed runs, computes rigorous statistical distributions:
- mean, median, min, max
- sample standard deviation
- coefficient of variation (% CV)
- latency / performance percentiles (p50, p95, p99)

Generates:
1. results/report_summary.json
2. results/final_results.json
3. results/final_results.csv

Guarantees:
- Invariant: Never coerces missing/None values to zero.
- Preserves unavailable and failed status with explicit reasons.
- Verifies deterministic workload checksum consistency across runs.
"""

import os
import sys
import csv
import json
import math
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from analysis.statistics_engine import compute_statistics, calculate_percentile, aggregate_benchmark_results
from collector.common import STATUS_SUCCESS, STATUS_FAILED, STATUS_UNAVAILABLE

RESULTS_DIR = PROJECT_ROOT / "results"
PROCESSED_DIR = RESULTS_DIR / "processed"
DASHBOARD_DATA_DIR = PROJECT_ROOT / "dashboard" / "src" / "data"

METRIC_UNITS = {
    "gflops": "GFLOPS",
    "throughput_mb_s": "MB/s",
    "ops_per_sec": "ops/sec",
    "latency_ns": "ns",
    "latency_us": "us",
    "latency_ms": "ms",
    "rtt_avg_ms": "ms",
    "rtt_min_ms": "ms",
    "rtt_max_ms": "ms",
    "rtt_mdev_ms": "ms",
    "packet_loss_percent": "%",
    "elapsed_sec": "s",
    "wall_time_sec": "s",
    "user_time_sec": "s",
    "system_time_sec": "s",
    "cpu_percentage": "%",
    "max_rss_kb": "KB",
    "page_faults": "count",
    "voluntary_ctx_switches": "count",
    "involuntary_ctx_switches": "count",
    "total_syscalls": "count",
    "startup_time_sec": "s",
    "readiness_latency_sec": "s",
    "p50_latency_ms": "ms",
    "p95_latency_ms": "ms",
    "p99_latency_ms": "ms",
    "requests_per_sec": "req/sec",
}


def load_all_runs(source_dir: Path = PROCESSED_DIR) -> List[Dict[str, Any]]:
    """Loads all processed runs from runs.json or *.jsonl in results/processed/."""
    runs_json = source_dir / "runs.json"
    if runs_json.exists():
        try:
            with open(runs_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception:
            pass

    runs = []
    for p in source_dir.glob("*.jsonl"):
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line_s = line.strip()
                if line_s:
                    try:
                        runs.append(json.loads(line_s))
                    except json.JSONDecodeError:
                        continue
    return runs


def generate_final_results_csv(final_results: Dict[str, Any], output_path: Path):
    """Writes tabular metric statistical summaries to CSV."""
    fieldnames = [
        "environment",
        "benchmark",
        "metric",
        "unit",
        "sample_count",
        "valid_count",
        "mean",
        "median",
        "stdev",
        "cv_percent",
        "min",
        "max",
        "p50",
        "p95",
        "p99"
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for group_key, summary in sorted(final_results.get("benchmarks", {}).items()):
            env = summary.get("environment")
            bench = summary.get("benchmark")
            metrics = summary.get("metrics", {})

            for metric_name, stats in sorted(metrics.items()):
                # Determine unit
                short_metric = metric_name.split(".")[-1]
                unit = METRIC_UNITS.get(short_metric, METRIC_UNITS.get(metric_name, ""))

                row = {
                    "environment": env,
                    "benchmark": bench,
                    "metric": metric_name,
                    "unit": unit,
                    "sample_count": stats.get("total_count", 0),
                    "valid_count": stats.get("valid_count", 0),
                    "mean": stats.get("mean"),
                    "median": stats.get("median"),
                    "stdev": stats.get("stdev"),
                    "cv_percent": stats.get("cv_percent"),
                    "min": stats.get("min"),
                    "max": stats.get("max"),
                    "p50": stats.get("p50"),
                    "p95": stats.get("p95"),
                    "p99": stats.get("p99"),
                }
                writer.writerow(row)


def run_analysis(output_dir: Path = RESULTS_DIR) -> Dict[str, Any]:
    """
    Executes full statistical aggregation and exports all 3 required files:
    - results/report_summary.json
    - results/final_results.json
    - results/final_results.csv
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    runs = load_all_runs(output_dir / "processed")

    # Load host inventory metadata if present
    host_inventory_file = output_dir / "host_inventory.json"
    host_inventory = {}
    if host_inventory_file.exists():
        try:
            with open(host_inventory_file, "r", encoding="utf-8") as f:
                host_inventory = json.load(f)
        except Exception:
            pass

    os_info = host_inventory.get("os", {})
    cpu_info = host_inventory.get("cpu", {}).get("parsed", {})
    mem_info = host_inventory.get("memory", {})

    host_os_name = os_info.get("os_release", {}).get("PRETTY_NAME") or os_info.get("system")
    host_kernel_ver = os_info.get("kernel_release")
    host_cpu_name = cpu_info.get("Model name") or host_inventory.get("cpu", {}).get("model_name")
    host_cpu_cores = cpu_info.get("CPU(s)") or host_inventory.get("cpu", {}).get("total_logical_cores")
    host_ram = mem_info.get("total_kb") or mem_info.get("MemTotal") or host_inventory.get("memory", {}).get("total_mb")

    # Status counts and experiment metadata
    experiment_ids = set()
    environments = set()
    benchmarks = set()
    status_counts = {STATUS_SUCCESS: 0, STATUS_UNAVAILABLE: 0, STATUS_FAILED: 0}

    for r in runs:
        if "experiment_id" in r:
            experiment_ids.add(r["experiment_id"])
        if "environment" in r:
            environments.add(r["environment"])
        if "benchmark" in r:
            benchmarks.add(r["benchmark"])
        st = r.get("status", STATUS_FAILED)
        status_counts[st] = status_counts.get(st, 0) + 1

    # Aggregate statistical distributions using rigorous engine
    benchmark_summaries = aggregate_benchmark_results(runs)

    # 1. Final Results JSON
    final_results = {
        "metadata": {
            "schema_version": "2.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "experiment_ids": sorted(list(experiment_ids)),
            "total_runs": len(runs),
            "status_distribution": status_counts,
            "environments": sorted(list(environments)),
            "benchmarks": sorted(list(benchmarks)),
            "host_os": host_os_name,
            "host_kernel": host_kernel_ver,
            "host_cpu_model": host_cpu_name,
            "host_cpu_cores": host_cpu_cores,
            "host_ram": host_ram
        },
        "benchmarks": benchmark_summaries
    }

    final_results_path = output_dir / "final_results.json"
    with open(final_results_path, "w", encoding="utf-8") as f:
        json.dump(final_results, f, indent=2)

    # 2. Final Results CSV
    final_results_csv_path = output_dir / "final_results.csv"
    generate_final_results_csv(final_results, final_results_csv_path)

    # 3. Report Summary JSON (Executive & High-Level Comparison)
    # Extract core headline metrics per environment
    core_metrics_matrix = {}
    checksum_verification = {}

    for group_key, s in benchmark_summaries.items():
        env = s["environment"]
        bench = s["benchmark"]
        m = s["metrics"]
        chk = s.get("checksum_analysis", {})

        if chk.get("unique_checksums"):
            checksum_verification.setdefault(bench, {})[env] = {
                "is_deterministic": chk.get("is_deterministic"),
                "checksums": chk.get("unique_checksums")
            }

        core_metrics_matrix.setdefault(env, {})

        if bench == "cpu_deterministic" and "gflops" in m:
            core_metrics_matrix[env]["cpu_gflops"] = {
                "mean": m["gflops"].get("mean"),
                "cv_percent": m["gflops"].get("cv_percent"),
                "p50": m["gflops"].get("p50")
            }
        elif bench == "memory_deterministic" and "throughput_mb_s" in m:
            core_metrics_matrix[env]["memory_throughput_mb_s"] = {
                "mean": m["throughput_mb_s"].get("mean"),
                "cv_percent": m["throughput_mb_s"].get("cv_percent"),
                "p50": m["throughput_mb_s"].get("p50")
            }
        elif bench == "syscall_deterministic" and "latency_ns" in m:
            core_metrics_matrix[env]["syscall_latency_ns"] = {
                "mean": m["latency_ns"].get("mean"),
                "cv_percent": m["latency_ns"].get("cv_percent"),
                "p50": m["latency_ns"].get("p50")
            }
        elif bench == "scheduling_deterministic" and "latency_us" in m:
            core_metrics_matrix[env]["ctx_switch_latency_us"] = {
                "mean": m["latency_us"].get("mean"),
                "cv_percent": m["latency_us"].get("cv_percent"),
                "p50": m["latency_us"].get("p50")
            }
        elif bench == "network_ping" and "rtt_avg_ms" in m:
            core_metrics_matrix[env]["network_ping_avg_ms"] = {
                "mean": m["rtt_avg_ms"].get("mean"),
                "p50": m["rtt_avg_ms"].get("p50")
            }
        elif bench == "app_latency" and "p50_latency_ms" in m:
            core_metrics_matrix[env]["http_latency_p50_ms"] = {
                "mean": m["p50_latency_ms"].get("mean")
            }
        elif bench == "startup_lifecycle" and "readiness_latency_sec" in m:
            core_metrics_matrix[env]["startup_readiness_sec"] = {
                "mean": m["readiness_latency_sec"].get("mean"),
                "min": m["readiness_latency_sec"].get("min"),
                "max": m["readiness_latency_sec"].get("max")
            }

    report_summary = {
        "report_type": "CC2 Comparative Virtualization Performance Summary",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_evaluated_runs": len(runs),
        "status_breakdown": status_counts,
        "evaluated_environments": sorted(list(environments)),
        "evaluated_benchmarks": sorted(list(benchmarks)),
        "host_system": {
            "os": host_os_name,
            "kernel": host_kernel_ver,
            "cpu": host_cpu_name,
            "cores": host_cpu_cores,
            "memory": host_ram
        },
        "performance_matrix": core_metrics_matrix,
        "checksum_verification": checksum_verification
    }

    report_summary_path = output_dir / "report_summary.json"
    with open(report_summary_path, "w", encoding="utf-8") as f:
        json.dump(report_summary, f, indent=2)

    # Sync to dashboard
    if DASHBOARD_DATA_DIR.exists():
        try:
            with open(DASHBOARD_DATA_DIR / "runs.json", "w", encoding="utf-8") as f:
                json.dump(runs, f, indent=2)
        except Exception as e:
            print(f"[-] Warning: Failed to sync runs.json to dashboard: {e}")

    # Run verified analysis dataset pipeline (Phase B Step 3)
    try:
        from analysis.dataset_validator import AnalysisDatasetGenerator
        dataset_gen = AnalysisDatasetGenerator(raw_dir=output_dir / "raw", processed_dir=output_dir / "processed")
        dataset_out = dataset_gen.run_full_pipeline()
        print(f"    - {dataset_out['dataset_json']}")
        print(f"    - {dataset_out['dataset_csv']}")
        print(f"    - {dataset_out['environment_summary']}")
        print(f"    - {dataset_out['analysis_manifest']}")
    except Exception as e:
        print(f"[-] Warning: Failed to run AnalysisDatasetGenerator: {e}")

    print(f"[+] Successfully generated:")
    print(f"    - {report_summary_path} ({report_summary_path.stat().st_size} bytes)")
    print(f"    - {final_results_path} ({final_results_path.stat().st_size} bytes)")
    print(f"    - {final_results_csv_path} ({final_results_csv_path.stat().st_size} bytes)")

    return report_summary


def main():
    parser = argparse.ArgumentParser(description="CC2 Statistical Analysis and Report Generator")
    parser.add_argument("--output-dir", type=str, default=str(RESULTS_DIR), help="Output directory for generated results")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    run_analysis(output_dir=out_dir)


if __name__ == "__main__":
    main()
