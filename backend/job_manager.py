#!/usr/bin/env python3
"""
backend/job_manager.py - Benchmark Job Execution & Concurrency Manager.

Manages the lifecycle of asynchronous benchmark experiments:
- Unique job IDs
- Strict concurrency control (at most one active experiment running)
- Background execution via runner subprocess
- Real-time sanitized log capture
- Fine-grained progress tracking (environment, benchmark, run, phase)
- Cancellation handling
- Provenance linking to generated raw/processed result files
"""

import os
import re
import sys
import time
import uuid
import signal
import threading
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple, Set

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.sanitizer import sanitize_text, sanitize_dict_records

# Supported environments and benchmark normalization
VALID_ENVIRONMENTS: Set[str] = {"host", "kvm", "virtualbox", "lxc", "all"}
VALID_MODES: Set[str] = {"quick", "full"}

BENCHMARK_ALIASES: Dict[str, str] = {
    "cpu": "cpu_deterministic",
    "cpu_deterministic": "cpu_deterministic",
    "memory": "memory_deterministic",
    "memory_deterministic": "memory_deterministic",
    "disk": "disk_fio",
    "disk_fio": "disk_fio",
    "network": "network_ping",
    "ping": "network_ping",
    "network_ping": "network_ping",
    "iperf": "network_iperf3",
    "iperf3": "network_iperf3",
    "network_iperf3": "network_iperf3",
    "app": "app_latency",
    "app_latency": "app_latency",
    "startup": "startup_lifecycle",
    "startup_lifecycle": "startup_lifecycle",
    "syscall": "syscall_deterministic",
    "syscall_deterministic": "syscall_deterministic",
    "scheduling": "scheduling_deterministic",
    "scheduling_deterministic": "scheduling_deterministic",
    "isolation": "isolation_audit",
    "isolation_audit": "isolation_audit",
    "all": "all"
}

# Forbidden characters in run parameters to prevent command injection
SHELL_INJECTION_PATTERN = re.compile(r"[;&|`$<>\n\r]")


class ConcurrencyConflictError(Exception):
    """Raised when an experiment job is already running or queued."""
    pass


class InvalidJobRequestError(Exception):
    """Raised when a client run request contains invalid parameters."""
    pass


@dataclass
class JobProgress:
    status: str = "queued"
    environment: Optional[str] = None
    benchmark: Optional[str] = None
    run: int = 0
    total_runs: int = 0
    phase: str = "initializing"
    percent: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkJob:
    job_id: str
    status: str  # "queued", "running", "completed", "failed", "cancelled"
    environment: str
    benchmark: str
    mode: str
    runs: int
    created_at: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    exit_code: Optional[int] = None
    progress: JobProgress = field(default_factory=JobProgress)
    result_files: List[str] = field(default_factory=list)
    error: Optional[str] = None
    stdout: str = ""
    stderr: str = ""
    command_args: List[str] = field(default_factory=list)
    is_dry_run: bool = False

    def to_summary_dict(self) -> Dict[str, Any]:
        """Summary representation without full terminal logs."""
        return {
            "job_id": self.job_id,
            "status": self.status,
            "environment": self.environment,
            "benchmark": self.benchmark,
            "mode": self.mode,
            "runs": self.runs,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "progress": self.progress.to_dict(),
            "result_files_count": len(self.result_files),
            "error": self.error,
            "is_dry_run": self.is_dry_run
        }

    def to_detail_dict(self) -> Dict[str, Any]:
        """Full representation including result file links."""
        summary = self.to_summary_dict()
        summary["result_files"] = self.result_files
        summary["command_args"] = [sanitize_text(a) for a in self.command_args]
        return summary


