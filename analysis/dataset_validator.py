#!/usr/bin/env python3
"""
analysis/dataset_validator.py - Comprehensive Raw Result Validation & Clean Analysis Dataset Generator for CC2.

Enforces:
1. Schema & Integrity Validation across all raw JSON payloads in results/raw/
   - Valid JSON syntax
   - Schema version 2.0.0
   - Recognized environments (host, kvm, virtualbox, lxc)
   - Mandatory provenance fields (run_id, timestamp, command, exit_code, metrics, status)
   - Workload binary SHA256 integrity verification against MANIFEST.json
   - Anti-fabrication check: Unavailable metrics must remain null and NEVER be coerced to zero
   - Secret scan: Prohibits private keys, plaintext passwords, or auth tokens in results
2. Workload Consistency Verification across comparable environments
3. Quality Flags Assignment: PASS, WARNING, FAILED, UNAVAILABLE
4. 100% Traceability linking every aggregate back to raw run IDs
5. Generation of:
   - results/processed/analysis_dataset.json & analysis_dataset.csv
   - results/processed/environment_summary.json (strictly NO winner/ranking/score fields)
   - results/processed/analysis_manifest.json
"""

import os
import re
import sys
import csv
import json
import math
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Set

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collector.common import (
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_UNAVAILABLE,
    VALID_STATUSES,
    VALID_ENVIRONMENTS
)
from collector.schema import SCHEMA_VERSION
from analysis.statistics_engine import compute_statistics, calculate_percentile
from benchmark.runner.benchmarks import BENCHMARK_REGISTRY, CPU_BENCHMARK

RESULTS_DIR = PROJECT_ROOT / "results"
RAW_DIR = RESULTS_DIR / "raw"
PROCESSED_DIR = RESULTS_DIR / "processed"
MANIFEST_FILE = PROJECT_ROOT / "workloads" / "MANIFEST.json"

# Metric units dictionary for clean tabular export
METRIC_UNITS: Dict[str, str] = {
    "gflops": "GFLOPS",
    "throughput_mb_s": "MB/s",
    "ops_per_sec": "ops/sec",
    "switches_per_sec": "switches/sec",
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
    "read_iops": "IOPS",
    "write_iops": "IOPS",
    "read_throughput_mb_s": "MB/s",
    "write_throughput_mb_s": "MB/s",
    "read_latency_p95_us": "us",
    "write_latency_p95_us": "us",
    "sender_bandwidth_mbps": "Mbps",
    "receiver_bandwidth_mbps": "Mbps",
    "p50": "ms",
    "p95": "ms",
    "p99": "ms",
    "requests_completed": "count",
    "hypervisor_start_sec": "s",
    "guest_boot_sec": "s",
    "network_ready_sec": "s",
    "app_ready_sec": "s",
    "total_startup_sec": "s"
}

# Secret detection patterns (passwords, tokens, private keys)
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"password\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
    re.compile(r"ssh-rsa\s+AAAA[0-9A-Za-z+/]+"),
    re.compile(r"\"(ssh_password|password|secret|api_key)\"\s*:\s*\"[^\"]+\"", re.IGNORECASE)
]


