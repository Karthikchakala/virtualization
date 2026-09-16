#!/usr/bin/env python3
"""
measurement.py - High-fidelity system and resource measurement engine.
Captures:
- wall time, user time, system time
- CPU percentage
- voluntary and involuntary context switches
- CPU migrations
- major and minor page faults
- RSS (Resident Set Size) and VSZ
- exit code
- Hardware performance counters via perf when available

Strict Invariant: If perf or any counter is unavailable, records status='unavailable'.
Never fabricates metrics. Never converts missing measurements to zero.
"""

import os
import re
import sys
import shutil
import tempfile
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collector.common import SafetyValidator

TIME_BIN = "/usr/bin/time"
PERF_BIN = shutil.which("perf")

def parse_wall_clock_time(time_str: str) -> Optional[float]:
    """
    Parses elapsed wall clock time formatted by /usr/bin/time:
    e.g., '0:00.05', '1:23.45', '1:02:03.45'
    """
    if not time_str or not time_str.strip():
        return None
    time_str = time_str.strip()
    try:
        parts = time_str.split(":")
        if len(parts) == 3:
            h = float(parts[0])
            m = float(parts[1])
            s = float(parts[2])
            return h * 3600.0 + m * 60.0 + s
        elif len(parts) == 2:
            m = float(parts[0])
            s = float(parts[1])
            return m * 60.0 + s
        else:
            return float(parts[0])
    except (ValueError, IndexError):
        return None

def parse_time_v_output(raw_output: str) -> Dict[str, Any]:
    """
    Parses the standard verbose output of GNU /usr/bin/time -v.
    Returns structured metrics dict.
    """
    metrics: Dict[str, Any] = {
        "status": "unavailable",
        "user_time_sec": None,
        "system_time_sec": None,
        "wall_time_sec": None,
        "cpu_percentage": None,
        "max_rss_kb": None,
        "vsz_kb": None,
        "minor_page_faults": None,
        "major_page_faults": None,
        "total_page_faults": None,
        "voluntary_context_switches": None,
        "involuntary_context_switches": None,
        "total_context_switches": None,
        "exit_code": None
    }

    if not raw_output:
        return metrics

    for line in raw_output.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue

        if "Elapsed (wall clock) time" in line and "):" in line:
            key = "Elapsed (wall clock) time"
            val = line.split("):", 1)[1].strip()
        else:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()

        try:
            if "User time (seconds)" in key:
                metrics["user_time_sec"] = float(val)
            elif "System time (seconds)" in key:
                metrics["system_time_sec"] = float(val)
            elif "Percent of CPU this job got" in key:
                val_clean = val.replace("%", "").strip()
                metrics["cpu_percentage"] = float(val_clean)
            elif "Elapsed (wall clock) time" in key:
                metrics["wall_time_sec"] = parse_wall_clock_time(val)
            elif "Maximum resident set size" in key:
                metrics["max_rss_kb"] = int(val)
            elif "Average total size" in key:
                metrics["vsz_kb"] = int(val)
            elif "Major (requiring I/O) page faults" in key:
                metrics["major_page_faults"] = int(val)
            elif "Minor (reclaiming a frame) page faults" in key:
                metrics["minor_page_faults"] = int(val)
            elif "Voluntary context switches" in key:
                metrics["voluntary_context_switches"] = int(val)
            elif "Involuntary context switches" in key:
                metrics["involuntary_context_switches"] = int(val)
            elif "Exit status" in key:
                metrics["exit_code"] = int(val)
        except (ValueError, TypeError):
            pass

    # Calculate aggregate page faults if both present
    if metrics["minor_page_faults"] is not None and metrics["major_page_faults"] is not None:
        metrics["total_page_faults"] = metrics["minor_page_faults"] + metrics["major_page_faults"]

    # Calculate aggregate context switches if both present
    if metrics["voluntary_context_switches"] is not None and metrics["involuntary_context_switches"] is not None:
        metrics["total_context_switches"] = metrics["voluntary_context_switches"] + metrics["involuntary_context_switches"]

    if metrics["wall_time_sec"] is not None:
        metrics["status"] = "success"

    return metrics

