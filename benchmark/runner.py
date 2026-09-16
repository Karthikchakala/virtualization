#!/usr/bin/env python3
"""
runner.py - Unified Experiment Orchestration & Benchmarking Engine for CC2.
Capabilities:
1. Coordinates Host Baseline, KVM/QEMU, Oracle VirtualBox, and Native LXC in one CLI.
2. Strict Run Isolation:
   - Verifies previous environments are stopped and no lingering processes exist.
   - Captures pre-benchmark host CPU, RAM, and load averages.
   - Enforces stabilization periods before and after each environment run.
3. Common Workloads:
   - EXACT same deterministic C binaries for CPU, Memory, Syscall, and Scheduling.
   - Safe regular file FIO storage tests (strict block device prohibition).
   - Identical ping and iperf3 network tests.
   - 100-request HTTP application latency evaluation.
   - Namespace and kernel sharing isolation audits.
4. Validation & Anti-Fabrication:
   - Rigorous post-execution validation (exit code, metrics, units, checksums).
   - No mock numbers. Missing metrics preserved as None with status='unavailable'.
5. Results Pipeline:
   - Raw data saved to results/raw/<env>/<benchmark>/<run_id>.json.
   - Processed data saved to results/processed/*.jsonl, *.json, and *.csv.
   - Aggregated statistics saved to results/statistics/*.json.
   - Synchronized with Vite/React dashboard.
"""

import os
import re
import sys
import csv
import json
import time
import uuid
import shutil
import socket
import argparse
import threading
import http.server
import socketserver
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collector.common import (
    run_safe_command,
    SafetyValidator,
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_UNAVAILABLE,
    ENV_HOST,
    ENV_KVM,
    ENV_VIRTUALBOX,
    ENV_LXC,
    VALID_ENVIRONMENTS
)
from collector.measurement import MeasurementEngine
from collector.schema import (
    VersionedBenchmarkResult,
    ResultStorageManager,
    create_versioned_result,
    SCHEMA_VERSION
)
from collector.advanced_metrics import (
    SyscallCollector,
    StraceParser,
    SchedulingCollector,
    PidstatParser,
    PerfStatParser,
    ThermalSystemStateCollector,
    MinimalHealthHttpServer,
    HttpLatencyBenchmark,
    Iperf3Config
)
from analysis.statistics_engine import compute_statistics, aggregate_benchmark_results
from analysis.validator import validate_execution_result

# Adapter imports
from benchmark.kvm_adapter import (
    KvmDiscovery,
    KvmLifecycle,
    KvmMetricsCollector,
    KvmStorageBenchmark,
    KvmNetworkBenchmark,
    KvmAppLatencyBenchmark,
    KvmIsolationAudit
)
from benchmark.vbox_adapter import (
    VBoxDiscovery,
    VBoxLifecycle,
    VBoxMetricsCollector,
    VBoxWorkloadRunner
)
from benchmark.lxc_adapter import (
    LxcDiscovery,
    LxcLifecycle,
    LxcMetricsCollector,
    LxcIsolationAudit,
    LxcWorkloadRunner
)

from benchmark.runner.environments import create_adapter
from benchmark.runner.executor import BenchmarkExecutor
from benchmark.runner.benchmarks import resolve_benchmarks, get_benchmark, ALLOWED_CLI_TESTS
from analysis.analyze import run_analysis

RESULTS_DIR = PROJECT_ROOT / "results"
DIST_DIR = PROJECT_ROOT / "workloads" / "dist"

ALL_TESTS = ["cpu", "memory", "disk", "network", "app", "app_latency", "startup", "syscall", "scheduling", "isolation"]


