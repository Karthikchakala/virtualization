#!/usr/bin/env python3
"""
schema.py - Versioned result schema and data persistence manager for CC2.
Enforces:
- schema_version
- experiment_id
- environment
- benchmark
- run_id
- timestamp
- command
- exit_code
- stdout
- stderr
- metrics
- status

Directory structure:
results/raw/
results/processed/
results/statistics/
"""

import os
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
RAW_DIR = RESULTS_DIR / "raw"
PROCESSED_DIR = RESULTS_DIR / "processed"
STATISTICS_DIR = RESULTS_DIR / "statistics"

SCHEMA_VERSION = "2.0.0"

VALID_ENVIRONMENTS = {"host", "kvm", "virtualbox", "lxc"}
VALID_STATUSES = {"success", "failed", "unavailable"}
VALID_BENCHMARKS = {
    "cpu_deterministic",
    "memory_deterministic",
    "syscall_deterministic",
    "scheduling_deterministic",
    "disk_fio",
    "network_ping",
    "network_iperf3",
    "app_latency",
    "startup_lifecycle",
    "isolation_audit"
}

@dataclass
class VersionedBenchmarkResult:
    schema_version: str
    experiment_id: str
    environment: str
    benchmark: str
    run_id: str
    timestamp: str
    command: str
    exit_code: int
    stdout: str
    stderr: str
    metrics: Dict[str, Any]
    status: str

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"Invalid schema_version '{self.schema_version}'. Expected '{SCHEMA_VERSION}'")
        if self.environment not in VALID_ENVIRONMENTS:
            raise ValueError(f"Invalid environment '{self.environment}'. Must be in {VALID_ENVIRONMENTS}")
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{self.status}'. Must be in {VALID_STATUSES}")
        if self.status == "unavailable" and not self.stderr and not self.metrics.get("reason"):
            # Unavailable runs should contain explanation
            pass

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VersionedBenchmarkResult":
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            experiment_id=data["experiment_id"],
            environment=data["environment"],
            benchmark=data["benchmark"],
            run_id=data["run_id"],
            timestamp=data["timestamp"],
            command=data["command"],
            exit_code=int(data["exit_code"]),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            metrics=data.get("metrics", {}),
            status=data["status"]
        )

