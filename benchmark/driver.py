#!/usr/bin/env python3
"""
driver.py - Benchmark Execution Orchestration Engine for CC2.
Coordinates workload execution across Host Baseline, KVM/QEMU, VirtualBox, and LXC.
Integrates:
- /usr/bin/time -v and perf telemetry via MeasurementEngine
- VersionedBenchmarkResult schema (v2.0.0)
- ResultStorageManager (raw/, processed/, statistics/)
- Anti-fabrication guarantees and strict non-destructive safety
"""

import os
import sys
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collector.common import (
    SafetyValidator,
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_UNAVAILABLE,
    ENV_HOST,
    ENV_KVM,
    ENV_VIRTUALBOX,
    ENV_LXC
)
from collector.measurement import MeasurementEngine
from collector.schema import (
    VersionedBenchmarkResult,
    ResultStorageManager,
    create_versioned_result,
    SCHEMA_VERSION
)
from analysis.statistics_engine import aggregate_benchmark_results

RESULTS_DIR = PROJECT_ROOT / "results"
DIST_DIR = PROJECT_ROOT / "workloads" / "dist"

class BenchmarkDriver:
    """Orchestrates benchmark runs and telemetry collection."""

    def __init__(self, experiment_id: str = "exp-cc2-phase1"):
        self.experiment_id = experiment_id
        self.storage = ResultStorageManager(RESULTS_DIR)
        self.measurement = MeasurementEngine()
        self.inventory = self._load_inventory()

    def _load_inventory(self) -> Dict[str, Any]:
        p = RESULTS_DIR / "host_inventory.json"
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def sync_to_dashboard(self):
        """Updates dashboard/src/data/runs.json with all processed runs."""
        dashboard_data = PROJECT_ROOT / "dashboard" / "src" / "data"
        if dashboard_data.exists():
            runs = self.storage.load_all_processed_runs()
            with open(dashboard_data / "runs.json", "w", encoding="utf-8") as f:
                json.dump(runs, f, indent=2)

    def run_host_cpu_workload(
        self,
        size: int = 300,
        iterations: int = 5,
        warmup: int = 1,
        threads: int = 1
    ) -> VersionedBenchmarkResult:
        """Executes deterministic CPU workload on host baseline with kernel telemetry."""
        bin_path = DIST_DIR / "cpu_workload"
        if not bin_path.exists():
            # Build package
            res = os.system(f"make -C {PROJECT_ROOT}/workloads all")
            if res != 0:
                raise RuntimeError("Failed to build workloads")

        cmd = f"{bin_path} --size {size} --iterations {iterations} --warmup {warmup} --threads {threads}"
        measured = self.measurement.run_measured(cmd, cwd=str(PROJECT_ROOT))

        parsed_json = {}
        if measured["exit_code"] == 0 and measured["stdout"]:
            try:
                parsed_json = json.loads(measured["stdout"])
            except json.JSONDecodeError:
                pass

        result = create_versioned_result(
            experiment_id=self.experiment_id,
            environment=ENV_HOST,
            benchmark="cpu_deterministic",
            command=cmd,
            measured_output=measured,
            workload_parsed_json=parsed_json
        )

        # Persist raw and processed
        self.storage.save_raw_result(result)
        self.storage.append_processed_result(result)
        
        # Also append to legacy results/benchmark_runs.jsonl for backward compatibility
        with open(RESULTS_DIR / "benchmark_runs.jsonl", "a", encoding="utf-8") as f:
            f.write(result.to_json() + "\n")

        self.sync_to_dashboard()
        return result

    def run_host_memory_workload(
        self,
        buffer_mb: int = 128,
        passes: int = 4,
        stride: int = 64
    ) -> VersionedBenchmarkResult:
        """Executes deterministic memory workload on host baseline with kernel telemetry."""
        bin_path = DIST_DIR / "memory_workload"
        if not bin_path.exists():
            res = os.system(f"make -C {PROJECT_ROOT}/workloads all")
            if res != 0:
                raise RuntimeError("Failed to build workloads")

        cmd = f"{bin_path} --buffer-mb {buffer_mb} --passes {passes} --stride {stride}"
        measured = self.measurement.run_measured(cmd, cwd=str(PROJECT_ROOT))

        parsed_json = {}
        if measured["exit_code"] == 0 and measured["stdout"]:
            try:
                parsed_json = json.loads(measured["stdout"])
            except json.JSONDecodeError:
                pass

        result = create_versioned_result(
            experiment_id=self.experiment_id,
            environment=ENV_HOST,
            benchmark="memory_deterministic",
            command=cmd,
            measured_output=measured,
            workload_parsed_json=parsed_json
        )

        self.storage.save_raw_result(result)
        self.storage.append_processed_result(result)

        with open(RESULTS_DIR / "benchmark_runs.jsonl", "a", encoding="utf-8") as f:
            f.write(result.to_json() + "\n")

        self.sync_to_dashboard()
        return result

    def run_lxc_cpu_workload(
        self,
        container_name: Optional[str] = None,
        size: int = 300,
        iterations: int = 5,
        warmup: int = 1
    ) -> Dict[str, Any]:
        """Executes deterministic CPU workload on Native LXC adapter with cgroups v2 telemetry."""
        from benchmark.lxc_adapter import LxcDiscovery, LxcWorkloadRunner
        c_name = container_name or LxcDiscovery.get_preferred_container() or "lxc-ubuntu"
        runner = LxcWorkloadRunner(experiment_id=self.experiment_id)
        res = runner.run_cpu_benchmark(c_name, size=size, iterations=iterations, warmup=warmup)
        self.sync_to_dashboard()
        return res

    def run_lxc_memory_workload(
        self,
        container_name: Optional[str] = None,
        buffer_mb: int = 128,
        passes: int = 4,
        stride: int = 64
    ) -> Dict[str, Any]:
        """Executes deterministic memory workload on Native LXC adapter with cgroups v2 telemetry."""
        from benchmark.lxc_adapter import LxcDiscovery, LxcWorkloadRunner
        c_name = container_name or LxcDiscovery.get_preferred_container() or "lxc-ubuntu"
        runner = LxcWorkloadRunner(experiment_id=self.experiment_id)
        res = runner.run_memory_benchmark(c_name, buffer_mb=buffer_mb, passes=passes, stride=stride)
        self.sync_to_dashboard()
        return res

    def generate_statistics_report(self) -> Dict[str, Any]:
        """Computes statistical report across all processed runs and persists to results/statistics/."""
        all_runs = self.storage.load_all_processed_runs()
        stats = aggregate_benchmark_results(all_runs)
        for key, report in stats.items():
            self.storage.save_statistics(key, report)
        return stats