class RawResultValidator:
    """Validates individual and collections of raw benchmark execution payloads."""

    def __init__(self, raw_dir: Path = RAW_DIR, manifest_path: Path = MANIFEST_FILE):
        self.raw_dir = raw_dir
        self.manifest_path = manifest_path
        self.canonical_workloads = self._load_workload_manifest()

    def _load_workload_manifest(self) -> Dict[str, Dict[str, Any]]:
        """Loads canonical workload SHA256 hashes from MANIFEST.json."""
        workloads = {}
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data.get("workloads", []):
                        workloads[item["workload_name"]] = item
                        workloads[item["binary"]] = item
            except Exception:
                pass
        return workloads

    def validate_single_payload(self, payload: Dict[str, Any], file_path: Optional[Path] = None) -> Tuple[bool, List[str]]:
        """
        Rigorously validates a single raw result payload against Schema 2.0.0 and CC2 invariants.
        Returns (is_valid, list_of_error_strings).
        """
        errors = []

        # 1. Required Top-Level Schema Fields
        required_fields = [
            "schema_version", "experiment_id", "run_id", "environment",
            "benchmark", "timestamp", "command", "status", "metrics"
        ]
        for field in required_fields:
            if field not in payload:
                errors.append(f"Missing mandatory field '{field}'")

        if errors:
            return False, errors

        # 2. Schema Version
        if str(payload.get("schema_version")) != SCHEMA_VERSION:
            errors.append(f"Invalid schema_version '{payload.get('schema_version')}'. Expected '{SCHEMA_VERSION}'")

        # 3. Environment Validity
        env = payload.get("environment")
        if env not in VALID_ENVIRONMENTS:
            errors.append(f"Invalid environment '{env}'. Must be one of {VALID_ENVIRONMENTS}")

        # 4. Status Validity
        status = payload.get("status")
        if status not in VALID_STATUSES and status not in ("timeout",):
            errors.append(f"Invalid status '{status}'. Must be in {VALID_STATUSES}")

        # 5. Non-Mock / Anti-Fabrication Check
        metrics = payload.get("metrics", {})
        if not isinstance(metrics, dict):
            errors.append(f"'metrics' must be a JSON object, got {type(metrics).__name__}")
            metrics = {}

        if status == STATUS_UNAVAILABLE:
            # Check for illegal coercion of missing values to zero
            for k, v in metrics.items():
                if k in ("gflops", "throughput_mb_s", "ops_per_sec", "switches_per_sec", "rtt_avg_ms", "sender_bandwidth_mbps"):
                    if v == 0 or v == 0.0:
                        errors.append(f"Anti-fabrication violation: Metric '{k}' was illegally coerced to zero in unavailable run")

        # 6. Success Status Coherence
        if status == STATUS_SUCCESS:
            exec_info = payload.get("execution", {})
            exit_code = exec_info.get("exit_code") if isinstance(exec_info, dict) else payload.get("exit_code")
            if exit_code is not None and exit_code != 0:
                errors.append(f"Contradiction: Status is 'success' but exit code is {exit_code}")

        # 7. Workload SHA256 Verification (if workload specified)
        workload_info = payload.get("workload")
        if isinstance(workload_info, dict):
            wl_name = workload_info.get("name")
            wl_sha = workload_info.get("sha256")
            if wl_name and wl_name in self.canonical_workloads and wl_sha:
                canonical_sha = self.canonical_workloads[wl_name].get("sha256")
                if canonical_sha and canonical_sha != wl_sha:
                    errors.append(
                        f"Workload SHA256 mismatch for '{wl_name}': got {wl_sha[:16]}..., expected {canonical_sha[:16]}..."
                    )

        # 8. Secret Leakage Scanner
        payload_str = json.dumps(payload)
        for pat in SECRET_PATTERNS:
            if pat.search(payload_str):
                errors.append(f"SECURITY VIOLATION: Potential secret or credential pattern detected: {pat.pattern}")

        return len(errors) == 0, errors

    def validate_all_raw_files(self) -> Dict[str, Any]:
        """
        Scans and validates every JSON file in results/raw/.
        Does NOT delete any file. Reports all issues transparently.
        """
        results: Dict[str, Any] = {
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "raw_dir": str(self.raw_dir),
            "total_files": 0,
            "valid_files": 0,
            "invalid_files": 0,
            "validation_details": [],
            "issues": []
        }

        if not self.raw_dir.exists():
            return results

        all_json_files = sorted(list(self.raw_dir.glob("**/*.json")))
        results["total_files"] = len(all_json_files)

        for json_path in all_json_files:
            rel_path = json_path.relative_to(self.raw_dir)
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                try:
                    payload = json.loads(content)
                except json.JSONDecodeError as e:
                    results["invalid_files"] += 1
                    issue = {
                        "file": str(rel_path),
                        "type": "MALFORMED_JSON",
                        "error": str(e)
                    }
                    results["issues"].append(issue)
                    continue

                is_valid, errors = self.validate_single_payload(payload, json_path)
                if is_valid:
                    results["valid_files"] += 1
                else:
                    results["invalid_files"] += 1
                    results["issues"].append({
                        "file": str(rel_path),
                        "run_id": payload.get("run_id"),
                        "type": "SCHEMA_VIOLATION",
                        "errors": errors
                    })

            except Exception as e:
                results["invalid_files"] += 1
                results["issues"].append({
                    "file": str(rel_path),
                    "type": "READ_ERROR",
                    "error": str(e)
                })

        return results