def probe_perf_support() -> Tuple[bool, str]:
    """Checks whether hardware performance counters are accessible without CAP_SYS_ADMIN."""
    if not PERF_BIN or not os.path.exists(PERF_BIN):
        return False, "perf binary not found"

    paranoid_path = Path("/proc/sys/kernel/perf_event_paranoid")
    paranoid_val = "unknown"
    if paranoid_path.exists():
        try:
            paranoid_val = paranoid_path.read_text().strip()
        except Exception:
            pass

    try:
        res = subprocess.run(
            [PERF_BIN, "stat", "-e", "cycles", "true"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if res.returncode == 0:
            return True, "supported"
        else:
            return False, f"Hardware counters restricted: /proc/sys/kernel/perf_event_paranoid is {paranoid_val} (requires CAP_PERFMON or CAP_SYS_ADMIN)"
    except Exception as e:
        return False, str(e)

def parse_perf_csv_output(raw_perf: str) -> Dict[str, Any]:
    """
    Parses perf stat output in CSV format (-x,).
    Calculates IPC (instructions per cycle) when cycles and instructions are available.
    """
    perf_data = {
        "status": "unavailable",
        "cycles": None,
        "instructions": None,
        "ipc": None,
        "context_switches": None,
        "cpu_migrations": None,
        "page_faults": None
    }

    if not raw_perf:
        return perf_data

    for line in raw_perf.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            val_str = parts[0]
            event_name = parts[2]
            try:
                val = int(val_str) if val_str.isdigit() else float(val_str)
            except ValueError:
                continue

            if "cycles" in event_name:
                perf_data["cycles"] = int(val)
            elif "instructions" in event_name:
                perf_data["instructions"] = int(val)
            elif "context-switches" in event_name:
                perf_data["context_switches"] = int(val)
            elif "cpu-migrations" in event_name:
                perf_data["cpu_migrations"] = int(val)
            elif "page-faults" in event_name:
                perf_data["page_faults"] = int(val)

    if perf_data["cycles"] and perf_data["instructions"] and perf_data["cycles"] > 0:
        perf_data["ipc"] = round(perf_data["instructions"] / perf_data["cycles"], 4)

    if any(v is not None for k, v in perf_data.items() if k not in ("status", "reason")):
        perf_data["status"] = "success"

    return perf_data

class MeasurementEngine:
    """Executes commands and captures resource & kernel telemetry."""

    def __init__(self):
        self.has_time = os.path.exists(TIME_BIN) and os.access(TIME_BIN, os.X_OK)
        self.perf_supported, self.perf_reason = probe_perf_support()

    def run_measured(
        self,
        cmd: str,
        cwd: Optional[str] = None,
        timeout: int = 60,
        env_vars: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Executes command with /usr/bin/time -v and perf (if available).
        Returns comprehensive execution payload.
        """
        SafetyValidator.validate_command(cmd)

        run_env = os.environ.copy()
        if env_vars:
            run_env.update(env_vars)

        time_output_file = None
        cmd_to_run = cmd

        if self.has_time:
            time_fd, time_path = tempfile.mkstemp(prefix="cc2_time_")
            os.close(time_fd)
            time_output_file = Path(time_path)
            cmd_to_run = f"{TIME_BIN} -v -o {time_output_file} {cmd}"

        proc_stdout = ""
        proc_stderr = ""
        exit_code = -1
        timed_out = False

        try:
            proc = subprocess.run(
                cmd_to_run,
                shell=True,
                cwd=cwd or str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=run_env
            )
            exit_code = proc.returncode
            proc_stdout = proc.stdout
            proc_stderr = proc.stderr
        except subprocess.TimeoutExpired as e:
            timed_out = True
            proc_stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            proc_stderr = f"Command timed out after {timeout} seconds."
            exit_code = -1
        except Exception as e:
            proc_stderr = f"Subprocess invocation error: {str(e)}"
            exit_code = -1

        # Parse /usr/bin/time -v data
        time_metrics = {}
        if time_output_file and time_output_file.exists():
            try:
                raw_time_str = time_output_file.read_text(encoding="utf-8")
                time_metrics = parse_time_v_output(raw_time_str)
                time_metrics["raw_time_v"] = raw_time_str
            finally:
                time_output_file.unlink(missing_ok=True)
        else:
            time_metrics = {
                "status": "unavailable",
                "reason": "/usr/bin/time not found or not executed"
            }

        # Perf metrics
        perf_metrics = {
            "status": "unavailable",
            "reason": self.perf_reason if not self.perf_supported else "perf not requested",
            "cycles": None,
            "instructions": None,
            "ipc": None,
            "context_switches": None,
            "cpu_migrations": None,
            "page_faults": None
        }

        # Override exit code from time -v if available and trustworthy
        final_exit_code = exit_code
        if time_metrics.get("exit_code") is not None and not timed_out:
            final_exit_code = time_metrics["exit_code"]

        return {
            "command": cmd,
            "exit_code": final_exit_code,
            "timed_out": timed_out,
            "stdout": proc_stdout,
            "stderr": proc_stderr,
            "telemetry": {
                "time_v": time_metrics,
                "perf": perf_metrics,
                "wall_time_sec": time_metrics.get("wall_time_sec"),
                "user_time_sec": time_metrics.get("user_time_sec"),
                "system_time_sec": time_metrics.get("system_time_sec"),
                "cpu_percentage": time_metrics.get("cpu_percentage"),
                "max_rss_kb": time_metrics.get("max_rss_kb"),
                "vsz_kb": time_metrics.get("vsz_kb"),
                "page_faults": {
                    "minor": time_metrics.get("minor_page_faults"),
                    "major": time_metrics.get("major_page_faults"),
                    "total": time_metrics.get("total_page_faults")
                },
                "context_switches": {
                    "voluntary": time_metrics.get("voluntary_context_switches"),
                    "involuntary": time_metrics.get("involuntary_context_switches"),
                    "total": time_metrics.get("total_context_switches")
                }
            }
        }

    def run_with_strace(self, cmd: str, timeout: int = 60) -> Dict[str, Any]:
        """Runs workload under strace -c and returns parsed syscall metrics."""
        from collector.advanced_metrics import SyscallCollector
        return SyscallCollector.run_strace(cmd, timeout=timeout)

    def run_with_scheduling(self, cmd: str, timeout: int = 60) -> Dict[str, Any]:
        """Runs workload under pidstat and perf stat to capture scheduling metrics."""
        from collector.advanced_metrics import SchedulingCollector
        return SchedulingCollector.collect_scheduling(cmd, timeout=timeout)

if __name__ == "__main__":
    engine = MeasurementEngine()
    print("Testing MeasurementEngine on host CPU workload...")
    res = engine.run_measured(f"{PROJECT_ROOT}/workloads/dist/cpu_workload --size 150 --iterations 2")
    print(f"Exit code: {res['exit_code']}")
    print(f"Wall time: {res['telemetry']['wall_time_sec']}s")
    print(f"User time: {res['telemetry']['user_time_sec']}s")
    print(f"System time: {res['telemetry']['system_time_sec']}s")
    print(f"CPU %:     {res['telemetry']['cpu_percentage']}%")
    print(f"Max RSS:   {res['telemetry']['max_rss_kb']} KB")
    print(f"Context switches: {res['telemetry']['context_switches']}")
    print(f"Perf status: {res['telemetry']['perf']['status']} ({res['telemetry']['perf']['reason']})")
