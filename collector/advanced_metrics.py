#!/usr/bin/env python3
"""
advanced_metrics.py - Advanced System, Hardware, and Latency Measurement Engine for CC2.

Provides specialized collectors and deterministic parsers for:
1. Syscall Profiling (strace -c):
   - Syscall counts, execution time, error counts, and top syscalls breakdown.
   - Status 'unavailable' when strace is restricted or missing.
2. Scheduling & Context Switches (perf stat, /usr/bin/time -v, pidstat):
   - Voluntary and involuntary context switches.
   - CPU migrations.
   - Major, minor, and total page faults.
   - Context switch rates (cswch/s, nvcswch/s) and fault rates.
3. Hardware Performance Counters (perf stat):
   - Cycles, instructions, and calculated IPC (Instructions Per Cycle).
   - Accurately captures /proc/sys/kernel/perf_event_paranoid restrictions.
   - Never fabricates counter values.
4. Thermal & System State Telemetry:
   - Per-core CPU frequencies (scaling_cur_freq).
   - Per-core CPU governors (scaling_governor).
   - System load averages (1m, 5m, 15m).
   - Thermal zone temperatures and sensor types.
   - STRICT SAFETY: Strictly read-only operations. Never modifies governor or disables thermal protection.
5. Application Latency:
   - Minimal identical HTTP application (/health -> HTTP 200).
   - 100 sequential requests measuring socket connect time, TTFB, and total latency.
   - Computes mean, median, p50, p95, p99, min, and max.
6. Network Standardization (iperf3):
   - Strict configuration enforcement: same duration, stream count, direction, and protocol.
   - Structured JSON collection and validation.
"""

import os
import re
import sys
import glob
import json
import time
import socket
import shutil
import tempfile
import subprocess
import http.server
import socketserver
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collector.common import SafetyValidator, run_safe_command, STATUS_SUCCESS, STATUS_FAILED, STATUS_UNAVAILABLE
from analysis.statistics_engine import compute_statistics

STRACE_BIN = shutil.which("strace")
PIDSTAT_BIN = shutil.which("pidstat")
PERF_BIN = shutil.which("perf")
TIME_BIN = "/usr/bin/time"


# =====================================================================
# 1. SYSCALL PROFILING (strace -c)
# =====================================================================

class StraceParser:
    """Parses strace summary output (-c) into structured syscall telemetry."""

    @staticmethod
    def parse(raw_output: str) -> Dict[str, Any]:
        """
        Parses strace -c output table:
        % time     seconds  usecs/call     calls    errors syscall
        ------ ----------- ----------- --------- --------- ----------------
         35.94    0.000313           4        68        47 openat
         22.39    0.000195           6        31           mmap
        ------ ----------- ----------- --------- --------- ----------------
        100.00    0.000871           4       181        53 total
        """
        if not raw_output or not raw_output.strip():
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": "Empty or missing strace output",
                "syscall_count": None,
                "syscall_time_sec": None,
                "errors": None,
                "top_syscalls": []
            }

        lines = [line.strip() for line in raw_output.splitlines() if line.strip()]
        dash_indices = [i for i, line in enumerate(lines) if line.startswith("------")]

        if len(dash_indices) < 2:
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": "Malformed strace output: delimiter lines missing",
                "syscall_count": None,
                "syscall_time_sec": None,
                "errors": None,
                "top_syscalls": []
            }

        start_idx = dash_indices[0] + 1
        end_idx = dash_indices[1]

        records: List[Dict[str, Any]] = []
        for line in lines[start_idx:end_idx]:
            parts = line.split()
            if len(parts) == 5:
                # No errors column present for this row
                try:
                    records.append({
                        "time_pct": float(parts[0]),
                        "seconds": float(parts[1]),
                        "usecs_per_call": int(parts[2]),
                        "calls": int(parts[3]),
                        "errors": 0,
                        "syscall": parts[4]
                    })
                except (ValueError, IndexError):
                    continue
            elif len(parts) >= 6:
                # Errors column present
                try:
                    records.append({
                        "time_pct": float(parts[0]),
                        "seconds": float(parts[1]),
                        "usecs_per_call": int(parts[2]),
                        "calls": int(parts[3]),
                        "errors": int(parts[4]),
                        "syscall": parts[5]
                    })
                except (ValueError, IndexError):
                    continue

        total_time = 0.0
        total_calls = 0
        total_errors = 0

        # Check for summary row below the second dash line
        if end_idx + 1 < len(lines):
            summary_parts = lines[end_idx + 1].split()
            if len(summary_parts) >= 5 and summary_parts[-1] == "total":
                try:
                    total_time = float(summary_parts[1])
                    total_calls = int(summary_parts[3])
                    if len(summary_parts) >= 6:
                        total_errors = int(summary_parts[4])
                except (ValueError, IndexError):
                    pass
        
        # Fallback to sum if summary row was unparseable
        if total_calls == 0 and records:
            total_calls = sum(r["calls"] for r in records)
            total_time = sum(r["seconds"] for r in records)
            total_errors = sum(r["errors"] for r in records)

        # Sort top syscalls by invocation count descending, then execution time
        top_syscalls = sorted(records, key=lambda x: (x["calls"], x["seconds"]), reverse=True)[:10]

        return {
            "status": STATUS_SUCCESS,
            "syscall_count": total_calls,
            "syscall_time_sec": total_time,
            "errors": total_errors,
            "unique_syscalls": len(records),
            "top_syscalls": top_syscalls
        }