class ResultStorageManager:
    """Manages raw, processed, and statistical result persistence."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or RESULTS_DIR
        self.raw_dir = self.base_dir / "raw"
        self.processed_dir = self.base_dir / "processed"
        self.statistics_dir = self.base_dir / "statistics"

        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.statistics_dir.mkdir(parents=True, exist_ok=True)

    def save_raw_result(self, result: VersionedBenchmarkResult) -> Path:
        """
        Saves individual raw execution payload to:
        results/raw/<environment>/<benchmark>/<run_id>.json
        Also preserves results/raw/<run_id>.json for backwards compatibility.
        """
        env_bench_dir = self.raw_dir / result.environment / result.benchmark
        env_bench_dir.mkdir(parents=True, exist_ok=True)
        hierarchical_path = env_bench_dir / f"{result.run_id}.json"
        with open(hierarchical_path, "w", encoding="utf-8") as f:
            f.write(result.to_json(indent=2))

        # Flat fallback
        flat_path = self.raw_dir / f"{result.run_id}.json"
        with open(flat_path, "w", encoding="utf-8") as f:
            f.write(result.to_json(indent=2))

        return hierarchical_path

    def append_processed_result(self, result: VersionedBenchmarkResult) -> Path:
        """Appends result to results/processed/{environment}_{benchmark}.jsonl."""
        filename = f"{result.environment}_{result.benchmark}.jsonl"
        out_path = self.processed_dir / filename
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(result.to_json() + "\n")
        return out_path

    def save_statistics(self, key: str, stats_payload: Dict[str, Any]) -> Path:
        """Saves statistical summary to results/statistics/{key}_stats.json."""
        clean_key = key.replace("::", "_")
        out_path = self.statistics_dir / f"{clean_key}_stats.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(stats_payload, f, indent=2)
        return out_path

    def load_all_processed_runs(self) -> List[Dict[str, Any]]:
        """Loads all processed runs across all environments."""
        runs = []
        for p in self.processed_dir.glob("*.jsonl"):
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line_s = line.strip()
                    if line_s:
                        try:
                            runs.append(json.loads(line_s))
                        except json.JSONDecodeError:
                            continue
        return runs

    def export_processed_to_csv(self) -> List[Path]:
        """Generates tabular CSV and JSON exports in results/processed/*.csv and *.json."""
        import csv
        runs = self.load_all_processed_runs()
        generated_paths = []
        if not runs:
            return generated_paths

        fieldnames = [
            "run_id", "experiment_id", "environment", "benchmark", "timestamp",
            "exit_code", "status", "gflops", "throughput_mb_s", "ops_per_sec",
            "latency_ns", "latency_us", "elapsed_sec", "wall_time_sec",
            "cpu_percentage", "max_rss_kb", "checksum"
        ]

        # 1. Global runs.csv
        global_csv = self.processed_dir / "runs.csv"
        with open(global_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in runs:
                metrics = r.get("metrics", {})
                row = {
                    "run_id": r.get("run_id"),
                    "experiment_id": r.get("experiment_id"),
                    "environment": r.get("environment"),
                    "benchmark": r.get("benchmark"),
                    "timestamp": r.get("timestamp"),
                    "exit_code": r.get("exit_code"),
                    "status": r.get("status"),
                    "checksum": metrics.get("checksum"),
                    "gflops": metrics.get("gflops"),
                    "throughput_mb_s": metrics.get("throughput_mb_s"),
                    "ops_per_sec": metrics.get("ops_per_sec"),
                    "latency_ns": metrics.get("latency_ns"),
                    "latency_us": metrics.get("latency_us"),
                    "elapsed_sec": metrics.get("elapsed_sec"),
                    "wall_time_sec": metrics.get("wall_time_sec"),
                    "cpu_percentage": metrics.get("cpu_percentage"),
                    "max_rss_kb": metrics.get("max_rss_kb"),
                }
                writer.writerow(row)
        generated_paths.append(global_csv)

        # 2. Per-benchmark CSVs
        by_bench: Dict[str, List[Dict[str, Any]]] = {}
        for r in runs:
            bench = r.get("benchmark", "unknown")
            by_bench.setdefault(bench, []).append(r)

        for bench, bench_runs in by_bench.items():
            bench_csv = self.processed_dir / f"{bench}.csv"
            with open(bench_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for r in bench_runs:
                    metrics = r.get("metrics", {})
                    row = {
                        "run_id": r.get("run_id"),
                        "experiment_id": r.get("experiment_id"),
                        "environment": r.get("environment"),
                        "benchmark": r.get("benchmark"),
                        "timestamp": r.get("timestamp"),
                        "exit_code": r.get("exit_code"),
                        "status": r.get("status"),
                        "checksum": metrics.get("checksum"),
                        "gflops": metrics.get("gflops"),
                        "throughput_mb_s": metrics.get("throughput_mb_s"),
                        "ops_per_sec": metrics.get("ops_per_sec"),
                        "latency_ns": metrics.get("latency_ns"),
                        "latency_us": metrics.get("latency_us"),
                        "elapsed_sec": metrics.get("elapsed_sec"),
                        "wall_time_sec": metrics.get("wall_time_sec"),
                        "cpu_percentage": metrics.get("cpu_percentage"),
                        "max_rss_kb": metrics.get("max_rss_kb"),
                    }
                    writer.writerow(row)
            generated_paths.append(bench_csv)

        # 3. Aggregated processed JSON
        runs_json = self.processed_dir / "runs.json"
        with open(runs_json, "w", encoding="utf-8") as f:
            json.dump(runs, f, indent=2)
        generated_paths.append(runs_json)

        return generated_paths

def create_versioned_result(
    experiment_id: str,
    environment: str,
    benchmark: str,
    command: str,
    measured_output: Dict[str, Any],
    workload_parsed_json: Optional[Dict[str, Any]] = None,
    status_override: Optional[str] = None
) -> VersionedBenchmarkResult:
    """Helper to construct a verified VersionedBenchmarkResult."""
    now_iso = datetime.now(timezone.utc).isoformat()
    run_id = f"{benchmark}-{environment}-{uuid.uuid4().hex[:8]}"

    exit_code = measured_output.get("exit_code", -1)
    stdout = measured_output.get("stdout", "")
    stderr = measured_output.get("stderr", "")
    telemetry = measured_output.get("telemetry", {})

    # Combine workload output and kernel telemetry
    combined_metrics: Dict[str, Any] = {}
    if workload_parsed_json:
        # Flatten workload results
        if "results" in workload_parsed_json:
            for k, v in workload_parsed_json["results"].items():
                combined_metrics[k] = v
        if "parameters" in workload_parsed_json:
            combined_metrics["parameters"] = workload_parsed_json["parameters"]

    # Add telemetry fields
    combined_metrics["telemetry"] = telemetry
    if telemetry.get("wall_time_sec") is not None:
        combined_metrics["wall_time_sec"] = telemetry["wall_time_sec"]
    if telemetry.get("user_time_sec") is not None:
        combined_metrics["user_time_sec"] = telemetry["user_time_sec"]
    if telemetry.get("system_time_sec") is not None:
        combined_metrics["system_time_sec"] = telemetry["system_time_sec"]
    if telemetry.get("cpu_percentage") is not None:
        combined_metrics["cpu_percentage"] = telemetry["cpu_percentage"]
    if telemetry.get("max_rss_kb") is not None:
        combined_metrics["max_rss_kb"] = telemetry["max_rss_kb"]

    if status_override:
        status = status_override
    elif exit_code == 0:
        status = "success"
    elif measured_output.get("timed_out"):
        status = "failed"
    else:
        status = "failed"

    return VersionedBenchmarkResult(
        schema_version=SCHEMA_VERSION,
        experiment_id=experiment_id,
        environment=environment,
        benchmark=benchmark,
        run_id=run_id,
        timestamp=now_iso,
        command=command,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        metrics=combined_metrics,
        status=status
    )