class AnalysisDatasetGenerator:
    """
    Generates verified, traceable analysis datasets and manifests from raw benchmark results.
    """

    def __init__(
        self,
        raw_dir: Path = RAW_DIR,
        processed_dir: Path = PROCESSED_DIR,
        manifest_path: Path = MANIFEST_FILE
    ):
        self.raw_dir = raw_dir
        self.processed_dir = processed_dir
        self.manifest_path = manifest_path
        self.validator = RawResultValidator(raw_dir, manifest_path)

    def load_valid_raw_runs(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Loads all valid raw JSON runs from results/raw/.
        Preserves existing files without modification.
        """
        validation_report = self.validator.validate_all_raw_files()
        valid_runs = []

        all_json_files = sorted(list(self.raw_dir.glob("**/*.json")))
        for p in all_json_files:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                is_valid, _ = self.validator.validate_single_payload(payload, p)
                if is_valid:
                    payload["_source_file"] = str(p.relative_to(PROJECT_ROOT))
                    valid_runs.append(payload)
            except Exception:
                continue

        return valid_runs, validation_report

    def compute_metric_distribution(self, runs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Groups runs by (environment, benchmark) and calculates distributions for each metric.
        Never calculates statistics from failed or unavailable measurements.
        """
        groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for r in runs:
            env = r.get("environment")
            bench = r.get("benchmark")
            if env and bench:
                groups.setdefault((env, bench), []).append(r)

        dataset = {}

        for (env, bench), group_runs in sorted(groups.items()):
            successful = [r for r in group_runs if r.get("status") == STATUS_SUCCESS]
            failed = [r for r in group_runs if r.get("status") in (STATUS_FAILED, "timeout")]
            unavailable = [r for r in group_runs if r.get("status") == STATUS_UNAVAILABLE]

            # Metric series extraction from successful runs
            series: Dict[str, List[float]] = {}
            raw_run_map: Dict[str, List[str]] = {}
            checksums: List[str] = []

            for r in group_runs:
                run_id = r.get("run_id", "")
                m = r.get("metrics", {})
                status = r.get("status")

                if status == STATUS_SUCCESS:
                    for k, v in m.items():
                        if k == "checksum":
                            checksums.append(str(v))
                        elif isinstance(v, (int, float)) and not isinstance(v, bool):
                            series.setdefault(k, []).append(float(v))
                            raw_run_map.setdefault(k, []).append(run_id)
                        elif isinstance(v, dict):
                            for subk, subv in v.items():
                                if subk == "checksum":
                                    checksums.append(str(subv))
                                elif isinstance(subv, (int, float)) and not isinstance(subv, bool):
                                    full_k = f"{k}.{subk}"
                                    series.setdefault(full_k, []).append(float(subv))
                                    raw_run_map.setdefault(full_k, []).append(run_id)

            # Assign quality flag per benchmark
            quality_flag = "PASS"
            if len(unavailable) > 0 and len(successful) == 0:
                quality_flag = "UNAVAILABLE"
            elif len(failed) > 0 and len(successful) == 0:
                quality_flag = "FAILED"
            elif len(successful) < 2:
                quality_flag = "WARNING"

            # Checksum consistency check
            unique_checksums = list(set(checksums))
            if len(unique_checksums) > 1:
                quality_flag = "FAILED"

            metric_stats = {}
            for metric_name, values in series.items():
                stats = compute_statistics(values)
                stats["quality_flag"] = quality_flag
                stats["raw_run_ids"] = raw_run_map.get(metric_name, [])
                metric_stats[metric_name] = stats

            dataset[f"{env}::{bench}"] = {
                "environment": env,
                "benchmark": bench,
                "run_counts": {
                    "total": len(group_runs),
                    "success": len(successful),
                    "failed": len(failed),
                    "unavailable": len(unavailable)
                },
                "quality_flag": quality_flag,
                "checksum_analysis": {
                    "is_deterministic": len(unique_checksums) == 1 if checksums else None,
                    "checksums": unique_checksums
                },
                "metrics": metric_stats,
                "raw_run_ids": [r.get("run_id") for r in group_runs if r.get("run_id")]
            }

        return dataset

    def export_analysis_dataset(self, dataset: Dict[str, Any]) -> Tuple[Path, Path]:
        """
        Exports machine-readable analysis dataset to:
        - results/processed/analysis_dataset.json
        - results/processed/analysis_dataset.csv
        """
        self.processed_dir.mkdir(parents=True, exist_ok=True)

        # 1. JSON Export
        json_path = self.processed_dir / "analysis_dataset.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": SCHEMA_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "dataset": dataset
            }, f, indent=2)

        # 2. CSV Export
        csv_path = self.processed_dir / "analysis_dataset.csv"
        fieldnames = [
            "environment",
            "benchmark",
            "metric",
            "unit",
            "quality_flag",
            "total_runs",
            "successful_runs",
            "failed_runs",
            "unavailable_runs",
            "mean",
            "median",
            "min",
            "max",
            "stdev",
            "cv_percent",
            "p50",
            "p95",
            "p99",
            "traceable_run_count"
        ]

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for key, entry in sorted(dataset.items()):
                env = entry["environment"]
                bench = entry["benchmark"]
                counts = entry["run_counts"]
                metrics = entry["metrics"]

                for mname, mstats in sorted(metrics.items()):
                    short_metric = mname.split(".")[-1]
                    unit = METRIC_UNITS.get(short_metric, METRIC_UNITS.get(mname, ""))

                    row = {
                        "environment": env,
                        "benchmark": bench,
                        "metric": mname,
                        "unit": unit,
                        "quality_flag": mstats.get("quality_flag", entry["quality_flag"]),
                        "total_runs": counts["total"],
                        "successful_runs": counts["success"],
                        "failed_runs": counts["failed"],
                        "unavailable_runs": counts["unavailable"],
                        "mean": mstats.get("mean"),
                        "median": mstats.get("median"),
                        "min": mstats.get("min"),
                        "max": mstats.get("max"),
                        "stdev": mstats.get("stdev"),
                        "cv_percent": mstats.get("cv_percent"),
                        "p50": mstats.get("p50"),
                        "p95": mstats.get("p95"),
                        "p99": mstats.get("p99"),
                        "traceable_run_count": len(mstats.get("raw_run_ids", []))
                    }
                    writer.writerow(row)

        return json_path, csv_path

    def generate_environment_summary(self, dataset: Dict[str, Any]) -> Path:
        """
        Generates descriptive environment summary showing available measurements and variability.
        CRITICAL INVARIANT: Strictly NO winner, best, worst, ranking, or score fields.
        """
        summary_by_env: Dict[str, Any] = {}

        for env in ["host", "kvm", "virtualbox", "lxc"]:
            summary_by_env[env] = {
                "environment": env,
                "benchmarks_evaluated": {},
                "summary_timestamp": datetime.now(timezone.utc).isoformat()
            }

        for key, entry in sorted(dataset.items()):
            env = entry["environment"]
            bench = entry["benchmark"]
            if env not in summary_by_env:
                summary_by_env[env] = {"environment": env, "benchmarks_evaluated": {}}

            # Extract headline metrics for readability
            headline_metrics = {}
            for mname, mstats in entry["metrics"].items():
                if mname in (
                    "gflops", "throughput_mb_s", "ops_per_sec", "switches_per_sec",
                    "rtt_avg_ms", "p50", "readiness_latency_sec", "total_startup_sec"
                ):
                    headline_metrics[mname] = {
                        "mean": mstats.get("mean"),
                        "median": mstats.get("median"),
                        "cv_percent": mstats.get("cv_percent"),
                        "p95": mstats.get("p95"),
                        "quality_flag": mstats.get("quality_flag")
                    }

            summary_by_env[env]["benchmarks_evaluated"][bench] = {
                "run_counts": entry["run_counts"],
                "quality_flag": entry["quality_flag"],
                "checksum_deterministic": entry["checksum_analysis"].get("is_deterministic"),
                "primary_measurements": headline_metrics
            }

        out_path = self.processed_dir / "environment_summary.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": SCHEMA_VERSION,
                "description": "Descriptive empirical performance and variability summary per virtualization tier.",
                "invariants": "Strictly non-evaluative; zero ranking, winner, or score fields.",
                "environments": summary_by_env
            }, f, indent=2)

        return out_path

    def generate_analysis_manifest(
        self,
        runs: List[Dict[str, Any]],
        validation_report: Dict[str, Any]
    ) -> Path:
        """
        Generates analysis manifest linking processed datasets to input raw provenance logs.
        """
        experiment_ids = sorted(list({r.get("experiment_id") for r in runs if r.get("experiment_id")}))
        environments = sorted(list({r.get("environment") for r in runs if r.get("environment")}))
        benchmarks = sorted(list({r.get("benchmark") for r in runs if r.get("benchmark")}))

        # Collect workload versions & SHA256
        workload_hashes = {}
        for r in runs:
            wl = r.get("workload")
            if isinstance(wl, dict) and wl.get("name") and wl.get("sha256"):
                workload_hashes[wl["name"]] = wl["sha256"]

        manifest_data = {
            "schema_version": SCHEMA_VERSION,
            "manifest_type": "CC2 Analysis Dataset Manifest",
            "processing_timestamp": datetime.now(timezone.utc).isoformat(),
            "experiment_ids": experiment_ids,
            "environments": environments,
            "benchmarks": benchmarks,
            "total_raw_runs_ingested": len(runs),
            "workload_sha256_digests": workload_hashes,
            "validation_summary": {
                "total_scanned": validation_report.get("total_files", 0),
                "valid_files": validation_report.get("valid_files", 0),
                "invalid_files": validation_report.get("invalid_files", 0),
                "validation_status": "PASS" if validation_report.get("invalid_files", 0) == 0 else "WARNING"
            },
            "input_raw_locations": [str(self.raw_dir)]
        }

        out_path = self.processed_dir / "analysis_manifest.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

        return out_path

    def run_full_pipeline(self) -> Dict[str, Any]:
        """
        Executes complete Step 3 pipeline:
        validate raw -> compute distributions -> export CSV/JSON -> generate summaries & manifests.
        """
        valid_runs, validation_report = self.load_valid_raw_runs()
        dataset = self.compute_metric_distribution(valid_runs)
        json_path, csv_path = self.export_analysis_dataset(dataset)
        env_summary_path = self.generate_environment_summary(dataset)
        manifest_path = self.generate_analysis_manifest(valid_runs, validation_report)

        return {
            "valid_runs_count": len(valid_runs),
            "validation_report": validation_report,
            "dataset_json": str(json_path),
            "dataset_csv": str(csv_path),
            "environment_summary": str(env_summary_path),
            "analysis_manifest": str(manifest_path)
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="CC2 Raw Result Validation & Clean Analysis Dataset Generator")
    parser.add_argument("--validate-only", action="store_true", help="Run raw result validation checks only")
    args = parser.parse_args()

    generator = AnalysisDatasetGenerator()
    if args.validate_only:
        report = generator.validator.validate_all_raw_files()
        print(json.dumps(report, indent=2))
        sys.exit(0 if report.get("invalid_files", 0) == 0 else 1)
    else:
        out = generator.run_full_pipeline()
        print(f"[+] Successfully generated verified analysis dataset:")
        print(f"    - {out['dataset_json']}")
        print(f"    - {out['dataset_csv']}")
        print(f"    - {out['environment_summary']}")
        print(f"    - {out['analysis_manifest']}")
        print(f"[+] Total valid raw runs ingested: {out['valid_runs_count']}")
        print(f"[+] Validation status: {out['validation_report']['valid_files']} valid / {out['validation_report']['total_files']} total")


if __name__ == "__main__":
    main()