if __name__ == "__main__":
    driver = BenchmarkDriver()
    print("=== CC2 PHASE 1: SAMPLE HOST BENCHMARKS ===")
    print("[1/2] Executing Sample Host CPU Benchmark (Size=250, Iterations=3)...")
    cpu_res = driver.run_host_cpu_workload(size=250, iterations=3, warmup=1)
    print(f"  Status:    {cpu_res.status}")
    print(f"  GFLOPS:    {cpu_res.metrics.get('gflops')}")
    print(f"  Checksum:  {cpu_res.metrics.get('checksum')}")
    print(f"  Wall Time: {cpu_res.metrics.get('wall_time_sec')}s")
    print(f"  CPU %:     {cpu_res.metrics.get('cpu_percentage')}%")
    print(f"  Max RSS:   {cpu_res.metrics.get('max_rss_kb')} KB")

    print("\n[2/2] Executing Sample Host Memory Benchmark (Buffer=64MB, Passes=3)...")
    mem_res = driver.run_host_memory_workload(buffer_mb=64, passes=3, stride=64)
    print(f"  Status:     {mem_res.status}")
    print(f"  Throughput: {mem_res.metrics.get('throughput_mb_s')} MB/s")
    print(f"  Checksum:   {mem_res.metrics.get('checksum')}")
    print(f"  Wall Time:  {mem_res.metrics.get('wall_time_sec')}s")
    print(f"  Max RSS:    {mem_res.metrics.get('max_rss_kb')} KB")

    print("\n[3/3] Generating Statistical Synthesis...")
    stats_rep = driver.generate_statistics_report()
    for k, v in stats_rep.items():
        print(f"  Summary for {k}: total={v['run_counts']['total']}, deterministic={v['checksum_analysis']['is_deterministic']}")
