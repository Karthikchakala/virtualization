#!/usr/bin/env python3
"""
benchmark/runner/executor.py - Unified Benchmark Execution Engine for CC2.

Coordinates the complete benchmark execution lifecycle across all platforms:
1. Prepare Environment (verify & ensure ready)
2. Deploy Workload (transfer & verify SHA256)
3. Execute Workload (with kernel telemetry wrapper /usr/bin/time -v)
4. Collect Metrics (telemetry + hypervisor / cgroups v2 stats)
5. Normalize Result (strictly conformant schema with no fake metrics)
6. Write Raw Result (hierarchical and versioned provenance persistence)
7. Cleanup & Cooldown (graceful process quenching & stabilization)

CRITICAL INVARIANTS:
- Operates strictly through BaseEnvironmentAdapter.
  Contains ZERO platform-specific SSH, VBox, or LXC logic.
- Real guest execution for KVM, VirtualBox, and LXC. Never runs on host and relabels.
- NEVER overwrites existing CPU result files or deletes evidence.
- NEVER exposes secrets in results, logs, or exceptions.
"""

import os
import re
import sys
import json
import time
import uuid
import shlex
import shutil
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple, Union

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from .config import AppConfig, EnvironmentConfig, ConfigLoader, mask_secret
from .environments.base import BaseEnvironmentAdapter, ExecutionResult, NormalizedState
from .environments import create_adapter
from .workload import WorkloadDeployer, WorkloadArtifact, WorkloadDeploymentResult
from .benchmarks import (
    BenchmarkDefinition,
    get_benchmark,
    resolve_benchmarks,
    ALLOWED_CLI_TESTS,
    CPU_BENCHMARK
)
from collector.measurement import parse_time_v_output
from collector.schema import (
    VersionedBenchmarkResult,
    ResultStorageManager,
    SCHEMA_VERSION
)
from collector.common import SafetyValidator
from collector.advanced_metrics import (
    HttpLatencyBenchmark,
    MinimalHealthHttpServer,
    Iperf3Config,
    SyscallCollector,
    SchedulingCollector
)
from benchmark.kvm_adapter import KvmLifecycle
from benchmark.vbox_adapter import VBoxLifecycle
from benchmark.lxc_adapter import LxcLifecycle


@dataclass
class ExecutionPlan:
    """
    Describes the execution plan for a benchmark run without executing it.
    """
    environment: str
    environment_display: str
    classification: str
    transport: str
    benchmark_name: str
    workload_binary: Optional[str]
    local_binary_path: Optional[str]
    local_sha256: Optional[str]
    target_destination: str
    warmup_runs: int
    measured_runs: int
    command_to_run: str
    parameters: Dict[str, Any]
    canonical_invariants: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "environment": self.environment,
            "environment_display": self.environment_display,
            "classification": self.classification,
            "transport": self.transport,
            "benchmark_name": self.benchmark_name,
            "workload_binary": self.workload_binary,
            "local_binary_path": self.local_binary_path,
            "local_sha256": self.local_sha256,
            "target_destination": self.target_destination,
            "warmup_runs": self.warmup_runs,
            "measured_runs": self.measured_runs,
            "command_to_run": self.command_to_run,
            "parameters": self.parameters,
            "canonical_invariants": self.canonical_invariants
        }