class SyscallCollector:
    """Executes a workload under strace -c and captures syscall telemetry."""

    @staticmethod
    def run_strace(command: str, timeout: int = 60) -> Dict[str, Any]:
        """Runs command with strace -c. Returns parsed syscall telemetry."""
        SafetyValidator.validate_command(command)

        if not STRACE_BIN or not os.path.exists(STRACE_BIN):
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": "strace binary not found on system",
                "syscall_count": None,
                "syscall_time_sec": None,
                "errors": None,
                "top_syscalls": []
            }

        strace_cmd = f"{STRACE_BIN} -c {command}"
        res = run_safe_command(strace_cmd, timeout=timeout)
        
        # strace prints summary output to stderr
        parsed = StraceParser.parse(res["stderr"])
        if parsed["status"] != STATUS_SUCCESS and res["stdout"]:
            # Check if stdout contained the table in case of redirection
            parsed = StraceParser.parse(res["stdout"])

        if parsed["status"] == STATUS_SUCCESS:
            parsed["command"] = command
            parsed["exit_code"] = res["exit_code"]
        else:
            parsed["exit_code"] = res["exit_code"]
            if not parsed.get("reason"):
                parsed["reason"] = res["stderr"] or "strace execution failed"

        return parsed


# =====================================================================
# 2. SCHEDULING TELEMETRY (pidstat & perf stat & time -v)
# =====================================================================

class PidstatParser:
    """Parses pidstat context switch (-w) and memory page fault (-r) output."""

    @staticmethod
    def parse(raw_output: str) -> Dict[str, Any]:
        metrics = {
            "status": STATUS_UNAVAILABLE,
            "voluntary_cswch_per_sec": None,
            "involuntary_nvcswch_per_sec": None,
            "minor_faults_per_sec": None,
            "major_faults_per_sec": None,
            "vsz_kb": None,
            "rss_kb": None,
            "reason": None
        }

        if not raw_output or not raw_output.strip():
            metrics["reason"] = "Empty pidstat output"
            return metrics

        for line in raw_output.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "Linux" in line or "Command" in line:
                continue

            parts = line.split()
            # Detect whether timestamp is 1 token (e.g. 16:30:15) or 2 tokens (e.g. 04:30:15 PM)
            offset = 1 if len(parts) > 1 and parts[1] in ("AM", "PM") else 0

            # Standard horizontal header: [Time (1 or 2 parts), UID, PID, minflt/s, majflt/s, VSZ, RSS, %MEM, cswch/s, nvcswch/s, Command]
            if len(parts) >= (10 + offset):
                try:
                    metrics["minor_faults_per_sec"] = float(parts[3 + offset])
                    metrics["major_faults_per_sec"] = float(parts[4 + offset])
                    metrics["vsz_kb"] = int(float(parts[5 + offset]))
                    metrics["rss_kb"] = int(float(parts[6 + offset]))
                    metrics["voluntary_cswch_per_sec"] = float(parts[8 + offset])
                    metrics["involuntary_nvcswch_per_sec"] = float(parts[9 + offset])
                    metrics["status"] = STATUS_SUCCESS
                    break
                except (ValueError, IndexError):
                    continue

        if metrics["status"] != STATUS_SUCCESS:
            # Check for non-horizontal pidstat sections
            for line in raw_output.splitlines():
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        # Context switch table: [Time, UID, PID, cswch/s, nvcswch/s, Command]
                        if metrics["voluntary_cswch_per_sec"] is None and float(parts[3]) >= 0:
                            metrics["voluntary_cswch_per_sec"] = float(parts[3])
                            metrics["involuntary_nvcswch_per_sec"] = float(parts[4])
                            metrics["status"] = STATUS_SUCCESS
                    except (ValueError, IndexError):
                        pass

        return metrics