class JobManager:
    """
    Thread-safe benchmark job executor and state store.
    """

    def __init__(self, project_root: Path = PROJECT_ROOT):
        self.project_root = project_root
        self.runner_script = project_root / "benchmark" / "runner.py"
        self._jobs: Dict[str, BenchmarkJob] = {}
        self._lock = threading.Lock()
        self._active_job_id: Optional[str] = None
        self._active_process: Optional[subprocess.Popen] = None

    def validate_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates the run request payload against strict whitelist invariants.
        """
        if not isinstance(payload, dict):
            raise InvalidJobRequestError("Request payload must be a JSON object.")

        # Check for unexpected fields
        allowed_fields = {"environment", "benchmark", "mode", "runs", "dry_run"}
        unknown_fields = set(payload.keys()) - allowed_fields
        if unknown_fields:
            raise InvalidJobRequestError(f"Unknown request fields rejected: {sorted(list(unknown_fields))}")

        # 1. Environment validation
        env_raw = str(payload.get("environment", "host")).strip().lower()
        if SHELL_INJECTION_PATTERN.search(env_raw) or env_raw not in VALID_ENVIRONMENTS:
            raise InvalidJobRequestError(
                f"Invalid environment '{env_raw}'. Allowed: {sorted(list(VALID_ENVIRONMENTS))}"
            )

        # 2. Benchmark validation
        bench_raw = str(payload.get("benchmark", "cpu")).strip().lower()
        if SHELL_INJECTION_PATTERN.search(bench_raw) or bench_raw not in BENCHMARK_ALIASES:
            raise InvalidJobRequestError(
                f"Invalid benchmark '{bench_raw}'. Allowed: {sorted(list(BENCHMARK_ALIASES.keys()))}"
            )
        canonical_bench = BENCHMARK_ALIASES[bench_raw]

        # 3. Mode validation
        mode_raw = str(payload.get("mode", "quick")).strip().lower()
        if mode_raw not in VALID_MODES:
            raise InvalidJobRequestError(f"Invalid mode '{mode_raw}'. Allowed: {sorted(list(VALID_MODES))}")

        # 4. Runs validation
        runs = payload.get("runs")
        if runs is not None:
            if not isinstance(runs, int) or isinstance(runs, bool):
                raise InvalidJobRequestError(f"Parameter 'runs' must be an integer (1..20), received: {type(runs).__name__}")
            if runs < 1 or runs > 20:
                raise InvalidJobRequestError(f"Parameter 'runs' must be between 1 and 20, received: {runs}")
        else:
            runs = 2 if mode_raw == "quick" else 5

        dry_run = bool(payload.get("dry_run", False))

        return {
            "environment": env_raw,
            "benchmark": canonical_bench,
            "mode": mode_raw,
            "runs": runs,
            "dry_run": dry_run
        }

    def create_and_start_job(self, payload: Dict[str, Any]) -> BenchmarkJob:
        """
        Validates parameters, enforces concurrency, and spawns the benchmark job.
        """
        validated = self.validate_request(payload)

        with self._lock:
            # Concurrency check: Ensure no other experiment is currently active
            if self._active_job_id is not None:
                active_job = self._jobs.get(self._active_job_id)
                if active_job and active_job.status in ("queued", "running"):
                    raise ConcurrencyConflictError(
                        f"An experiment job '{self._active_job_id}' is currently {active_job.status}. "
                        "Simultaneous experiments are prevented to eliminate host resource interference."
                    )

            # Generate unique job ID
            timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            short_id = uuid.uuid4().hex[:8]
            job_id = f"job-{timestamp_str}-{short_id}"

            total_runs = validated["runs"]
            # Estimate total runs if all environments are selected
            env_count = 4 if validated["environment"] == "all" else 1
            expected_total_steps = env_count * total_runs

            progress = JobProgress(
                status="queued",
                environment=validated["environment"],
                benchmark=validated["benchmark"],
                run=0,
                total_runs=expected_total_steps,
                phase="queued",
                percent=0
            )

            job = BenchmarkJob(
                job_id=job_id,
                status="queued",
                environment=validated["environment"],
                benchmark=validated["benchmark"],
                mode=validated["mode"],
                runs=validated["runs"],
                created_at=datetime.now(timezone.utc).isoformat(),
                progress=progress,
                is_dry_run=validated["dry_run"]
            )

            self._jobs[job_id] = job
            self._active_job_id = job_id

        # Spawn worker thread to execute runner
        worker = threading.Thread(
            target=self._execute_job_worker,
            args=(job_id,),
            name=f"Worker-{job_id}",
            daemon=True
        )
        worker.start()

        return job

    def get_job(self, job_id: str) -> Optional[BenchmarkJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 50) -> List[BenchmarkJob]:
        with self._lock:
            sorted_jobs = sorted(
                self._jobs.values(),
                key=lambda j: j.created_at,
                reverse=True
            )
            return sorted_jobs[:limit]

    def cancel_job(self, job_id: str) -> bool:
        """
        Cancels an active job and terminates its runner process.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in ("queued", "running"):
                return False

            if self._active_job_id == job_id and self._active_process:
                try:
                    self._active_process.terminate()
                    time.sleep(0.5)
                    if self._active_process.poll() is None:
                        self._active_process.kill()
                except Exception:
                    pass

            job.status = "cancelled"
            job.ended_at = datetime.now(timezone.utc).isoformat()
            job.progress.status = "cancelled"
            job.progress.phase = "cancelled_by_user"
            if self._active_job_id == job_id:
                self._active_job_id = None
                self._active_process = None

            return True

    def _execute_job_worker(self, job_id: str) -> None:
        """
        Worker thread running the runner.py subprocess.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = "running"
            job.started_at = datetime.now(timezone.utc).isoformat()
            job.progress.status = "running"
            job.progress.phase = "starting_runner"

        # Build command safely without shell strings
        cmd: List[str] = [sys.executable, str(self.runner_script)]

        if job.environment == "all":
            cmd.append("--all")
        else:
            cmd.extend(["--environment", job.environment])

        if job.benchmark != "all":
            cmd.extend(["--test", job.benchmark])

        if job.mode == "full":
            cmd.append("--full")
        else:
            cmd.append("--quick")

        if job.runs:
            cmd.extend(["--runs", str(job.runs)])

        if job.is_dry_run:
            cmd.append("--dry-run")

        job.command_args = cmd

        # Snapshot existing results directory to detect newly produced files
        pre_files = self._snapshot_result_files()

        stdout_chunks: List[str] = []
        stderr_chunks: List[str] = []

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self.project_root),
                bufsize=1
            )
            with self._lock:
                self._active_process = proc

            # Thread to capture stderr
            def read_stderr():
                for err_line in iter(proc.stderr.readline, ''):
                    if not err_line:
                        break
                    sanitized = sanitize_text(err_line)
                    stderr_chunks.append(sanitized)
                proc.stderr.close()

            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stderr_thread.start()

            # Read stdout line by line and parse progress
            current_completed_runs = 0
            for line in iter(proc.stdout.readline, ''):
                if not line:
                    break
                sanitized_line = sanitize_text(line)
                stdout_chunks.append(sanitized_line)

                # Dynamically update progress
                self._parse_progress_line(job, sanitized_line)

            proc.stdout.close()
            stderr_thread.join(timeout=5)
            proc.wait()
            exit_code = proc.returncode

        except Exception as e:
            exit_code = -1
            stderr_chunks.append(f"Subprocess execution error: {sanitize_text(str(e))}")

        # Post-execution state update
        post_files = self._snapshot_result_files()
        new_files = sorted(list(post_files - pre_files))

        with self._lock:
            job.stdout = "".join(stdout_chunks)
            job.stderr = "".join(stderr_chunks)
            job.exit_code = exit_code
            job.ended_at = datetime.now(timezone.utc).isoformat()
            job.result_files = new_files

            if exit_code == 0:
                job.status = "completed"
                job.progress.status = "completed"
                job.progress.phase = "finished"
                job.progress.percent = 100
            else:
                job.status = "failed"
                job.progress.status = "failed"
                job.progress.phase = "failed"
                job.error = f"Runner exited with non-zero code {exit_code}"

            if self._active_job_id == job_id:
                self._active_job_id = None
                self._active_process = None

    def _parse_progress_line(self, job: BenchmarkJob, line: str) -> None:
        """
        Extracts execution progress from runner stdout in real-time.
        """
        line_s = line.strip()

        # Check for benchmark start header
        # BENCHMARK EXECUTION: memory_deterministic on Host Ubuntu Baseline
        bench_match = re.search(r"BENCHMARK EXECUTION:\s*(\w+)\s+on\s+([A-Za-z0-9\s]+)", line_s)
        if bench_match:
            bench_name = bench_match.group(1)
            target_desc = bench_match.group(2).lower()
            job.progress.benchmark = bench_name
            if "host" in target_desc:
                job.progress.environment = "host"
            elif "kvm" in target_desc:
                job.progress.environment = "kvm"
            elif "virtualbox" in target_desc or "vbox" in target_desc:
                job.progress.environment = "virtualbox"
            elif "lxc" in target_desc:
                job.progress.environment = "lxc"
            job.progress.phase = "initiating_benchmark"

        # Check for step transitions
        if "Step 1/7: Preparing environment" in line_s:
            job.progress.phase = "preparing_environment"
        elif "Step 2/7: Inspecting target execution identity" in line_s:
            job.progress.phase = "inspecting_identity"
        elif "Step 3/7: Quenching and host thermal stabilization" in line_s:
            job.progress.phase = "thermal_stabilization"
        elif "Deploying workload" in line_s:
            job.progress.phase = "deploying_workload"
        elif "Step 5/7: Executing" in line_s:
            job.progress.phase = "executing_runs"
        elif "Step 6/7: Cleaning up environment" in line_s:
            job.progress.phase = "cleaning_up"

        # Check for measured run completion
        # [Run 2/5] ID: memory_deterministic-host-12345678...
        run_match = re.search(r"\[Run\s+(\d+)/(\d+)\]", line_s)
        if run_match:
            cur_run = int(run_match.group(1))
            tot_runs = int(run_match.group(2))
            job.progress.run = cur_run
            job.progress.phase = f"running_iteration_{cur_run}_of_{tot_runs}"
            if job.progress.total_runs > 0:
                calc_percent = min(95, int((cur_run / max(tot_runs, 1)) * 90))
                job.progress.percent = max(job.progress.percent, calc_percent)

    def _snapshot_result_files(self) -> Set[str]:
        """Snapshots filenames in results/ directory to identify newly generated files."""
        results_dir = self.project_root / "results"
        if not results_dir.exists():
            return set()

        files = set()
        for p in results_dir.rglob("*.json*"):
            if p.is_file():
                try:
                    rel = p.relative_to(self.project_root)
                    files.add(str(rel))
                except Exception:
                    pass
        return files


# Global JobManager singleton
_GLOBAL_JOB_MANAGER: Optional[JobManager] = None

def get_job_manager() -> JobManager:
    global _GLOBAL_JOB_MANAGER
    if _GLOBAL_JOB_MANAGER is None:
        _GLOBAL_JOB_MANAGER = JobManager()
    return _GLOBAL_JOB_MANAGER