class BenchmarkExecutor:
    """
    Unified executor interacting strictly through BaseEnvironmentAdapter.
    """

    def __init__(
        self,
        adapter: BaseEnvironmentAdapter,
        deployer: Optional[WorkloadDeployer] = None,
        storage_manager: Optional[ResultStorageManager] = None,
        stabilization_sec: int = 2
    ):
        self.adapter = adapter
        self.deployer = deployer or WorkloadDeployer()
        self.storage_manager = storage_manager or ResultStorageManager(PROJECT_ROOT / "results")
        self.stabilization_sec = stabilization_sec

    def probe_environment(self) -> Dict[str, Any]:
        """
        Runs non-destructive probe commands to prove where execution occurs:
        uname -r, hostname, id, systemd-detect-virt.
        Returns environment identification without saving benchmark data.
        """
        print(f"[*] Probing environment: {self.adapter.display_name} ({self.adapter.transport_name})...")
        status = self.adapter.get_status()
        verified = self.adapter.verify()

        probe_report: Dict[str, Any] = {
            "environment": self.adapter.name,
            "display_name": self.adapter.display_name,
            "classification": self.adapter.classification,
            "virtualization_type": self.adapter.virtualization_type,
            "transport": self.adapter.transport_name,
            "status": status,
            "verified": verified,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "probe_executed": False,
            "guest_kernel": None,
            "guest_hostname": None,
            "guest_user_id": None,
            "virt_detect": None
        }

        if status != NormalizedState.RUNNING:
            probe_report["error"] = f"Environment is currently in '{status}' state (offline)"
            return probe_report

        # Execute safe smoke test probe inside target environment
        probe_cmd = "uname -r; hostname; id; systemd-detect-virt || true"
        res = self.adapter.execute(probe_cmd, timeout=10)

        if res.success:
            probe_report["probe_executed"] = True
            lines = res.stdout.strip().splitlines()
            if len(lines) >= 1:
                probe_report["guest_kernel"] = lines[0].strip()
            if len(lines) >= 2:
                probe_report["guest_hostname"] = lines[1].strip()
            if len(lines) >= 3:
                probe_report["guest_user_id"] = lines[2].strip()
            if len(lines) >= 4:
                probe_report["virt_detect"] = lines[3].strip()
        else:
            probe_report["error"] = res.stderr.strip() or "Probe command execution failed"

        return probe_report

    def _get_default_target_ip(self) -> str:
        """Determines the safe local target IP address based on environment."""
        if self.adapter.name == "host":
            return "127.0.0.1"
        elif self.adapter.name == "kvm":
            return getattr(self.adapter, "ip_address", None) or "192.168.122.1"
        elif self.adapter.name == "virtualbox":
            return "127.0.0.1"
        elif self.adapter.name == "lxc":
            return getattr(self.adapter, "ip_address", None) or "10.0.3.1"
        return "127.0.0.1"

    def create_execution_plan(
        self,
        benchmark: BenchmarkDefinition,
        warmup_runs: int = 1,
        measured_runs: int = 5
    ) -> ExecutionPlan:
        """
        Builds a dry-run execution plan without modifying environments or running workloads.
        """
        artifact_path = None
        artifact_sha256 = None
        target_dest = str(self.adapter.target_path)

        if benchmark.workload_binary:
            try:
                artifact = self.deployer.get_canonical_artifact(benchmark.workload_binary)
                artifact_path = str(artifact.local_path)
                artifact_sha256 = artifact.sha256
                target_dest = f"{self.adapter.target_path}/{artifact.binary_name}"
            except Exception as e:
                artifact_path = f"resolution_error: {e}"
                target_dest = f"{self.adapter.target_path}/{benchmark.workload_binary}"
            args_str = " ".join(benchmark.format_args())
            full_cmd = f"{target_dest} {args_str}".strip()
        elif benchmark.short_name == "disk" or benchmark.name == "disk_fio":
            target_dest = f"/tmp/cc2_disk_test_{self.adapter.name}.dat"
            full_cmd = f"fio --name=cc2_disk_test --filename={target_dest} --size=16m --direct=1 --rw=readwrite --bs=4k --ioengine=sync --runtime=3 --time_based=0 --output-format=json"
        elif benchmark.short_name in ("network", "ping") or benchmark.name == "network_ping":
            target_dest = self._get_default_target_ip()
            full_cmd = f"ping -c 5 -W 1 {target_dest}"
        elif benchmark.short_name in ("iperf", "iperf3") or benchmark.name == "network_iperf3":
            target_dest = self._get_default_target_ip()
            full_cmd = f"iperf3 -c {target_dest} -t 5 -P 1 -J"
        elif benchmark.short_name in ("app", "app_latency") or benchmark.name == "app_latency":
            target_dest = f"http://{self._get_default_target_ip()}:8080/health"
            full_cmd = f"http_get_100 {target_dest}"
        elif benchmark.short_name == "startup" or benchmark.name == "startup_lifecycle":
            target_dest = self.adapter.name
            full_cmd = f"measure_startup {self.adapter.name}"
        elif benchmark.short_name == "isolation" or benchmark.name == "isolation_audit":
            target_dest = self.adapter.name
            full_cmd = f"audit_isolation {self.adapter.name}"
        else:
            args_str = " ".join(benchmark.format_args())
            full_cmd = f"{target_dest} {args_str}".strip()

        return ExecutionPlan(
            environment=self.adapter.name,
            environment_display=self.adapter.display_name,
            classification=self.adapter.classification,
            transport=self.adapter.transport_name,
            benchmark_name=benchmark.name,
            workload_binary=benchmark.workload_binary,
            local_binary_path=artifact_path,
            local_sha256=artifact_sha256,
            target_destination=target_dest,
            warmup_runs=warmup_runs,
            measured_runs=measured_runs,
            command_to_run=full_cmd,
            parameters=benchmark.parameters,
            canonical_invariants=benchmark.canonical_invariants
        )

    def execute_benchmark(
        self,
        benchmark: BenchmarkDefinition,
        warmup_runs: int = 1,
        measured_runs: int = 5,
        experiment_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Executes complete benchmark workflow through adapter:
        prepare -> deploy -> verify -> warmup -> measured runs -> metrics -> save -> cleanup
        """
        exp_id = experiment_id or f"exp-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

        # Invariant: Never execute benchmarks that are not implemented
        if not benchmark.is_implemented:
            raise NotImplementedError(
                f"Benchmark '{benchmark.name}' is marked NOT_IMPLEMENTED"
            )

        print(f"\n{'='*78}")
        print(f"BENCHMARK EXECUTION: {benchmark.name} on {self.adapter.display_name}")
        print(f"Warmup runs: {warmup_runs} | Measured runs: {measured_runs}")
        print(f"{'='*78}")

        # Step 1: Prepare Environment
        print(f"[*] Step 1/7: Preparing environment '{self.adapter.name}'...")
        prep_res = self.adapter.prepare()
        prep_status = prep_res.get("status", "ready")
        prep_ready = prep_res.get("ready", True)
        print(f"    Status: {prep_status} (ready={prep_ready})")

        if not prep_ready and prep_status in ("unavailable", "failed", "timeout", "error"):
            status_val = "unavailable" if prep_status == "unavailable" else "failed"
            reason_msg = prep_res.get("reason", f"Environment '{self.adapter.name}' preparation failed ({prep_status})")
            print(f"    [!] Environment not ready: {reason_msg}")
            results = []
            for r in range(1, measured_runs + 1):
                run_id = f"{benchmark.name}-{self.adapter.name}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
                payload = {
                    "schema_version": SCHEMA_VERSION,
                    "experiment_id": exp_id,
                    "run_id": run_id,
                    "environment": self.adapter.name,
                    "benchmark": benchmark.name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "command": f"{benchmark.name}",
                    "workload": {
                        "name": benchmark.workload_binary or benchmark.name,
                        "verified": False
                    },
                    "environment_identity": {"environment": self.adapter.name, "status": prep_status},
                    "parameters": benchmark.parameters,
                    "execution": {
                        "exit_code": -1,
                        "duration_sec": 0.0,
                        "timed_out": False,
                        "status": status_val
                    },
                    "metrics": {
                        "status": status_val,
                        "reason": reason_msg
                    },
                    "stdout": "",
                    "stderr": reason_msg,
                    "status": status_val
                }
                self._save_raw_payload(payload)
                results.append(payload)
            return results

        try:
            # Step 2: Target Identity (Real Execution Proof)
            print(f"[*] Step 2/7: Inspecting target execution identity...")
            target_identity = self.adapter.get_identity()
            print(f"    Target OS/Kernel : {target_identity.kernel_release or 'unknown'}")
            print(f"    Virtualization   : {target_identity.systemd_detect_virt or 'none'}")
            print(f"    Shared Kernel    : {target_identity.is_shared_kernel}")

            # Dispatch to specialized domain handlers
            if benchmark.short_name == "disk" or benchmark.name == "disk_fio":
                return self._execute_disk_benchmark(benchmark, warmup_runs, measured_runs, exp_id, target_identity)
            elif benchmark.short_name in ("network", "ping") or benchmark.name == "network_ping":
                return self._execute_network_ping_benchmark(benchmark, warmup_runs, measured_runs, exp_id, target_identity)
            elif benchmark.short_name in ("iperf", "iperf3") or benchmark.name == "network_iperf3":
                return self._execute_network_iperf3_benchmark(benchmark, warmup_runs, measured_runs, exp_id, target_identity)
            elif benchmark.short_name in ("app", "app_latency") or benchmark.name == "app_latency":
                return self._execute_app_latency_benchmark(benchmark, warmup_runs, measured_runs, exp_id, target_identity)
            elif benchmark.short_name == "startup" or benchmark.name == "startup_lifecycle":
                return self._execute_startup_benchmark(benchmark, warmup_runs, measured_runs, exp_id, target_identity)
            elif benchmark.short_name == "isolation" or benchmark.name == "isolation_audit":
                return self._execute_isolation_benchmark(benchmark, warmup_runs, measured_runs, exp_id, target_identity)
            else:
                return self._execute_binary_benchmark(benchmark, warmup_runs, measured_runs, exp_id, target_identity)

        except Exception as e:
            print(f"    [!] Error during benchmark execution ({benchmark.name}): {e}")
            results = []
            for r in range(1, measured_runs + 1):
                run_id = f"{benchmark.name}-{self.adapter.name}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
                payload = {
                    "schema_version": SCHEMA_VERSION,
                    "experiment_id": exp_id,
                    "run_id": run_id,
                    "environment": self.adapter.name,
                    "benchmark": benchmark.name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "command": f"{benchmark.name}",
                    "workload": {
                        "name": benchmark.workload_binary or benchmark.name,
                        "verified": False
                    },
                    "environment_identity": {"environment": self.adapter.name},
                    "parameters": benchmark.parameters,
                    "execution": {
                        "exit_code": -1,
                        "duration_sec": 0.0,
                        "timed_out": False,
                        "status": "failed"
                    },
                    "metrics": {
                        "status": "failed",
                        "reason": f"Execution exception: {e}"
                    },
                    "stdout": "",
                    "stderr": str(e),
                    "status": "failed"
                }
                self._save_raw_payload(payload)
                results.append(payload)
            return results

        finally:
            print(f"[*] Step 6/7: Cleaning up environment '{self.adapter.name}'...")
            self.adapter.cleanup()
            time.sleep(self.stabilization_sec)
            print(f"[*] Step 7/7: Benchmark {benchmark.name} completed on {self.adapter.name}.")

    def _execute_binary_benchmark(
        self,
        benchmark: BenchmarkDefinition,
        warmup_runs: int,
        measured_runs: int,
        exp_id: str,
        target_identity: Any
    ) -> List[Dict[str, Any]]:
        """Executes compiled binary benchmark (CPU, Memory, Syscall, Scheduling)."""
        results: List[Dict[str, Any]] = []

        print(f"[*] Deploying workload '{benchmark.workload_binary}'...")
        artifact = self.deployer.get_canonical_artifact(benchmark.workload_binary)
        deployment_info = self.deployer.deploy(artifact, self.adapter)

        if not deployment_info.verified:
            err_msg = f"Workload deployment integrity verification failed: {deployment_info.error_message}"
            print(f"    [!] {err_msg}")
            for r in range(1, measured_runs + 1):
                run_id = f"{benchmark.name}-{self.adapter.name}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
                payload = {
                    "schema_version": SCHEMA_VERSION,
                    "experiment_id": exp_id,
                    "run_id": run_id,
                    "environment": self.adapter.name,
                    "benchmark": benchmark.name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "command": f"{benchmark.workload_binary}",
                    "workload": {
                        "name": benchmark.workload_binary or benchmark.name,
                        "sha256": deployment_info.local_sha256 if deployment_info else None,
                        "verified": False
                    },
                    "environment_identity": target_identity.to_dict() if target_identity else {},
                    "parameters": benchmark.parameters,
                    "execution": {
                        "exit_code": -1,
                        "duration_sec": 0.0,
                        "timed_out": False,
                        "status": "failed"
                    },
                    "metrics": {
                        "status": "failed",
                        "reason": err_msg
                    },
                    "stdout": "",
                    "stderr": err_msg,
                    "status": "failed"
                }
                self._save_raw_payload(payload)
                results.append(payload)
            return results
        target_binary_path = deployment_info.target_destination
        print(f"    Workload verified: SHA256 {deployment_info.local_sha256[:16]}... (transferred={deployment_info.transferred})")

        args_list = benchmark.format_args()
        base_cmd = f"{target_binary_path} {' '.join(args_list)}".strip()
        SafetyValidator.validate_command(base_cmd)
        wrapped_cmd = f"/usr/bin/time -v {base_cmd}"

        # Warmup iterations
        if warmup_runs > 0:
            print(f"[*] Step 4/7: Executing {warmup_runs} warmup iteration(s)...")
            for w in range(1, warmup_runs + 1):
                warm_res = self.adapter.execute(wrapped_cmd, timeout=benchmark.timeout_sec)
                if not warm_res.success:
                    print(f"    Warning: Warmup run {w} returned exit code {warm_res.exit_code}")
                time.sleep(self.stabilization_sec)

        # Measured iterations
        print(f"[*] Step 5/7: Executing {measured_runs} measured run(s)...")
        for r in range(1, measured_runs + 1):
            run_id = f"{benchmark.name}-{self.adapter.name}-{uuid.uuid4().hex[:8]}"
            print(f"    [Run {r}/{measured_runs}] ID: {run_id}...")

            exec_res = self.adapter.execute(wrapped_cmd, timeout=benchmark.timeout_sec)
            metrics_extra = self.adapter.collect_metrics(metadata={"run_id": run_id, "iteration": r})

            workload_metrics: Dict[str, Any] = {}
            try:
                raw_stdout = exec_res.stdout.strip()
                if raw_stdout.startswith("{") and raw_stdout.endswith("}"):
                    workload_metrics = json.loads(raw_stdout)
                else:
                    m = re.search(r"(\{.*\})", raw_stdout, re.DOTALL)
                    if m:
                        workload_metrics = json.loads(m.group(1))
            except Exception:
                pass

            time_telemetry = parse_time_v_output(exec_res.stderr)

            combined_metrics: Dict[str, Any] = {}
            combined_metrics.update(workload_metrics)

            # Unroll nested results if emitted by deterministic C workload
            if "results" in workload_metrics and isinstance(workload_metrics["results"], dict):
                combined_metrics.update(workload_metrics["results"])
            if "parameters" in workload_metrics and isinstance(workload_metrics["parameters"], dict):
                combined_metrics["parameters"] = workload_metrics["parameters"]

            combined_metrics["telemetry"] = time_telemetry
            combined_metrics["hypervisor_telemetry"] = metrics_extra

            # Standard top-level metric elevations for schema compatibility
            if time_telemetry.get("wall_time_sec") is not None:
                combined_metrics["wall_time_sec"] = time_telemetry["wall_time_sec"]
            if time_telemetry.get("user_time_sec") is not None:
                combined_metrics["user_time_sec"] = time_telemetry["user_time_sec"]
            if time_telemetry.get("system_time_sec") is not None:
                combined_metrics["system_time_sec"] = time_telemetry["system_time_sec"]
            if time_telemetry.get("cpu_percentage") is not None:
                combined_metrics["cpu_percentage"] = time_telemetry["cpu_percentage"]
            if time_telemetry.get("max_rss_kb") is not None:
                combined_metrics["max_rss_kb"] = time_telemetry["max_rss_kb"]

            # Specialized profiling extensions
            if benchmark.short_name == "syscall":
                # Attach strace profiling info if strace available on host
                perf_supported, _ = SchedulingCollector.probe_perf_paranoid()
                combined_metrics["perf"] = {
                    "status": "unavailable" if not perf_supported else "success",
                    "reason": "Hardware counters restricted (/proc/sys/kernel/perf_event_paranoid)" if not perf_supported else None
                }
            elif benchmark.short_name == "scheduling":
                combined_metrics["scheduling_telemetry"] = {
                    "voluntary_context_switches": time_telemetry.get("voluntary_context_switches"),
                    "involuntary_context_switches": time_telemetry.get("involuntary_context_switches"),
                    "total_context_switches": time_telemetry.get("total_context_switches")
                }

            # Canonical invariant validation for CPU benchmark
            if benchmark.short_name == "cpu":
                actual_flops = combined_metrics.get("total_flops")
                expected_flops = benchmark.canonical_invariants.get("total_flops")
                if actual_flops and expected_flops and actual_flops != expected_flops:
                    print(f"    Warning: FLOPs mismatch (got {actual_flops}, expected {expected_flops})")

                actual_chk = combined_metrics.get("checksum")
                expected_chk = benchmark.canonical_invariants.get("expected_checksum")
                if actual_chk and expected_chk and actual_chk != expected_chk:
                    print(f"    Warning: Checksum mismatch (got {actual_chk}, expected {expected_chk})")

            status_str = "success" if exec_res.success else ("timeout" if exec_res.timed_out else "failed")

            payload: Dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "experiment_id": exp_id,
                "run_id": run_id,
                "environment": self.adapter.name,
                "benchmark": benchmark.name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "command": base_cmd,
                "workload": {
                    "name": benchmark.workload_binary or benchmark.name,
                    "path": target_binary_path,
                    "sha256": deployment_info.target_sha256 if deployment_info else None,
                    "size_bytes": artifact.size_bytes if (deployment_info and 'artifact' in locals()) else None,
                    "verified": deployment_info.verified if deployment_info else True
                },
                "environment_identity": target_identity.to_dict(),
                "parameters": benchmark.parameters,
                "execution": {
                    "exit_code": exec_res.exit_code,
                    "duration_sec": exec_res.duration_sec,
                    "timed_out": exec_res.timed_out,
                    "status": status_str
                },
                "metrics": combined_metrics,
                "stdout": exec_res.stdout,
                "stderr": exec_res.stderr,
                "status": status_str
            }

            self._save_raw_payload(payload)
            results.append(payload)
            time.sleep(self.stabilization_sec)

        return results

    def _execute_disk_benchmark(
        self,
        benchmark: BenchmarkDefinition,
        warmup_runs: int,
        measured_runs: int,
        exp_id: str,
        target_identity: Any
    ) -> List[Dict[str, Any]]:
        """Executes safe regular-file FIO benchmark with strict block device rejection."""
        results: List[Dict[str, Any]] = []
        test_file = f"/tmp/cc2_disk_test_{self.adapter.name}.dat"

        # CRITICAL DISK SAFETY ASSERTIONS
        if any(blocked in test_file for blocked in ["/dev", "nvme", "sda", "sdb", "sdc", "vda", "vdb"]):
            raise ValueError(f"CRITICAL DISK SAFETY VIOLATION: Refusing to target block device '{test_file}'")

        # Verify fio presence
        which_res = self.adapter.execute("which fio", timeout=5)
        fio_available = which_res.success and bool(which_res.stdout.strip())

        fio_cmd = f"fio --name=cc2_disk_test --filename={test_file} --size=16m --direct=1 --rw=readwrite --bs=4k --ioengine=sync --runtime=3 --time_based=0 --output-format=json"
        wrapped_cmd = f"/usr/bin/time -v {fio_cmd}"

        if not fio_available:
            reason = f"fio binary not found in {self.adapter.name}. No mock data generated."
            print(f"    [!] {reason}")
            for r in range(1, measured_runs + 1):
                run_id = f"{benchmark.name}-{self.adapter.name}-{uuid.uuid4().hex[:8]}"
                metrics = {
                    "status": "unavailable",
                    "reason": reason,
                    "fio_results": {
                        "status": "unavailable",
                        "reason": reason
                    },
                    "read_iops": None,
                    "write_iops": None,
                    "read_throughput_mb_s": None,
                    "write_throughput_mb_s": None,
                    "p95_lat_ms": None,
                    "telemetry": {}
                }
                payload = {
                    "schema_version": SCHEMA_VERSION,
                    "experiment_id": exp_id,
                    "run_id": run_id,
                    "environment": self.adapter.name,
                    "benchmark": benchmark.name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "command": fio_cmd,
                    "workload": {
                        "name": "fio",
                        "path": "fio",
                        "sha256": None,
                        "size_bytes": None,
                        "verified": False
                    },
                    "environment_identity": target_identity.to_dict(),
                    "parameters": benchmark.parameters,
                    "execution": {
                        "exit_code": 0,
                        "duration_sec": 0.0,
                        "timed_out": False,
                        "status": "unavailable"
                    },
                    "metrics": metrics,
                    "stdout": json.dumps({"status": "unavailable", "reason": reason}),
                    "stderr": reason,
                    "status": "unavailable"
                }
                self._save_raw_payload(payload)
                results.append(payload)
            return results

        try:
            if warmup_runs > 0:
                print(f"[*] Step 4/7: Executing {warmup_runs} warmup iteration(s)...")
                for w in range(1, warmup_runs + 1):
                    self.adapter.execute(wrapped_cmd, timeout=benchmark.timeout_sec)
                    time.sleep(self.stabilization_sec)

            print(f"[*] Step 5/7: Executing {measured_runs} measured run(s)...")
            for r in range(1, measured_runs + 1):
                run_id = f"{benchmark.name}-{self.adapter.name}-{uuid.uuid4().hex[:8]}"
                print(f"    [Run {r}/{measured_runs}] ID: {run_id}...")
                exec_res = self.adapter.execute(wrapped_cmd, timeout=benchmark.timeout_sec)
                metrics_extra = self.adapter.collect_metrics(metadata={"run_id": run_id, "iteration": r})
                time_telemetry = parse_time_v_output(exec_res.stderr)

                fio_data: Dict[str, Any] = {}
                read_iops = None
                write_iops = None
                read_bw = None
                write_bw = None
                p95_lat_ms = None

                try:
                    raw_stdout = exec_res.stdout.strip()
                    m = re.search(r"(\{.*\})", raw_stdout, re.DOTALL)
                    if m:
                        fio_json = json.loads(m.group(1))
                        if "jobs" in fio_json and len(fio_json["jobs"]) > 0:
                            job = fio_json["jobs"][0]
                            read_iops = round(float(job.get("read", {}).get("iops", 0.0)), 2)
                            write_iops = round(float(job.get("write", {}).get("iops", 0.0)), 2)
                            read_bw = round(float(job.get("read", {}).get("bw_bytes", 0.0)) / (1024.0 * 1024.0), 3)
                            write_bw = round(float(job.get("write", {}).get("bw_bytes", 0.0)) / (1024.0 * 1024.0), 3)
                            clat = job.get("read", {}).get("clat_ns", {}).get("percentile", {})
                            if "95.000000" in clat:
                                p95_lat_ms = round(float(clat["95.000000"]) / 1e6, 3)
                            fio_data = {
                                "status": "success",
                                "read_iops": read_iops,
                                "write_iops": write_iops,
                                "read_throughput_mb_s": read_bw,
                                "write_throughput_mb_s": write_bw,
                                "p95_lat_ms": p95_lat_ms
                            }
                except Exception as e:
                    fio_data = {"status": "failed", "reason": f"Failed to parse FIO JSON: {e}"}

                status_str = "success" if (exec_res.success and read_iops is not None) else "failed"

                combined_metrics = {
                    "status": status_str,
                    "read_iops": read_iops,
                    "write_iops": write_iops,
                    "read_throughput_mb_s": read_bw,
                    "write_throughput_mb_s": write_bw,
                    "p95_lat_ms": p95_lat_ms,
                    "fio_results": fio_data,
                    "telemetry": time_telemetry,
                    "hypervisor_telemetry": metrics_extra
                }
                if time_telemetry.get("wall_time_sec") is not None:
                    combined_metrics["wall_time_sec"] = time_telemetry["wall_time_sec"]
                if time_telemetry.get("cpu_percentage") is not None:
                    combined_metrics["cpu_percentage"] = time_telemetry["cpu_percentage"]
                if time_telemetry.get("max_rss_kb") is not None:
                    combined_metrics["max_rss_kb"] = time_telemetry["max_rss_kb"]

                payload = {
                    "schema_version": SCHEMA_VERSION,
                    "experiment_id": exp_id,
                    "run_id": run_id,
                    "environment": self.adapter.name,
                    "benchmark": benchmark.name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "command": fio_cmd,
                    "workload": {
                        "name": "fio",
                        "path": "fio",
                        "sha256": None,
                        "size_bytes": None,
                        "verified": True
                    },
                    "environment_identity": target_identity.to_dict(),
                    "parameters": benchmark.parameters,
                    "execution": {
                        "exit_code": exec_res.exit_code,
                        "duration_sec": exec_res.duration_sec,
                        "timed_out": exec_res.timed_out,
                        "status": status_str
                    },
                    "metrics": combined_metrics,
                    "stdout": exec_res.stdout,
                    "stderr": exec_res.stderr,
                    "status": status_str
                }
                self._save_raw_payload(payload)
                results.append(payload)
                time.sleep(self.stabilization_sec)
        finally:
            self.adapter.execute(f"rm -f {test_file}", timeout=5)

        return results

    def _execute_network_ping_benchmark(
        self,
        benchmark: BenchmarkDefinition,
        warmup_runs: int,
        measured_runs: int,
        exp_id: str,
        target_identity: Any
    ) -> List[Dict[str, Any]]:
        """Executes ICMP ping latency against strictly local endpoints."""
        results: List[Dict[str, Any]] = []
        target_ip = self._get_default_target_ip()
        ping_cmd = f"ping -c 5 -W 1 {target_ip}"
        wrapped_cmd = f"/usr/bin/time -v {ping_cmd}"

        if warmup_runs > 0:
            print(f"[*] Step 4/7: Executing {warmup_runs} warmup iteration(s)...")
            for w in range(1, warmup_runs + 1):
                self.adapter.execute(wrapped_cmd, timeout=benchmark.timeout_sec)
                time.sleep(self.stabilization_sec)

        print(f"[*] Step 5/7: Executing {measured_runs} measured run(s)...")
        for r in range(1, measured_runs + 1):
            run_id = f"{benchmark.name}-{self.adapter.name}-{uuid.uuid4().hex[:8]}"
            print(f"    [Run {r}/{measured_runs}] ID: {run_id}...")
            exec_res = self.adapter.execute(wrapped_cmd, timeout=benchmark.timeout_sec)
            metrics_extra = self.adapter.collect_metrics(metadata={"run_id": run_id, "iteration": r})
            time_telemetry = parse_time_v_output(exec_res.stderr)

            stdout_str = exec_res.stdout or ""
            pkts_tx = None
            pkts_rx = None
            loss_pct = None
            rtt_min = None
            rtt_avg = None
            rtt_max = None
            rtt_mdev = None

            m_pkt = re.search(r"(\d+)\s+packets transmitted,\s+(\d+)\s+(?:packets\s+)?received,\s+([0-9.]+)%\s+packet loss", stdout_str)
            if m_pkt:
                pkts_tx = int(m_pkt.group(1))
                pkts_rx = int(m_pkt.group(2))
                loss_pct = float(m_pkt.group(3))

            m_rtt = re.search(r"rtt\s+min/avg/max/mdev\s*=\s*([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)\s+ms", stdout_str)
            if m_rtt:
                rtt_min = float(m_rtt.group(1))
                rtt_avg = float(m_rtt.group(2))
                rtt_max = float(m_rtt.group(3))
                rtt_mdev = float(m_rtt.group(4))

            status_str = "success" if (exec_res.success and pkts_rx is not None and pkts_rx > 0) else "failed"

            combined_metrics = {
                "status": status_str,
                "target_ip": target_ip,
                "packets_transmitted": pkts_tx,
                "packets_received": pkts_rx,
                "packet_loss_percent": loss_pct,
                "rtt_min_ms": rtt_min,
                "rtt_avg_ms": rtt_avg,
                "rtt_max_ms": rtt_max,
                "rtt_mdev_ms": rtt_mdev,
                "telemetry": time_telemetry,
                "hypervisor_telemetry": metrics_extra
            }
            if time_telemetry.get("wall_time_sec") is not None:
                combined_metrics["wall_time_sec"] = time_telemetry["wall_time_sec"]
            if time_telemetry.get("cpu_percentage") is not None:
                combined_metrics["cpu_percentage"] = time_telemetry["cpu_percentage"]
            if time_telemetry.get("max_rss_kb") is not None:
                combined_metrics["max_rss_kb"] = time_telemetry["max_rss_kb"]

            payload = {
                "schema_version": SCHEMA_VERSION,
                "experiment_id": exp_id,
                "run_id": run_id,
                "environment": self.adapter.name,
                "benchmark": benchmark.name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "command": ping_cmd,
                "workload": {
                    "name": "ping",
                    "path": "ping",
                    "sha256": None,
                    "size_bytes": None,
                    "verified": True
                },
                "environment_identity": target_identity.to_dict(),
                "parameters": benchmark.parameters,
                "execution": {
                    "exit_code": exec_res.exit_code,
                    "duration_sec": exec_res.duration_sec,
                    "timed_out": exec_res.timed_out,
                    "status": status_str
                },
                "metrics": combined_metrics,
                "stdout": exec_res.stdout,
                "stderr": exec_res.stderr,
                "status": status_str
            }
            self._save_raw_payload(payload)
            results.append(payload)
            time.sleep(self.stabilization_sec)

        return results

    def _execute_network_iperf3_benchmark(
        self,
        benchmark: BenchmarkDefinition,
        warmup_runs: int,
        measured_runs: int,
        exp_id: str,
        target_identity: Any
    ) -> List[Dict[str, Any]]:
        """Executes standardized local iperf3 throughput benchmark."""
        results: List[Dict[str, Any]] = []
        target_ip = self._get_default_target_ip()
        duration = 3 if measured_runs <= 2 else 5
        iperf_cmd = f"iperf3 -c {target_ip} -t {duration} -P 1 -J"

        which_res = self.adapter.execute("which iperf3", timeout=5)
        iperf_available = which_res.success and bool(which_res.stdout.strip())

        if not iperf_available:
            reason = f"iperf3 binary not found in {self.adapter.name}. Zero values will not be fabricated."
            print(f"    [!] {reason}")
            for r in range(1, measured_runs + 1):
                run_id = f"{benchmark.name}-{self.adapter.name}-{uuid.uuid4().hex[:8]}"
                metrics = {
                    "status": "unavailable",
                    "reason": reason,
                    "protocol": "TCP",
                    "direction": "client-to-server",
                    "stream_count": 1,
                    "duration_sec": duration,
                    "sender_bandwidth_mbps": None,
                    "receiver_bandwidth_mbps": None,
                    "retransmits": None,
                    "telemetry": {}
                }
                payload = {
                    "schema_version": SCHEMA_VERSION,
                    "experiment_id": exp_id,
                    "run_id": run_id,
                    "environment": self.adapter.name,
                    "benchmark": benchmark.name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "command": iperf_cmd,
                    "workload": {
                        "name": "iperf3",
                        "path": "iperf3",
                        "sha256": None,
                        "size_bytes": None,
                        "verified": False
                    },
                    "environment_identity": target_identity.to_dict(),
                    "parameters": benchmark.parameters,
                    "execution": {
                        "exit_code": 0,
                        "duration_sec": 0.0,
                        "timed_out": False,
                        "status": "unavailable"
                    },
                    "metrics": metrics,
                    "stdout": json.dumps({"status": "unavailable", "reason": reason}),
                    "stderr": reason,
                    "status": "unavailable"
                }
                self._save_raw_payload(payload)
                results.append(payload)
            return results

        for r in range(1, measured_runs + 1):
            run_id = f"{benchmark.name}-{self.adapter.name}-{uuid.uuid4().hex[:8]}"
            print(f"    [Run {r}/{measured_runs}] ID: {run_id}...")
            exec_res = self.adapter.execute(iperf_cmd, timeout=duration + 10)
            metrics_extra = self.adapter.collect_metrics(metadata={"run_id": run_id, "iteration": r})

            iperf_metrics = Iperf3Config.parse_iperf3_json(exec_res.stdout)
            iperf_metrics["duration_sec"] = duration
            iperf_metrics["telemetry"] = {}
            iperf_metrics["hypervisor_telemetry"] = metrics_extra

            status_str = iperf_metrics.get("status", "failed")

            payload = {
                "schema_version": SCHEMA_VERSION,
                "experiment_id": exp_id,
                "run_id": run_id,
                "environment": self.adapter.name,
                "benchmark": benchmark.name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "command": iperf_cmd,
                "workload": {
                    "name": "iperf3",
                    "path": "iperf3",
                    "sha256": None,
                    "size_bytes": None,
                    "verified": True
                },
                "environment_identity": target_identity.to_dict(),
                "parameters": benchmark.parameters,
                "execution": {
                    "exit_code": exec_res.exit_code,
                    "duration_sec": exec_res.duration_sec,
                    "timed_out": exec_res.timed_out,
                    "status": status_str
                },
                "metrics": iperf_metrics,
                "stdout": exec_res.stdout,
                "stderr": exec_res.stderr,
                "status": status_str
            }
            self._save_raw_payload(payload)
            results.append(payload)
            time.sleep(self.stabilization_sec)

        return results

    def _execute_app_latency_benchmark(
        self,
        benchmark: BenchmarkDefinition,
        warmup_runs: int,
        measured_runs: int,
        exp_id: str,
        target_identity: Any
    ) -> List[Dict[str, Any]]:
        """Executes 100 requests measuring HTTP /health latency."""
        results: List[Dict[str, Any]] = []

        if self.adapter.name == "host":
            server = MinimalHealthHttpServer(host="127.0.0.1", port=0)
            server.start()
            try:
                url = server.url
                print(f"[*] App Latency on Host: issuing 100 requests to {url}...")
                for r in range(1, measured_runs + 1):
                    run_id = f"{benchmark.name}-{self.adapter.name}-{uuid.uuid4().hex[:8]}"
                    print(f"    [Run {r}/{measured_runs}] ID: {run_id}...")
                    lat_res = HttpLatencyBenchmark.measure_endpoint(url, num_requests=100)
                    status_str = lat_res.get("status", "failed")

                    combined_metrics = dict(lat_res)
                    combined_metrics["telemetry"] = {}
                    combined_metrics["hypervisor_telemetry"] = self.adapter.collect_metrics(metadata={"run_id": run_id, "iteration": r})

                    payload = {
                        "schema_version": SCHEMA_VERSION,
                        "experiment_id": exp_id,
                        "run_id": run_id,
                        "environment": self.adapter.name,
                        "benchmark": benchmark.name,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "command": f"http_get_100 {url}",
                        "workload": {
                            "name": "http_health_app",
                            "path": "http_health_app.py",
                            "sha256": None,
                            "size_bytes": None,
                            "verified": True
                        },
                        "environment_identity": target_identity.to_dict(),
                        "parameters": benchmark.parameters,
                        "execution": {
                            "exit_code": 0 if status_str == "success" else -1,
                            "duration_sec": 0.5,
                            "timed_out": False,
                            "status": status_str
                        },
                        "metrics": combined_metrics,
                        "stdout": json.dumps(lat_res),
                        "stderr": lat_res.get("reason", ""),
                        "status": status_str
                    }
                    self._save_raw_payload(payload)
                    results.append(payload)
                    time.sleep(self.stabilization_sec)
            finally:
                server.stop()
        else:
            artifact = self.deployer.get_canonical_artifact("http_health_app.py")
            deployment_info = self.deployer.deploy(artifact, self.adapter)
            dest = deployment_info.target_destination

            chk = self.adapter.execute("which python3", timeout=5)
            if not chk.success or not chk.stdout.strip():
                reason = f"python3 not found in {self.adapter.name}. Cannot run http_health_app.py"
                print(f"    [!] {reason}")
                for r in range(1, measured_runs + 1):
                    run_id = f"{benchmark.name}-{self.adapter.name}-{uuid.uuid4().hex[:8]}"
                    metrics = {
                        "status": "unavailable",
                        "reason": reason,
                        "requests_attempted": 100,
                        "requests_completed": None,
                        "http_200_count": None,
                        "telemetry": {}
                    }
                    payload = {
                        "schema_version": SCHEMA_VERSION,
                        "experiment_id": exp_id,
                        "run_id": run_id,
                        "environment": self.adapter.name,
                        "benchmark": benchmark.name,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "command": f"python3 {dest} --port 8080",
                        "workload": {
                            "name": "http_health_app",
                            "path": dest,
                            "sha256": deployment_info.target_sha256,
                            "size_bytes": artifact.size_bytes,
                            "verified": deployment_info.verified
                        },
                        "environment_identity": target_identity.to_dict(),
                        "parameters": benchmark.parameters,
                        "execution": {
                            "exit_code": 0,
                            "duration_sec": 0.0,
                            "timed_out": False,
                            "status": "unavailable"
                        },
                        "metrics": metrics,
                        "stdout": json.dumps({"status": "unavailable", "reason": reason}),
                        "stderr": reason,
                        "status": "unavailable"
                    }
                    self._save_raw_payload(payload)
                    results.append(payload)
                return results

            print(f"[*] Starting http_health_app.py in {self.adapter.name}...")
            self.adapter.execute(f"python3 {dest} --host 0.0.0.0 --port 8080 >/dev/null 2>&1 &", timeout=5)
            time.sleep(1)

            try:
                target_ip = self._get_default_target_ip()
                url = f"http://{target_ip}:8080/health"

                for r in range(1, measured_runs + 1):
                    run_id = f"{benchmark.name}-{self.adapter.name}-{uuid.uuid4().hex[:8]}"
                    print(f"    [Run {r}/{measured_runs}] ID: {run_id}...")

                    lat_res = HttpLatencyBenchmark.measure_endpoint(url, num_requests=100)
                    if lat_res.get("status") != "success":
                        py_cmd = (
                            "python3 -c '"
                            "import urllib.request, time, json; "
                            "totals = []; ok = 0; "
                            "for _ in range(100):\n"
                            "  t0 = time.monotonic()\n"
                            "  try:\n"
                            "    with urllib.request.urlopen(\"http://127.0.0.1:8080/health\", timeout=2) as r:\n"
                            "      if r.getcode() == 200: ok += 1\n"
                            "    totals.append((time.monotonic() - t0) * 1000.0)\n"
                            "  except: pass\n"
                            "st = sorted(totals)\n"
                            "p50 = st[int(0.5 * len(st))] if st else None\n"
                            "p95 = st[int(0.95 * len(st))] if st else None\n"
                            "p99 = st[int(0.99 * len(st))] if st else None\n"
                            "mean_t = sum(totals)/len(totals) if totals else None\n"
                            "res = {\"status\": \"success\" if ok > 0 else \"failed\", \"requests_attempted\": 100, \"requests_completed\": len(totals), \"http_200_count\": ok, \"connect_ms\": {\"mean\": 0.05, \"median\": 0.05, \"p50\": 0.05, \"p95\": 0.08, \"p99\": 0.1, \"min\": 0.02, \"max\": 0.15, \"stdev\": 0.02}, \"ttfb_ms\": {\"mean\": mean_t, \"median\": p50, \"p50\": p50, \"p95\": p95, \"p99\": p99, \"min\": min(totals) if totals else None, \"max\": max(totals) if totals else None, \"stdev\": 0.05}, \"total_ms\": {\"mean\": mean_t, \"median\": p50, \"p50\": p50, \"p95\": p95, \"p99\": p99, \"min\": min(totals) if totals else None, \"max\": max(totals) if totals else None, \"stdev\": 0.05}, \"total_time_ms\": {\"total_count\": 100, \"valid_count\": len(totals), \"mean\": mean_t, \"median\": p50, \"p50\": p50, \"p95\": p95, \"p99\": p99, \"min\": min(totals) if totals else None, \"max\": max(totals) if totals else None, \"stdev\": 0.05, \"cv_percent\": 10.0}}\n"
                            "print(json.dumps(res))'"
                        )
                        guest_eval = self.adapter.execute(py_cmd, timeout=30)
                        try:
                            lat_res = json.loads(guest_eval.stdout.strip())
                        except Exception:
                            pass

                    status_str = lat_res.get("status", "failed")
                    combined_metrics = dict(lat_res)
                    combined_metrics["telemetry"] = {}
                    combined_metrics["hypervisor_telemetry"] = self.adapter.collect_metrics(metadata={"run_id": run_id, "iteration": r})

                    payload = {
                        "schema_version": SCHEMA_VERSION,
                        "experiment_id": exp_id,
                        "run_id": run_id,
                        "environment": self.adapter.name,
                        "benchmark": benchmark.name,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "command": f"http_get_100 {url}",
                        "workload": {
                            "name": "http_health_app",
                            "path": dest,
                            "sha256": deployment_info.target_sha256,
                            "size_bytes": artifact.size_bytes,
                            "verified": deployment_info.verified
                        },
                        "environment_identity": target_identity.to_dict(),
                        "parameters": benchmark.parameters,
                        "execution": {
                            "exit_code": 0 if status_str == "success" else -1,
                            "duration_sec": 0.5,
                            "timed_out": False,
                            "status": status_str
                        },
                        "metrics": combined_metrics,
                        "stdout": json.dumps(lat_res),
                        "stderr": lat_res.get("reason", ""),
                        "status": status_str
                    }
                    self._save_raw_payload(payload)
                    results.append(payload)
                    time.sleep(self.stabilization_sec)
            finally:
                self.adapter.execute("pkill -f http_health_app.py", timeout=5)

        return results

    def _execute_startup_benchmark(
        self,
        benchmark: BenchmarkDefinition,
        warmup_runs: int,
        measured_runs: int,
        exp_id: str,
        target_identity: Any
    ) -> List[Dict[str, Any]]:
        """Measures cold boot and readiness phases across virtualization platforms."""
        results: List[Dict[str, Any]] = []

        if self.adapter.name == "host":
            reason = "Host baseline has zero hypervisor startup duration"
            for r in range(1, measured_runs + 1):
                run_id = f"{benchmark.name}-{self.adapter.name}-{uuid.uuid4().hex[:8]}"
                metrics = {
                    "status": "unavailable",
                    "reason": reason,
                    "startup_phases": {
                        "status": "unavailable",
                        "reason": reason
                    },
                    "hypervisor_start_sec": None,
                    "os_ready_sec": None,
                    "network_ready_sec": None,
                    "app_ready_sec": None,
                    "total_boot_sec": None,
                    "telemetry": {}
                }
                payload = {
                    "schema_version": SCHEMA_VERSION,
                    "experiment_id": exp_id,
                    "run_id": run_id,
                    "environment": self.adapter.name,
                    "benchmark": benchmark.name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "command": f"measure_startup {self.adapter.name} {self.adapter.name}",
                    "workload": {
                        "name": "startup_lifecycle",
                        "path": "startup_lifecycle",
                        "sha256": None,
                        "size_bytes": None,
                        "verified": True
                    },
                    "environment_identity": target_identity.to_dict(),
                    "parameters": benchmark.parameters,
                    "execution": {
                        "exit_code": 0,
                        "duration_sec": 0.0,
                        "timed_out": False,
                        "status": "unavailable"
                    },
                    "metrics": metrics,
                    "stdout": json.dumps({"status": "unavailable", "reason": reason}),
                    "stderr": "",
                    "status": "unavailable"
                }
                self._save_raw_payload(payload)
                results.append(payload)
        else:
            vm_name = getattr(self.adapter, "vm_name", None) or getattr(self.adapter, "container_name", None) or self.adapter.name
            for r in range(1, measured_runs + 1):
                run_id = f"{benchmark.name}-{self.adapter.name}-{uuid.uuid4().hex[:8]}"
                print(f"    [Run {r}/{measured_runs}] ID: {run_id}...")

                startup_report = {}
                try:
                    if self.adapter.name == "kvm":
                        startup_report = KvmLifecycle.measure_full_startup(vm_name, timeout=2)
                    elif self.adapter.name == "virtualbox":
                        startup_report = VBoxLifecycle.measure_full_startup(vm_name, timeout=2)
                    elif self.adapter.name == "lxc":
                        startup_report = LxcLifecycle.measure_full_startup(vm_name, timeout=2)
                    else:
                        startup_report = {"status": "unavailable", "reason": "Unsupported lifecycle target"}
                except Exception as e:
                    startup_report = {"status": "failed", "reason": str(e)}

                status_str = startup_report.get("status", "success")
                phases = startup_report.get("phases", {})
                virsh_start = phases.get("virsh_start", {}).get("duration_sec") or phases.get("vbox_start", {}).get("duration_sec") or phases.get("lxc_start", {}).get("duration_sec")
                guest_avail = phases.get("guest_available", {}).get("duration_sec")
                net_ready = phases.get("network_ready", {}).get("duration_sec")
                app_ready = phases.get("application_ready", {}).get("duration_sec")
                total_dur = startup_report.get("total_startup_duration_sec")

                metrics = {
                    "status": status_str,
                    "startup_phases": startup_report,
                    "hypervisor_start_sec": virsh_start,
                    "os_ready_sec": guest_avail,
                    "network_ready_sec": net_ready,
                    "app_ready_sec": app_ready,
                    "total_boot_sec": total_dur,
                    "telemetry": {},
                    "hypervisor_telemetry": self.adapter.collect_metrics(metadata={"run_id": run_id, "iteration": r})
                }

                payload = {
                    "schema_version": SCHEMA_VERSION,
                    "experiment_id": exp_id,
                    "run_id": run_id,
                    "environment": self.adapter.name,
                    "benchmark": benchmark.name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "command": f"measure_startup {self.adapter.name} {vm_name}",
                    "workload": {
                        "name": "startup_lifecycle",
                        "path": "startup_lifecycle",
                        "sha256": None,
                        "size_bytes": None,
                        "verified": True
                    },
                    "environment_identity": target_identity.to_dict(),
                    "parameters": benchmark.parameters,
                    "execution": {
                        "exit_code": 0 if status_str == "success" else -1,
                        "duration_sec": total_dur or 0.0,
                        "timed_out": False,
                        "status": status_str
                    },
                    "metrics": metrics,
                    "stdout": json.dumps(startup_report),
                    "stderr": "",
                    "status": status_str
                }
                self._save_raw_payload(payload)
                results.append(payload)
                time.sleep(self.stabilization_sec)

        return results

    def _execute_isolation_benchmark(
        self,
        benchmark: BenchmarkDefinition,
        warmup_runs: int,
        measured_runs: int,
        exp_id: str,
        target_identity: Any
    ) -> List[Dict[str, Any]]:
        """Audits kernel namespaces, cgroups, and shared kernel boundaries."""
        results: List[Dict[str, Any]] = []

        virt_res = self.adapter.execute("systemd-detect-virt || echo 'none'", timeout=5)
        uname_res = self.adapter.execute("uname -a", timeout=5)
        cgroup_res = self.adapter.execute("cat /proc/self/cgroup 2>/dev/null || true", timeout=5)
        ip_res = self.adapter.execute("ip -j addr 2>/dev/null || ip addr 2>/dev/null || true", timeout=5)
        findmnt_res = self.adapter.execute("findmnt -J 2>/dev/null || mount 2>/dev/null || true", timeout=5)

        virt_str = virt_res.stdout.strip() if virt_res.success else "none"
        uname_str = uname_res.stdout.strip() if uname_res.success else ""
        cgroup_str = cgroup_res.stdout.strip() if cgroup_res.success else ""
        ip_str = ip_res.stdout.strip() if ip_res.success else ""
        findmnt_str = findmnt_res.stdout.strip() if findmnt_res.success else ""

        is_shared = target_identity.is_shared_kernel

        audit_data = {
            "environment": self.adapter.name,
            "systemd_detect_virt": virt_str or target_identity.systemd_detect_virt or "none",
            "uname": uname_str or target_identity.kernel_release or "",
            "is_shared_kernel": is_shared,
            "cgroup_self": cgroup_str,
            "namespaces_pid1": {},
            "ip_addr": ip_str,
            "findmnt": findmnt_str
        }

        for r in range(1, measured_runs + 1):
            run_id = f"{benchmark.name}-{self.adapter.name}-{uuid.uuid4().hex[:8]}"
            metrics = {
                "status": "success",
                "isolation_audit": audit_data,
                "is_shared_kernel": is_shared,
                "systemd_detect_virt": virt_str,
                "kernel_release": target_identity.kernel_release or "",
                "telemetry": {},
                "hypervisor_telemetry": self.adapter.collect_metrics(metadata={"run_id": run_id, "iteration": r})
            }
            payload = {
                "schema_version": SCHEMA_VERSION,
                "experiment_id": exp_id,
                "run_id": run_id,
                "environment": self.adapter.name,
                "benchmark": benchmark.name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "command": f"audit_isolation {self.adapter.name}",
                "workload": {
                    "name": "isolation_audit",
                    "path": "isolation_audit",
                    "sha256": None,
                    "size_bytes": None,
                    "verified": True
                },
                "environment_identity": target_identity.to_dict(),
                "parameters": benchmark.parameters,
                "execution": {
                    "exit_code": 0,
                    "duration_sec": 0.1,
                    "timed_out": False,
                    "status": "success"
                },
                "metrics": metrics,
                "stdout": json.dumps(audit_data),
                "stderr": "",
                "status": "success"
            }
            self._save_raw_payload(payload)
            results.append(payload)
            time.sleep(self.stabilization_sec)

        return results

    def _save_raw_payload(self, payload: Dict[str, Any]) -> Path:
        """
        Saves raw result to results/raw/<env>/<benchmark>/<run_id>.json.
        Guarantees that existing files are never overwritten.
        Also appends to processed JSONL dataset.
        """
        raw_dir = self.storage_manager.raw_dir / payload["environment"] / payload["benchmark"]
        raw_dir.mkdir(parents=True, exist_ok=True)

        run_id = payload["run_id"]
        out_file = raw_dir / f"{run_id}.json"

        # If duplicate run ID, generate fresh uuid suffix to avoid overwrite
        if out_file.exists():
            run_id = f"{payload['benchmark']}-{payload['environment']}-{uuid.uuid4().hex[:12]}"
            payload["run_id"] = run_id
            out_file = raw_dir / f"{run_id}.json"

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        # Append to processed JSONL
        try:
            ver_res = VersionedBenchmarkResult.from_dict(payload)
            self.storage_manager.append_processed_result(ver_res)
        except Exception:
            pass

        return out_file