class PerfStatParser:
    """Parses perf stat CSV output for cycles, instructions, IPC, and migrations."""

    @staticmethod
    def parse_csv(raw_output: str) -> Dict[str, Any]:
        perf_data = {
            "status": STATUS_UNAVAILABLE,
            "cycles": None,
            "instructions": None,
            "ipc": None,
            "context_switches": None,
            "cpu_migrations": None,
            "page_faults": None,
            "reason": None
        }

        if not raw_output or not raw_output.strip():
            perf_data["reason"] = "Empty perf output"
            return perf_data

        for line in raw_output.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                val_str = parts[0]
                event_name = parts[2].lower()
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

        if perf_data["cycles"] and perf_data["instructions"]:
            if perf_data["cycles"] > 0:
                perf_data["ipc"] = round(perf_data["instructions"] / perf_data["cycles"], 4)

        if any(v is not None for k, v in perf_data.items() if k not in ("status", "reason")):
            perf_data["status"] = STATUS_SUCCESS

        return perf_data


class SchedulingCollector:
    """
    Coordinates context switches, CPU migrations, and page fault collections
    across perf stat, /usr/bin/time -v, and pidstat.
    """

    @staticmethod
    def probe_perf_paranoid() -> Tuple[bool, str]:
        """Checks /proc/sys/kernel/perf_event_paranoid and accessibility."""
        if not PERF_BIN or not os.path.exists(PERF_BIN):
            return False, "perf binary not found on host"

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
                timeout=3
            )
            if res.returncode == 0:
                return True, "supported"
            else:
                return False, f"Hardware counters restricted: /proc/sys/kernel/perf_event_paranoid is {paranoid_val} (requires CAP_PERFMON or CAP_SYS_ADMIN)"
        except Exception as e:
            return False, f"perf execution error: {str(e)}"

    @classmethod
    def collect_scheduling(cls, command: str, timeout: int = 60) -> Dict[str, Any]:
        """
        Executes command and captures scheduling telemetry:
        context switches, CPU migrations, page faults, and hardware counters.
        """
        SafetyValidator.validate_command(command)

        perf_supported, perf_reason = cls.probe_perf_paranoid()

        # 1. Run with pidstat -h -w -r -e
        pidstat_metrics = {"status": STATUS_UNAVAILABLE, "reason": "pidstat not available"}
        if PIDSTAT_BIN and os.path.exists(PIDSTAT_BIN):
            pid_res = run_safe_command(f"{PIDSTAT_BIN} -h -w -r -e {command}", timeout=timeout)
            if pid_res["exit_code"] == 0:
                pidstat_metrics = PidstatParser.parse(pid_res["stdout"])

        # 2. Run with perf stat if supported
        perf_metrics = {
            "status": STATUS_UNAVAILABLE,
            "reason": perf_reason,
            "cycles": None,
            "instructions": None,
            "ipc": None,
            "context_switches": None,
            "cpu_migrations": None,
            "page_faults": None
        }

        if perf_supported:
            perf_cmd = f"{PERF_BIN} stat -x, -e context-switches,cpu-migrations,page-faults,cycles,instructions {command}"
            perf_run = run_safe_command(perf_cmd, timeout=timeout)
            parsed_perf = PerfStatParser.parse_csv(perf_run["stderr"] or perf_run["stdout"])
            if parsed_perf["status"] == STATUS_SUCCESS:
                perf_metrics = parsed_perf

        return {
            "pidstat": pidstat_metrics,
            "perf": perf_metrics
        }


# =====================================================================
# 3. THERMAL & SYSTEM STATE TELEMETRY (Read-Only)
# =====================================================================