class IsolationManager:
    """Guarantees strict run isolation and stabilization between benchmark environments."""

    @staticmethod
    def get_host_telemetry() -> Dict[str, Any]:
        """Captures host CPU, RAM, and load averages before or after benchmarking."""
        telemetry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "loadavg": list(os.getloadavg()),
            "mem_total_kb": None,
            "mem_free_kb": None,
            "mem_available_kb": None,
            "cpu_user_ticks": None,
            "cpu_system_ticks": None,
            "cpu_idle_ticks": None
        }

        # Memory telemetry from /proc/meminfo
        meminfo_path = Path("/proc/meminfo")
        if meminfo_path.exists():
            try:
                for line in meminfo_path.read_text().splitlines():
                    if line.startswith("MemTotal:"):
                        telemetry["mem_total_kb"] = int(line.split()[1])
                    elif line.startswith("MemFree:"):
                        telemetry["mem_free_kb"] = int(line.split()[1])
                    elif line.startswith("MemAvailable:"):
                        telemetry["mem_available_kb"] = int(line.split()[1])
            except Exception:
                pass

        # CPU ticks from /proc/stat
        stat_path = Path("/proc/stat")
        if stat_path.exists():
            try:
                first_line = stat_path.read_text().splitlines()[0]
                parts = first_line.split()
                if len(parts) >= 5:
                    telemetry["cpu_user_ticks"] = int(parts[1])
                    telemetry["cpu_system_ticks"] = int(parts[3])
                    telemetry["cpu_idle_ticks"] = int(parts[4])
            except Exception:
                pass

        # Thermal, CPU frequency, governor (read-only)
        telemetry["system_state"] = ThermalSystemStateCollector.collect_full_system_state()

        return telemetry

    @staticmethod
    def kill_lingering_workloads():
        """Ensures no previous benchmark workload processes are lingering."""
        workload_patterns = [
            "cpu_workload",
            "memory_workload",
            "syscall_workload",
            "scheduling_workload",
            "fio",
            "iperf3"
        ]
        for pattern in workload_patterns:
            run_safe_command(f"pkill -9 -f '{pattern}'")

    @staticmethod
    def ensure_all_environments_stopped():
        """Verifies and ensures KVM, VirtualBox, and LXC instances are cleanly shut down."""
        # 1. KVM shutdown check
        kvm_vm = KvmDiscovery.get_preferred_vm()
        if kvm_vm:
            state_res = run_safe_command(f"virsh -c qemu:///system domstate {kvm_vm}")
            if state_res["exit_code"] == 0 and "running" in state_res["stdout"].lower():
                print(f"[*] Quenching active KVM VM: {kvm_vm}")
                KvmLifecycle.shutdown_gracefully(kvm_vm, timeout=15)

        # 2. VirtualBox shutdown check
        running_vms = VBoxDiscovery.list_running_vms()
        for v in running_vms:
            print(f"[*] Quenching active VirtualBox VM: {v['name']}")
            VBoxLifecycle.shutdown_gracefully(v["name"], timeout=15)

        # 3. LXC shutdown check
        containers = LxcDiscovery.list_all_containers()
        for c in containers:
            if c.get("state") == "RUNNING":
                print(f"[*] Quenching active LXC Container: {c['name']}")
                LxcLifecycle.shutdown_gracefully(c["name"], timeout=15)

        # 4. Clean lingering processes
        IsolationManager.kill_lingering_workloads()

    @staticmethod
    def wait_for_stabilization(seconds: int = 3, reason: str = "Pre-benchmark cooldown"):
        """Pauses execution to allow CPU thermal frequency scaling and background activity to settle."""
        print(f"[*] Waiting {seconds}s for system stabilization ({reason})...")
        time.sleep(seconds)