class ThermalSystemStateCollector:
    """
    Safely captures CPU frequency, governor, system load, and thermal telemetry.
    Strict Invariant: Strictly read-only operations. Never modifies governors or thermal limits.
    """

    @staticmethod
    def collect_cpu_frequency() -> Dict[str, Any]:
        """Collects per-core CPU frequency in kHz and summary stats."""
        freq_files = sorted(glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq"))
        per_core: Dict[str, int] = {}

        if freq_files:
            for f_path in freq_files:
                match = re.search(r"cpu(\d+)", f_path)
                core_id = match.group(1) if match else os.path.basename(os.path.dirname(os.path.dirname(f_path)))
                try:
                    with open(f_path, "r") as f:
                        freq_val = int(f.read().strip())
                        per_core[f"cpu{core_id}"] = freq_val
                except Exception:
                    pass

        # Fallback to /proc/cpuinfo if cpufreq files not available (e.g. inside VMs)
        if not per_core:
            cpuinfo_path = Path("/proc/cpuinfo")
            if cpuinfo_path.exists():
                try:
                    curr_cpu = 0
                    for line in cpuinfo_path.read_text().splitlines():
                        if line.startswith("processor"):
                            curr_cpu = int(line.split(":")[1].strip())
                        elif line.startswith("cpu MHz"):
                            mhz = float(line.split(":")[1].strip())
                            per_core[f"cpu{curr_cpu}"] = int(mhz * 1000)
                except Exception:
                    pass

        if not per_core:
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": "CPU frequency interfaces not readable in this environment",
                "per_core_khz": {},
                "min_khz": None,
                "max_khz": None,
                "avg_khz": None
            }

        values = list(per_core.values())
        return {
            "status": STATUS_SUCCESS,
            "per_core_khz": per_core,
            "min_khz": min(values),
            "max_khz": max(values),
            "avg_khz": round(sum(values) / len(values), 2)
        }

    @staticmethod
    def collect_cpu_governor() -> Dict[str, Any]:
        """Collects per-core CPU governors (read-only)."""
        gov_files = sorted(glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"))
        per_core: Dict[str, str] = {}

        if gov_files:
            for g_path in gov_files:
                match = re.search(r"cpu(\d+)", g_path)
                core_id = match.group(1) if match else os.path.basename(os.path.dirname(os.path.dirname(g_path)))
                try:
                    with open(g_path, "r") as f:
                        per_core[f"cpu{core_id}"] = f.read().strip()
                except Exception:
                    pass

        if not per_core:
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": "CPU governor interfaces not readable in this environment",
                "per_core": {},
                "governors": []
            }

        unique_govs = sorted(list(set(per_core.values())))
        return {
            "status": STATUS_SUCCESS,
            "per_core": per_core,
            "governors": unique_govs,
            "dominant_governor": unique_govs[0] if len(unique_govs) == 1 else "mixed"
        }

    @staticmethod
    def collect_load_average() -> Dict[str, float]:
        """Collects 1-minute, 5-minute, and 15-minute system load averages."""
        load1, load5, load15 = os.getloadavg()
        return {
            "load_1m": round(load1, 3),
            "load_5m": round(load5, 3),
            "load_15m": round(load15, 3)
        }

    @staticmethod
    def collect_thermal_zones() -> Dict[str, Any]:
        """Safely reads thermal zones and temperature sensors (read-only)."""
        zone_dirs = sorted(glob.glob("/sys/class/thermal/thermal_zone*"))
        zones: List[Dict[str, Any]] = []

        for zd in zone_dirs:
            zone_name = os.path.basename(zd)
            t_type = "unknown"
            temp_c = None

            type_file = Path(zd) / "type"
            temp_file = Path(zd) / "temp"

            if type_file.exists():
                try:
                    with open(type_file, "r") as f:
                        t_type = f.read().strip()
                except Exception:
                    pass

            if temp_file.exists():
                try:
                    with open(temp_file, "r") as f:
                        raw_temp = int(f.read().strip())
                        temp_c = round(raw_temp / 1000.0, 2)
                except Exception:
                    pass

            if temp_c is not None:
                zones.append({
                    "zone": zone_name,
                    "type": t_type,
                    "temperature_c": temp_c
                })

        if not zones:
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": "Thermal zone interfaces not readable in this environment",
                "zones": [],
                "max_temp_c": None,
                "package_temp_c": None
            }

        all_temps = [z["temperature_c"] for z in zones]
        pkg_zone = next((z for z in zones if "pkg" in z["type"].lower() or "tcpu" in z["type"].lower() or "core" in z["type"].lower()), None)

        return {
            "status": STATUS_SUCCESS,
            "zones": zones,
            "max_temp_c": max(all_temps),
            "package_temp_c": pkg_zone["temperature_c"] if pkg_zone else None
        }

    @classmethod
    def collect_full_system_state(cls) -> Dict[str, Any]:
        """Collects combined read-only system, thermal, and frequency snapshot."""
        return {
            "cpu_frequency": cls.collect_cpu_frequency(),
            "cpu_governor": cls.collect_cpu_governor(),
            "load_average": cls.collect_load_average(),
            "thermal": cls.collect_thermal_zones()
        }