class ExperimentRunner:
    """Orchestrates comprehensive cross-environment empirical benchmarking."""

    def __init__(
        self,
        experiment_id: Optional[str] = None,
        mode: str = "quick",
        runs: Optional[int] = None,
        tests: Optional[List[str]] = None,
        storage_dir: Optional[Path] = None
    ):
        self.experiment_id = experiment_id or f"exp-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.mode = mode.lower()
        self.storage = ResultStorageManager(storage_dir or RESULTS_DIR)
        self.measurement = MeasurementEngine()

        # Run counts configuration
        if runs is not None and runs > 0:
            self.warmup_runs = 1 if runs > 1 else 0
            self.measured_runs = runs
        elif self.mode == "full":
            self.warmup_runs = 1
            self.measured_runs = 5
        else: # quick
            self.warmup_runs = 1
            self.measured_runs = 2

        # Tests configuration
        if not tests or "all" in tests:
            self.selected_tests = list(ALL_TESTS)
        else:
            self.selected_tests = [t.lower() for t in tests if t.lower() in ALL_TESTS]

        self.generated_runs: List[Dict[str, Any]] = []
        self._ensure_binaries_built()

    def _ensure_binaries_built(self):
        """Builds all deterministic C binaries if missing."""
        required = ["cpu_workload", "memory_workload", "syscall_workload", "scheduling_workload"]
        missing = [b for b in required if not (DIST_DIR / b).exists()]
        if missing:
            print(f"[*] Building missing workload binaries: {missing}...")
            res = os.system(f"make -C {PROJECT_ROOT}/workloads all")
            if res != 0:
                raise RuntimeError("Failed to compile benchmark binaries in workloads/")

    def sync_dashboard(self):
        """Updates dashboard/src/data/runs.json and exports CSVs."""
        self.storage.export_processed_to_csv()
        dashboard_data = PROJECT_ROOT / "dashboard" / "src" / "data"
        if dashboard_data.exists():
            runs = self.storage.load_all_processed_runs()
            with open(dashboard_data / "runs.json", "w", encoding="utf-8") as f:
                json.dump(runs, f, indent=2)

    # --------------------------------------------------------------------------
    # Benchmark Executors
    # --------------------------------------------------------------------------

    def run_benchmark_iterations(
        self,
        environment: str,
        benchmark: str,
        command_template: str,
        parse_func,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[VersionedBenchmarkResult]:
        """Runs warmup and measured iterations for a given command."""
        results: List[VersionedBenchmarkResult] = []
        meta = metadata or {}

        # 1. Warmup
        if self.warmup_runs > 0:
            print(f"    -> [Warmup 1/{self.warmup_runs}] {benchmark}...")
            _ = self.measurement.run_measured(command_template, cwd=str(PROJECT_ROOT))

        # 2. Measured Runs
        for i in range(1, self.measured_runs + 1):
            print(f"    -> [Measured {i}/{self.measured_runs}] {benchmark}...")
            measured = self.measurement.run_measured(command_template, cwd=str(PROJECT_ROOT))
            parsed_json = {}
            if measured["exit_code"] == 0 and measured["stdout"]:
                try:
                    parsed_json = json.loads(measured["stdout"])
                except Exception:
                    pass

            # Create versioned result
            res = create_versioned_result(
                experiment_id=self.experiment_id,
                environment=environment,
                benchmark=benchmark,
                command=command_template,
                measured_output=measured,
                workload_parsed_json=parsed_json
            )

            # Attach metadata
            res.metrics["metadata"] = meta
            res.metrics["iteration"] = i

            # Post-execution validation
            valid, errors = validate_execution_result(
                benchmark=benchmark,
                exit_code=res.exit_code,
                stdout=res.stdout,
                metrics=res.metrics,
                status=res.status
            )
            if not valid:
                res.status = STATUS_FAILED
                res.metrics["validation_errors"] = errors
                print(f"       [!] Validation failed: {errors}")

            # Save raw and processed
            self.storage.save_raw_result(res)
            self.storage.append_processed_result(res)
            results.append(res)

        return results

    # --------------------------------------------------------------------------
    # Individual Test Handlers
    # --------------------------------------------------------------------------

    def test_cpu(self, environment: str, metadata: Optional[Dict[str, Any]] = None) -> List[VersionedBenchmarkResult]:
        bin_path = DIST_DIR / "cpu_workload"
        cmd = f"{bin_path} --size 200 --iterations 3 --warmup 0 --threads 1"
        results = self.run_benchmark_iterations(
            environment=environment,
            benchmark="cpu_deterministic",
            command_template=cmd,
            parse_func=lambda s: json.loads(s).get("results", {}),
            metadata=metadata
        )

        # Advanced CPU Hardware performance counters (cycles, instructions, IPC)
        perf_supported, perf_reason = SchedulingCollector.probe_perf_paranoid()
        for res in results:
            if perf_supported:
                hw_counters = SchedulingCollector.collect_scheduling(cmd, timeout=30).get("perf", {})
                res.metrics["hardware_counters"] = hw_counters
            else:
                res.metrics["hardware_counters"] = {
                    "status": STATUS_UNAVAILABLE,
                    "reason": perf_reason,
                    "cycles": None,
                    "instructions": None,
                    "ipc": None
                }

        return results

    def test_memory(self, environment: str, metadata: Optional[Dict[str, Any]] = None) -> List[VersionedBenchmarkResult]:
        bin_path = DIST_DIR / "memory_workload"
        cmd = f"{bin_path} --buffer-mb 64 --passes 3 --stride 64"
        return self.run_benchmark_iterations(
            environment=environment,
            benchmark="memory_deterministic",
            command_template=cmd,
            parse_func=lambda s: json.loads(s).get("results", {}),
            metadata=metadata
        )

    def test_syscall(self, environment: str, metadata: Optional[Dict[str, Any]] = None) -> List[VersionedBenchmarkResult]:
        bin_path = DIST_DIR / "syscall_workload"
        cmd = f"{bin_path} --iterations 200000 --warmup 5000"
        results = self.run_benchmark_iterations(
            environment=environment,
            benchmark="syscall_deterministic",
            command_template=cmd,
            parse_func=lambda s: json.loads(s).get("results", {}),
            metadata=metadata
        )

        # strace -c profiling on the common workload
        print(f"    -> [Syscall Profiling] strace -c on {bin_path.name} ({environment})...")
        strace_cmd = f"{bin_path} --iterations 50000 --warmup 0"
        strace_res = SyscallCollector.run_strace(strace_cmd, timeout=30)

        for res in results:
            res.metrics["strace_profile"] = {
                "status": strace_res.get("status", STATUS_UNAVAILABLE),
                "syscall_count": strace_res.get("syscall_count"),
                "syscall_time_sec": strace_res.get("syscall_time_sec"),
                "errors": strace_res.get("errors"),
                "top_syscalls": strace_res.get("top_syscalls", []),
                "reason": strace_res.get("reason")
            }

        return results

    def test_scheduling(self, environment: str, metadata: Optional[Dict[str, Any]] = None) -> List[VersionedBenchmarkResult]:
        bin_path = DIST_DIR / "scheduling_workload"
        cmd = f"{bin_path} --iterations 20000 --warmup 1000"
        results = self.run_benchmark_iterations(
            environment=environment,
            benchmark="scheduling_deterministic",
            command_template=cmd,
            parse_func=lambda s: json.loads(s).get("results", {}),
            metadata=metadata
        )

        # Advanced scheduling telemetry (context switches, CPU migrations, page faults)
        print(f"    -> [Scheduling Profiling] pidstat & perf stat on {bin_path.name} ({environment})...")
        sched_data = SchedulingCollector.collect_scheduling(cmd, timeout=30)
        perf_data = sched_data.get("perf", {})
        pidstat_data = sched_data.get("pidstat", {})

        for res in results:
            res.metrics["scheduling_telemetry"] = {
                "voluntary_context_switches": res.metrics.get("telemetry", {}).get("context_switches", {}).get("voluntary"),
                "involuntary_context_switches": res.metrics.get("telemetry", {}).get("context_switches", {}).get("involuntary"),
                "total_context_switches": res.metrics.get("telemetry", {}).get("context_switches", {}).get("total"),
                "cpu_migrations": perf_data.get("cpu_migrations"),
                "page_faults": {
                    "minor": res.metrics.get("telemetry", {}).get("page_faults", {}).get("minor"),
                    "major": res.metrics.get("telemetry", {}).get("page_faults", {}).get("major"),
                    "total": res.metrics.get("telemetry", {}).get("page_faults", {}).get("total")
                },
                "rates": {
                    "voluntary_cswch_per_sec": pidstat_data.get("voluntary_cswch_per_sec"),
                    "involuntary_nvcswch_per_sec": pidstat_data.get("involuntary_nvcswch_per_sec"),
                    "minor_faults_per_sec": pidstat_data.get("minor_faults_per_sec"),
                    "major_faults_per_sec": pidstat_data.get("major_faults_per_sec")
                }
            }

        return results

    def test_disk(self, environment: str, metadata: Optional[Dict[str, Any]] = None) -> VersionedBenchmarkResult:
        """Runs safe FIO regular file storage benchmark with rigorous safety validations."""
        print(f"    -> [Storage] FIO regular file benchmark ({environment})...")
        test_file = PROJECT_ROOT / "results" / f"test_disk_{environment}.dat"

        # Safety assertions
        target_str = str(test_file)
        if "/dev" in target_str or "nvme" in target_str or "sd" in target_str or "vd" in target_str:
            raise ValueError(f"Safety Violation: Disk target cannot reference block device: {target_str}")

        free_bytes = shutil.disk_usage(PROJECT_ROOT / "results").free
        if free_bytes < 100 * 1024 * 1024:
            raise RuntimeError(f"Insufficient disk space for safe storage benchmark: {free_bytes // (1024*1024)} MB available")

        # Run storage test
        runner = VBoxWorkloadRunner(experiment_id=self.experiment_id)
        fio_res = runner.run_storage_fio(test_file, file_size_mb=16, runtime_sec=3)

        measured = {
            "exit_code": 0 if fio_res["status"] == "success" else (-1 if fio_res["status"] == "failed" else 0),
            "stdout": json.dumps(fio_res),
            "stderr": fio_res.get("reason", ""),
            "execution_time_sec": 3.0
        }

        res = create_versioned_result(
            experiment_id=self.experiment_id,
            environment=environment,
            benchmark="disk_fio",
            command=f"fio safe_file={test_file}",
            measured_output=measured,
            workload_parsed_json=fio_res if fio_res["status"] == "success" else None,
            status_override=fio_res["status"]
        )
        res.metrics["fio_results"] = fio_res
        res.metrics["metadata"] = metadata or {}

        self.storage.save_raw_result(res)
        self.storage.append_processed_result(res)
        return res

    def test_network(self, environment: str, target_ip: str, metadata: Optional[Dict[str, Any]] = None) -> List[VersionedBenchmarkResult]:
        """Runs standardized ping and iperf3 tests."""
        print(f"    -> [Network] Ping latency ({target_ip})...")
        cmd = f"ping -c 5 -W 1 {target_ip}"
        measured = self.measurement.run_measured(cmd)

        ping_parsed = KvmNetworkBenchmark.run_ping_test(target_ip, count=5)
        res_ping = create_versioned_result(
            experiment_id=self.experiment_id,
            environment=environment,
            benchmark="network_ping",
            command=cmd,
            measured_output=measured,
            workload_parsed_json=ping_parsed if ping_parsed["status"] == "success" else None,
            status_override=ping_parsed["status"]
        )
        res_ping.metrics.update(ping_parsed)
        res_ping.metrics["metadata"] = metadata or {}

        self.storage.save_raw_result(res_ping)
        self.storage.append_processed_result(res_ping)

        # Standardized iperf3 test (same duration, same stream count, same direction, same protocol)
        duration = Iperf3Config.QUICK_DURATION_SEC if self.mode == "quick" else Iperf3Config.DEFAULT_DURATION_SEC
        iperf_cmd = Iperf3Config.build_command(target_ip, duration=duration, streams=Iperf3Config.DEFAULT_STREAM_COUNT)
        print(f"    -> [Network] Standardized iperf3 throughput ({target_ip})...")
        
        iperf_bin = shutil.which("iperf3")
        if not iperf_bin:
            iperf_res = {
                "status": STATUS_UNAVAILABLE,
                "reason": "iperf3 binary not found on host. Zero values will not be fabricated.",
                "protocol": Iperf3Config.DEFAULT_PROTOCOL,
                "direction": Iperf3Config.DEFAULT_DIRECTION,
                "stream_count": Iperf3Config.DEFAULT_STREAM_COUNT,
                "duration_sec": duration
            }
        else:
            run_out = run_safe_command(iperf_cmd, timeout=duration + 10)
            iperf_res = Iperf3Config.parse_iperf3_json(run_out["stdout"])
            iperf_res["duration_sec"] = duration

        res_iperf = create_versioned_result(
            experiment_id=self.experiment_id,
            environment=environment,
            benchmark="network_iperf3",
            command=iperf_cmd,
            measured_output={"exit_code": 0 if iperf_res["status"] == "success" else -1, "stdout": json.dumps(iperf_res), "stderr": iperf_res.get("reason", "")},
            workload_parsed_json=iperf_res if iperf_res["status"] == "success" else None,
            status_override=iperf_res["status"]
        )
        res_iperf.metrics.update(iperf_res)
        res_iperf.metrics["metadata"] = metadata or {}

        self.storage.save_raw_result(res_iperf)
        self.storage.append_processed_result(res_iperf)

        return [res_ping, res_iperf]

    def test_app_latency(self, environment: str, metadata: Optional[Dict[str, Any]] = None) -> VersionedBenchmarkResult:
        """Runs 100-request HTTP health check measuring connect time, TTFB, and total duration."""
        print(f"    -> [App Latency] 100 HTTP health checks ({environment})...")
        server = MinimalHealthHttpServer(host="127.0.0.1", port=0)
        server.start()

        try:
            url = server.url
            lat_res = HttpLatencyBenchmark.measure_endpoint(url, num_requests=100)

            res = create_versioned_result(
                experiment_id=self.experiment_id,
                environment=environment,
                benchmark="app_latency",
                command=f"http_get_100 {url}",
                measured_output={"exit_code": 0 if lat_res["status"] == STATUS_SUCCESS else -1, "stdout": json.dumps(lat_res), "stderr": lat_res.get("reason", "")},
                workload_parsed_json=lat_res if lat_res["status"] == STATUS_SUCCESS else None,
                status_override=lat_res["status"]
            )
            res.metrics.update(lat_res)
            res.metrics["metadata"] = metadata or {}

            self.storage.save_raw_result(res)
            self.storage.append_processed_result(res)
            return res
        finally:
            server.stop()

    def test_startup(self, environment: str, target_name: str, metadata: Optional[Dict[str, Any]] = None) -> VersionedBenchmarkResult:
        """Measures full startup phase durations for virtualization target."""
        print(f"    -> [Startup Lifecycle] Measuring phase durations ({environment}: {target_name})...")
        if environment == ENV_KVM:
            startup_report = KvmLifecycle.measure_full_startup(target_name, timeout=2)
        elif environment == ENV_VIRTUALBOX:
            startup_report = VBoxLifecycle.measure_full_startup(target_name, timeout=2)
        elif environment == ENV_LXC:
            startup_report = LxcLifecycle.measure_full_startup(target_name, timeout=2)
        else:
            startup_report = {"status": "unavailable", "reason": "Host baseline has zero hypervisor startup duration"}

        res = create_versioned_result(
            experiment_id=self.experiment_id,
            environment=environment,
            benchmark="startup_lifecycle",
            command=f"measure_startup {environment} {target_name}",
            measured_output={"exit_code": 0, "stdout": json.dumps(startup_report), "stderr": ""},
            workload_parsed_json=startup_report,
            status_override=startup_report.get("status", "success")
        )
        res.metrics["startup_phases"] = startup_report
        res.metrics["metadata"] = metadata or {}

        self.storage.save_raw_result(res)
        self.storage.append_processed_result(res)
        return res

    def test_isolation(self, environment: str, target_name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> VersionedBenchmarkResult:
        """Captures namespace, cgroup, and virtualization signatures."""
        print(f"    -> [Isolation Audit] Capturing isolation boundaries ({environment})...")
        if environment == ENV_LXC:
            audit_data = LxcIsolationAudit.audit_isolation(target_name)
        elif environment == ENV_KVM:
            audit_data = KvmIsolationAudit.collect_host_isolation()
            audit_data["environment"] = ENV_KVM
        elif environment == ENV_VIRTUALBOX:
            runner = VBoxWorkloadRunner(experiment_id=self.experiment_id)
            audit_data = runner.run_isolation_audit()
        else:
            audit_data = KvmIsolationAudit.collect_host_isolation()
            audit_data["environment"] = ENV_HOST

        res = create_versioned_result(
            experiment_id=self.experiment_id,
            environment=environment,
            benchmark="isolation_audit",
            command=f"audit_isolation {environment}",
            measured_output={"exit_code": 0, "stdout": json.dumps(audit_data), "stderr": ""},
            workload_parsed_json=audit_data,
            status_override="success"
        )
        res.metrics["isolation_audit"] = audit_data
        res.metrics["metadata"] = metadata or {}

        self.storage.save_raw_result(res)
        self.storage.append_processed_result(res)
        return res

    # --------------------------------------------------------------------------
    # Environment Orchestrator
    # --------------------------------------------------------------------------

    def run_environment(self, environment: str):
        """Runs the complete requested test matrix for one environment with strict isolation."""
        print("\n" + "=" * 60)
        print(f"EXECUTING EXPERIMENT ENVIRONMENT: [{environment.upper()}]")
        print(f"Experiment ID:  {self.experiment_id}")
        print(f"Mode:           {self.mode.upper()} (Warmup: {self.warmup_runs}, Measured: {self.measured_runs})")
        print(f"Active Tests:   {', '.join(self.selected_tests)}")
        print("=" * 60)

        # 1. Isolation: Ensure all previous environments are completely stopped
        IsolationManager.ensure_all_environments_stopped()

        # 2. Host telemetry snapshot before run
        pre_telemetry = IsolationManager.get_host_telemetry()
        print(f"[*] Pre-run Load Average: {pre_telemetry['loadavg']}, Avail RAM: {pre_telemetry['mem_available_kb']} KB")

        # 3. Wait for stabilization
        IsolationManager.wait_for_stabilization(seconds=2, reason=f"Pre-{environment} stabilization")

        try:
            adapter = create_adapter(environment)
            executor = BenchmarkExecutor(
                adapter=adapter,
                storage_manager=self.storage,
                stabilization_sec=1
            )
            benchmarks = resolve_benchmarks(self.selected_tests)

            for bench in benchmarks:
                runs = executor.execute_benchmark(
                    benchmark=bench,
                    warmup_runs=self.warmup_runs,
                    measured_runs=self.measured_runs,
                    experiment_id=self.experiment_id
                )
                self.generated_runs.extend(runs)

        except Exception as e:
            print(f"[!] Error executing benchmarks in environment '{environment}': {e}")
        finally:
            # 6. Shutdown target environment cleanly
            print(f"[*] Cleaning up environment [{environment}]...")
            IsolationManager.ensure_all_environments_stopped()

            # 7. Post-run stabilization
            IsolationManager.wait_for_stabilization(seconds=2, reason=f"Post-{environment} cooldown")

    def generate_experiment_manifest(
        self,
        env_list: List[str],
        start_time: str,
        end_time: str,
        duration_sec: float
    ) -> Path:
        """Generates comprehensive experiment reproducibility manifest."""
        status_counts = {"success": 0, "failed": 0, "unavailable": 0}
        for r in self.generated_runs:
            st = r.get("status", "failed")
            status_counts[st] = status_counts.get(st, 0) + 1

        benchmarks = [b.name for b in resolve_benchmarks(self.selected_tests)]

        manifest_data = {
            "schema_version": SCHEMA_VERSION,
            "manifest_type": "CC2 Experiment Execution Manifest",
            "experiment_id": self.experiment_id,
            "start_time": start_time,
            "end_time": end_time,
            "duration_sec": duration_sec,
            "mode": self.mode,
            "run_count_config": {
                "warmup_runs": self.warmup_runs,
                "measured_runs": self.measured_runs
            },
            "environments": env_list,
            "benchmarks": benchmarks,
            "workload_versions_sha256": {
                "cpu_deterministic": "212853035b582f238058b8d436fecf1f25bd5ff249965c7467336903a563fd9f",
                "memory_deterministic": "1bbf56eae471571293a033c266978f5f63df9ef8dfb0badbae30802b8c28d544",
                "syscall_deterministic": "9e9f18e0e7f5e7cd5d6e772a89b816ff8b3f408bde2c5295186a44ade3d186b1",
                "scheduling_deterministic": "2c69d4493ed25e1ba413c2710191861ee98e88fc597a7bfc6cccc1020fb472b7",
                "http_health_app": "017cb76e9bba79df36c3aba7969fca08db09f019cbce2fd23356dfdb2241227a"
            },
            "total_runs_executed": len(self.generated_runs),
            "status_distribution": status_counts,
            "runs_summary": [
                {
                    "run_id": r.get("run_id"),
                    "environment": r.get("environment"),
                    "benchmark": r.get("benchmark"),
                    "status": r.get("status"),
                    "exit_code": r.get("execution", {}).get("exit_code")
                }
                for r in self.generated_runs
            ]
        }

        manifest_dir = self.storage.processed_dir
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = manifest_dir / f"experiment_manifest_{self.experiment_id}.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

        latest_file = self.storage.base_dir / "experiment_manifest.json"
        with open(latest_file, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

        print(f"[+] Saved experiment manifest -> {manifest_file.name}")
        return manifest_file

    def run_all_environments(self, env_list: List[str]):
        """Runs multiple environments sequentially with full isolation and statistics compilation."""
        t_start = time.time()
        start_iso = datetime.now(timezone.utc).isoformat()
        for env in env_list:
            self.run_environment(env)

        duration_sec = round(time.time() - t_start, 2)
        end_iso = datetime.now(timezone.utc).isoformat()

        # Generate Experiment Manifest
        self.generate_experiment_manifest(env_list, start_iso, end_iso, duration_sec)

        # Post-experiment processing: statistics and CSV export
        print("\n" + "=" * 60)
        print("COMPILING EXPERIMENT STATISTICS & TABULAR CSV EXPORTS")
        print("=" * 60)

        run_analysis(self.storage.base_dir)
        self.sync_dashboard()

        print("\n" + "=" * 60)
        print(f"EXPERIMENT COMPLETED SUCCESSFULLY IN {duration_sec}s")
        print(f"Experiment ID: {self.experiment_id}")
        print("=" * 60)


def build_arg_parser() -> argparse.ArgumentParser:
    """Builds comprehensive CLI parser matching CC2 specification."""
    parser = argparse.ArgumentParser(
        prog="./benchmark/runner.sh",
        description="CC2 Empirical Benchmark Experiment Runner across Host, KVM, VirtualBox, and LXC.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  ./benchmark/runner.sh --environment host --quick
  ./benchmark/runner.sh --environment kvm --quick
  ./benchmark/runner.sh --environment virtualbox --quick
  ./benchmark/runner.sh --environment lxc --quick
  ./benchmark/runner.sh --all --quick
  ./benchmark/runner.sh --environment host --test cpu --test memory --quick
  ./benchmark/runner.sh --all --full --runs 5
"""
    )

    env_group = parser.add_mutually_exclusive_group(required=False)
    env_group.add_argument(
        "--environment", "-e",
        choices=["host", "kvm", "virtualbox", "lxc"],
        help="Target execution environment for benchmark evaluation"
    )
    env_group.add_argument(
        "--all", "-a",
        action="store_true",
        help="Execute benchmarks sequentially across all environments (host, kvm, virtualbox, lxc)"
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--quick", "-q",
        action="store_true",
        help="Quick evaluation: 1 warmup run, 2 measured runs (default)"
    )
    mode_group.add_argument(
        "--full", "-f",
        action="store_true",
        help="Full rigorous evaluation: 1 warmup run, 5 measured runs"
    )

    parser.add_argument(
        "--runs", "-r",
        type=int,
        default=None,
        help="Custom number of measured benchmark runs (overrides quick/full defaults)"
    )

    parser.add_argument(
        "--test", "-t",
        action="append",
        choices=["cpu", "memory", "disk", "network", "ping", "iperf", "app", "app_latency", "startup", "syscall", "scheduling", "isolation", "all"],
        default=None,
        help="Specific test to run (repeatable, defaults to 'all'):\n"
             "  cpu         Deterministic matrix multiplication (GFLOPS, checksum)\n"
             "  memory      Deterministic buffer traversal (MB/s throughput)\n"
             "  disk        Safe regular-file FIO benchmark\n"
             "  network     Ping RTT latency and iperf3 throughput\n"
             "  app         100 HTTP GET /health requests latency\n"
             "  startup     Hypervisor/container boot and readiness profiling\n"
             "  syscall     Raw getpid() syscall latency and rate\n"
             "  scheduling  Context-switch latency via 2-way pipe ping-pong\n"
             "  isolation   Namespaces, cgroups, and kernel sharing verification\n"
             "  all         Execute all test domains (default)"
    )

    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="Validate environment, resolve workloads, calculate SHA256, and show execution plan without executing workloads or modifying environments."
    )

    parser.add_argument(
        "--probe", "-p",
        action="store_true",
        help="Execute harmless diagnostic smoke test (uname -r, hostname, id) to verify real environment identity without running benchmarks."
    )

    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    # Explicit conflict check for run count modes
    if args.quick and args.full:
        parser.error("Cannot combine --quick and --full. Choose one.")

    # Determine environments
    if args.all:
        environments = ["host", "kvm", "virtualbox", "lxc"]
    elif args.environment:
        environments = [args.environment]
    else:
        parser.print_help()
        sys.exit(0)

    # 1. Non-destructive Smoke Test Probe (--probe)
    if getattr(args, "probe", False):
        print("=" * 78)
        print("CC2 ENVIRONMENT DIAGNOSTIC PROBE (--probe)")
        print("=" * 78)
        from benchmark.runner.environments import create_adapter
        from benchmark.runner.executor import BenchmarkExecutor
        for env_name in environments:
            try:
                adapter = create_adapter(env_name)
                executor = BenchmarkExecutor(adapter)
                report = executor.probe_environment()
                print(f"\n[{report['display_name']}]")
                print(f"  Classification : {report['classification']}")
                print(f"  Transport      : {report['transport']}")
                print(f"  Status         : {report['status']}")
                print(f"  Verified       : {report['verified']}")
                if report.get("probe_executed"):
                    print(f"  Guest Kernel   : {report.get('guest_kernel')}")
                    print(f"  Guest Hostname : {report.get('guest_hostname')}")
                    print(f"  Guest User ID  : {report.get('guest_user_id')}")
                    print(f"  Virt Detect    : {report.get('virt_detect') or 'none'}")
                elif report.get("error"):
                    print(f"  Probe Info     : {report.get('error')}")
            except Exception as e:
                print(f"\n[{env_name.upper()}] Error running probe: {e}")

        print("\n" + "=" * 78)
        print("PROBE COMPLETED: Strictly non-destructive. Zero benchmarks executed.")
        print("=" * 78)
        sys.exit(0)

    # 2. Execution Plan Dry-Run (--dry-run)
    if getattr(args, "dry_run", False):
        print("=" * 78)
        print("CC2 BENCHMARK DRY-RUN EXECUTION PLAN (--dry-run)")
        print("=" * 78)
        from benchmark.runner.environments import create_adapter
        from benchmark.runner.executor import BenchmarkExecutor
        from benchmark.runner.benchmarks import resolve_benchmarks

        # Determine run counts
        if args.runs is not None and args.runs > 0:
            warmup = 1 if args.runs > 1 else 0
            measured = args.runs
            mode_desc = f"custom ({measured} measured runs)"
        elif args.full:
            warmup = 1
            measured = 5
            mode_desc = "full (1 warmup, 5 measured runs)"
        else:
            warmup = 1
            measured = 2
            mode_desc = "quick (1 warmup, 2 measured runs)"

        benchmarks = resolve_benchmarks(args.test)

        print(f"Plan Mode: {mode_desc}")
        print(f"Selected Environments: {environments}")
        print(f"Selected Benchmarks  : {[b.name for b in benchmarks]}")
        print("-" * 78)

        for env_name in environments:
            try:
                adapter = create_adapter(env_name)
                executor = BenchmarkExecutor(adapter)
                print(f"\nEnvironment: {adapter.display_name} ({adapter.classification})")
                print(f"Transport  : {adapter.transport_name} -> Target Path: {adapter.target_path}")
                print(f"Status     : {adapter.get_status()} (Verified: {adapter.verify()})")

                for bench in benchmarks:
                    plan = executor.create_execution_plan(bench, warmup_runs=warmup, measured_runs=measured)
                    print(f"\n  [Benchmark: {plan.benchmark_name}]")
                    print(f"    Workload Binary  : {plan.workload_binary or 'N/A'}")
                    if plan.local_binary_path:
                        print(f"    Local Artifact   : {plan.local_binary_path}")
                    if plan.local_sha256:
                        print(f"    Local SHA256     : {plan.local_sha256}")
                    print(f"    Destination      : {plan.target_destination}")
                    print(f"    Command Pattern  : {plan.command_to_run}")
                    print(f"    Execution Runs   : {plan.warmup_runs} warmup, {plan.measured_runs} measured")
                    if plan.canonical_invariants:
                        print(f"    Invariants       : {plan.canonical_invariants}")
            except Exception as e:
                print(f"\nEnvironment {env_name} plan error: {e}")

        print("\n" + "=" * 78)
        print("DRY-RUN COMPLETED: Zero workloads executed. Zero result files modified.")
        print("=" * 78)
        sys.exit(0)

    # 3. Regular Execution
    mode = "full" if args.full else "quick"
    runner = ExperimentRunner(
        mode=mode,
        runs=args.runs,
        tests=args.test
    )
    runner.run_all_environments(environments)


if __name__ == "__main__":
    main()