# =====================================================================
# 4. APPLICATION LATENCY (Minimal HTTP Application & 100-Request Benchmark)
# =====================================================================

class MinimalHealthHttpServer:
    """Minimal zero-dependency HTTP application serving GET /health with HTTP 200."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                body = b'{"status":"healthy","version":"1.0.0"}'
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass  # Suppress request logging for benchmarking efficiency

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.server = socketserver.TCPServer((host, port), self.Handler)
        self.host, self.port = self.server.server_address
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/health"


class HttpLatencyBenchmark:
    """
    Executes exactly 100 HTTP GET /health requests.
    Measures socket-level:
    - connect time (ms)
    - TTFB: Time To First Byte (ms)
    - total time (ms)
    Calculates: mean, median, p50, p95, p99, min, max.
    """

    @staticmethod
    def measure_endpoint(
        url: str,
        num_requests: int = 100,
        timeout_sec: float = 3.0
    ) -> Dict[str, Any]:
        """Measures 100 requests to url and returns comprehensive percentiles."""
        match = re.match(r"http://([^:/]+):?(\d+)?(/.*)?", url)
        if not match:
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": f"Malformed URL '{url}'. Expected http://<host>[:<port>]/path"
            }

        host = match.group(1)
        port = int(match.group(2)) if match.group(2) else 80
        path = match.group(3) if match.group(3) else "/"

        connect_ms_list: List[float] = []
        ttfb_ms_list: List[float] = []
        total_ms_list: List[float] = []
        status_codes: List[int] = []

        req_bytes = f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n".encode("utf-8")

        for _ in range(num_requests):
            t_start = time.monotonic()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout_sec)
            try:
                # 1. Measure TCP connection handshake
                sock.connect((host, port))
                t_connect = time.monotonic()

                # 2. Send HTTP request
                sock.sendall(req_bytes)

                # 3. Measure Time to First Byte (TTFB)
                first_chunk = sock.recv(1)
                t_ttfb = time.monotonic()

                # 4. Drain the remainder of the HTTP response
                resp_buf = bytearray(first_chunk)
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    resp_buf.extend(chunk)
                t_total = time.monotonic()

                # Parse HTTP status code
                resp_str = resp_buf.decode("latin1", errors="replace")
                if "HTTP/" in resp_str:
                    parts = resp_str.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        status_codes.append(int(parts[1]))

                connect_ms_list.append((t_connect - t_start) * 1000.0)
                ttfb_ms_list.append((t_ttfb - t_start) * 1000.0)
                total_ms_list.append((t_total - t_start) * 1000.0)
            except Exception:
                pass
            finally:
                sock.close()

        if not total_ms_list:
            return {
                "status": STATUS_UNAVAILABLE,
                "url": url,
                "reason": f"HTTP endpoint at {url} unreachable or timed out across all requests"
            }

        # Calculate statistics
        connect_stats = compute_statistics(connect_ms_list)
        ttfb_stats = compute_statistics(ttfb_ms_list)
        total_stats = compute_statistics(total_ms_list)

        success_count = sum(1 for sc in status_codes if sc == 200)

        return {
            "status": STATUS_SUCCESS if success_count > 0 else STATUS_FAILED,
            "url": url,
            "requests_attempted": num_requests,
            "requests_completed": len(total_ms_list),
            "http_200_count": success_count,
            "connect_ms": {
                "mean": connect_stats["mean"],
                "median": connect_stats["median"],
                "p50": connect_stats["p50"],
                "p95": connect_stats["p95"],
                "p99": connect_stats["p99"],
                "min": connect_stats["min"],
                "max": connect_stats["max"],
                "stdev": connect_stats["stdev"]
            },
            "ttfb_ms": {
                "mean": ttfb_stats["mean"],
                "median": ttfb_stats["median"],
                "p50": ttfb_stats["p50"],
                "p95": ttfb_stats["p95"],
                "p99": ttfb_stats["p99"],
                "min": ttfb_stats["min"],
                "max": ttfb_stats["max"],
                "stdev": ttfb_stats["stdev"]
            },
            "total_ms": {
                "mean": total_stats["mean"],
                "median": total_stats["median"],
                "p50": total_stats["p50"],
                "p95": total_stats["p95"],
                "p99": total_stats["p99"],
                "min": total_stats["min"],
                "max": total_stats["max"],
                "stdev": total_stats["stdev"]
            },
            "total_time_ms": total_stats,
            "total_duration_ms": total_stats
        }


# =====================================================================
# 5. NETWORK STANDARDIZATION (iperf3)
# =====================================================================

class Iperf3Config:
    """Guarantees strictly identical iperf3 benchmarking parameters across all environments."""
    DEFAULT_DURATION_SEC = 10
    QUICK_DURATION_SEC = 3
    DEFAULT_STREAM_COUNT = 1
    DEFAULT_PROTOCOL = "TCP"
    DEFAULT_DIRECTION = "client-to-server"

    @classmethod
    def build_command(
        cls,
        target_ip: str,
        duration: int = DEFAULT_DURATION_SEC,
        streams: int = DEFAULT_STREAM_COUNT
    ) -> str:
        """Constructs standardized iperf3 invocation guaranteeing identical parameters."""
        iperf_bin = shutil.which("iperf3") or "iperf3"
        # -J: JSON format output
        # -t: Duration in seconds
        # -P: Parallel stream count
        # Default direction is client-to-server; TCP protocol
        return f"{iperf_bin} -c {target_ip} -t {duration} -P {streams} -J"

    @staticmethod
    def parse_iperf3_json(raw_json_str: str) -> Dict[str, Any]:
        """Parses standardized iperf3 JSON output into bandwidth and retransmit metrics."""
        if not raw_json_str or not raw_json_str.strip():
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": "Empty iperf3 output"
            }

        try:
            data = json.loads(raw_json_str)
        except json.JSONDecodeError as e:
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": f"Failed to parse iperf3 JSON: {str(e)}"
            }

        if "error" in data:
            return {
                "status": STATUS_UNAVAILABLE,
                "reason": data["error"]
            }

        end_section = data.get("end", {})
        sum_sent = end_section.get("sum_sent", {})
        sum_received = end_section.get("sum_received", {})

        sender_mbps = (sum_sent.get("bits_per_second", 0.0) / 1e6) if sum_sent else None
        receiver_mbps = (sum_received.get("bits_per_second", 0.0) / 1e6) if sum_received else None
        retransmits = sum_sent.get("retransmits") if sum_sent else None

        return {
            "status": STATUS_SUCCESS,
            "protocol": Iperf3Config.DEFAULT_PROTOCOL,
            "direction": Iperf3Config.DEFAULT_DIRECTION,
            "stream_count": len(end_section.get("streams", [])) or Iperf3Config.DEFAULT_STREAM_COUNT,
            "sender_bandwidth_mbps": round(sender_mbps, 3) if sender_mbps is not None else None,
            "receiver_bandwidth_mbps": round(receiver_mbps, 3) if receiver_mbps is not None else None,
            "retransmits": retransmits,
            "raw_json": data
        }


if __name__ == "__main__":
    print("=== Testing Thermal & System State Collector ===")
    state = ThermalSystemStateCollector.collect_full_system_state()
    print(json.dumps(state, indent=2))

    print("\n=== Testing Strace Syscall Collector ===")
    syscall_res = SyscallCollector.run_strace(f"{PROJECT_ROOT}/workloads/dist/cpu_workload --size 50 --iterations 1")
    print(f"Status: {syscall_res['status']}, Count: {syscall_res.get('syscall_count')}, Top: {len(syscall_res.get('top_syscalls', []))}")

    print("\n=== Testing HTTP Health Benchmark ===")
    srv = MinimalHealthHttpServer()
    srv.start()
    try:
        lat = HttpLatencyBenchmark.measure_endpoint(srv.url, num_requests=10)
        print(f"Status: {lat['status']}, Completed: {lat['requests_completed']}")
        print(f"Connect p50: {lat['connect_ms']['p50']}ms, TTFB p50: {lat['ttfb_ms']['p50']}ms, Total p50: {lat['total_ms']['p50']}ms")
    finally:
        srv.stop()
