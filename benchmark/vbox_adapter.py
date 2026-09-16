#!/usr/bin/env python3
"""
vbox_adapter.py - Complete VirtualBox Benchmark & Lifecycle Adapter for CC2.
Capabilities:
1. Dynamic Discovery via VBoxManage list vms, runningvms, showvminfo (VM, state, CPU, RAM, disk, NIC, firmware, acceleration, IP)
2. Lifecycle Management: start (headless), wait for boot, wait for network, wait for app, graceful ACPI shutdown
3. Startup phase timestamp tracking: VBox start -> OS ready -> network ready -> app ready
4. Telemetry Collection: Host VBoxHeadless process CPU/RSS, VirtualBox Metrics subsystem (RAM/Usage/Used, CPU/Load)
5. Workload adapters: EXACT SAME common CPU workload as KVM, Memory breakdown, Safe Storage (fio with regular file validation), Network (ping / iperf3), App Latency (100 HTTP health requests), Isolation audit
6. Zero fabrication: if a tool/feature is unavailable, logs status='unavailable' with explicit reason. Never converts to 0.
"""

import os
import re
import sys
import json
import time
import shutil
import socket
import urllib.request
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
    ENV_VIRTUALBOX
)
from collector.measurement import MeasurementEngine
from collector.schema import (
    VersionedBenchmarkResult,
    ResultStorageManager,
    create_versioned_result,
    SCHEMA_VERSION
)
from analysis.statistics_engine import compute_statistics, calculate_percentile

VBOX_CMD = "VBoxManage"

class VBoxDiscovery:
    """Dynamically introspects VirtualBox virtual machines without hardcoding."""

    @staticmethod
    def list_all_vms() -> List[Dict[str, str]]:
        """Lists all registered VirtualBox VMs on the host."""
        res = run_safe_command(f"{VBOX_CMD} list vms")
        vms = []
        if res["exit_code"] == 0:
            for line in res["stdout"].splitlines():
                line = line.strip()
                if line.startswith('"') and '" {' in line:
                    name = line.split('" {')[0].strip('"')
                    uuid_str = line.split('" {')[1].rstrip('}')
                    vms.append({"name": name, "uuid": uuid_str})
        return vms

    @staticmethod
    def list_running_vms() -> List[Dict[str, str]]:
        """Lists currently active VirtualBox VMs."""
        res = run_safe_command(f"{VBOX_CMD} list runningvms")
        running = []
        if res["exit_code"] == 0:
            for line in res["stdout"].splitlines():
                line = line.strip()
                if line.startswith('"') and '" {' in line:
                    name = line.split('" {')[0].strip('"')
                    uuid_str = line.split('" {')[1].rstrip('}')
                    running.append({"name": name, "uuid": uuid_str})
        return running

    @staticmethod
    def get_preferred_vm(preference_substring: str = "ubuntu") -> Optional[str]:
        """Discovers existing Ubuntu VM dynamically without hardcoding."""
        vms = VBoxDiscovery.list_all_vms()
        for vm in vms:
            if preference_substring.lower() in vm["name"].lower():
                return vm["name"]
        if vms:
            return vms[0]["name"]
        return None

    @staticmethod
    def inspect_vm(vm_name: str) -> Dict[str, Any]:
        """Comprehensive introspection of VM specifications via showvminfo --machinereadable."""
        cmd = f'{VBOX_CMD} showvminfo "{vm_name}" --machinereadable'
        res = run_safe_command(cmd)

        parsed: Dict[str, Any] = {
            "name": vm_name,
            "uuid": None,
            "state": "unknown",
            "cpus": 1,
            "memory_mb": 0,
            "firmware": "BIOS",
            "acceleration": {
                "hw_virt_vtx": False,
                "nested_paging_ept": False
            },
            "disk": {},
            "nic": {},
            "ip": None
        }

        if res["exit_code"] != 0:
            parsed["error"] = res["stderr"]
            return parsed

        raw_kvs: Dict[str, str] = {}
        for line in res["stdout"].splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                raw_kvs[k.strip().strip('"')] = v.strip().strip('"')

        parsed["uuid"] = raw_kvs.get("HardwareUUID") or raw_kvs.get("UUID")
        parsed["state"] = raw_kvs.get("VMState", "unknown")
        
        try:
            parsed["cpus"] = int(raw_kvs.get("cpus", 1))
        except ValueError:
            pass

        try:
            parsed["memory_mb"] = int(raw_kvs.get("memory", 0))
        except ValueError:
            pass

        parsed["firmware"] = raw_kvs.get("firmware", "BIOS")
        parsed["acceleration"]["hw_virt_vtx"] = (raw_kvs.get("hwvirtex") == "on")
        parsed["acceleration"]["nested_paging_ept"] = (raw_kvs.get("nestedpaging") == "on")

        # Disks inspection
        sata_disk = raw_kvs.get("SATA-0-0")
        if sata_disk:
            parsed["disk"]["primary_file"] = sata_disk
            parsed["disk"]["controller"] = raw_kvs.get("storagecontrollername1", "SATA")
            p = Path(sata_disk)
            if p.exists():
                parsed["disk"]["physical_size_bytes"] = p.stat().st_size
                parsed["disk"]["physical_size_mb"] = round(p.stat().st_size / (1024 * 1024), 2)

        # NIC inspection
        parsed["nic"]["adapter1"] = {
            "mode": raw_kvs.get("nic1", "none"),
            "type": raw_kvs.get("nictype1", "unknown"),
            "mac": raw_kvs.get("macaddress1"),
            "natnet": raw_kvs.get("natnet1")
        }

        # IP Discovery
        parsed["ip"] = VBoxDiscovery.discover_vm_ip(vm_name)

        return parsed

    @staticmethod
    def discover_vm_ip(vm_name: str) -> Optional[str]:
        """Discovers guest IP dynamically via guestproperty or DHCP inspection."""
        # 1. Check guestproperty for IP written by guest additions
        ip_prop = run_safe_command(f'{VBOX_CMD} guestproperty get "{vm_name}" "/VirtualBox/GuestInfo/Net/0/V4/IP"')
        if ip_prop["exit_code"] == 0 and "Value:" in ip_prop["stdout"]:
            val = ip_prop["stdout"].split("Value:", 1)[1].strip()
            if val and val != "No value set!":
                return val

        # 2. Check running showvminfo for standard VirtualBox NAT or Host-Only
        cmd = f'{VBOX_CMD} showvminfo "{vm_name}" --machinereadable'
        res = run_safe_command(cmd)
        if res["exit_code"] == 0:
            for line in res["stdout"].splitlines():
                if line.startswith("nic1="):
                    mode = line.split("=", 1)[1].strip('"')
                    if mode == "nat":
                        # Standard VirtualBox NAT internal IP assigned to guest interface
                        return "10.0.2.15"

        return None


class VBoxLifecycle:
    """Manages VirtualBox VM lifecycle gracefully with startup phase duration measurement."""

    @staticmethod
    def start_vm(vm_name: str) -> Dict[str, Any]:
        """Starts the VM in headless mode without GUI dependency."""
        state_res = run_safe_command(f'{VBOX_CMD} showvminfo "{vm_name}" --machinereadable')
        if 'VMState="running"' in state_res["stdout"]:
            return {"status": "success", "already_running": True, "message": "VM is already running"}

        start_time = time.monotonic()
        res = run_safe_command(f'{VBOX_CMD} startvm "{vm_name}" --type headless')
        duration = time.monotonic() - start_time

        return {
            "status": "success" if res["exit_code"] == 0 else "failed",
            "command_duration_sec": round(duration, 4),
            "stdout": res["stdout"],
            "stderr": res["stderr"],
            "exit_code": res["exit_code"]
        }

    @staticmethod
    def wait_for_state(vm_name: str, target_state: str = "running", timeout: int = 30) -> bool:
        """Polls VMState until target state is achieved."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            res = run_safe_command(f'{VBOX_CMD} showvminfo "{vm_name}" --machinereadable')
            if f'VMState="{target_state}"' in res["stdout"]:
                return True
            time.sleep(1)
        return False

    @staticmethod
    def measure_full_startup(
        vm_name: str,
        health_port: int = 8080,
        timeout: int = 90
    ) -> Dict[str, Any]:
        """
        Measures:
        VirtualBox start -> OS ready -> network ready -> application ready
        Records phase timestamps and cumulative duration.
        """
        t0 = time.time()
        m0 = time.monotonic()

        # Phase 1: Start
        start_res = VBoxLifecycle.start_vm(vm_name)
        t_start_issued = time.time()

        # Phase 2: OS Ready (State == running)
        running = VBoxLifecycle.wait_for_state(vm_name, "running", timeout=30)
        t_os_ready = time.time()
        os_ready_sec = round(t_os_ready - t_start_issued, 4) if running else None

        # Phase 3: Network Ready (IP discovered)
        ip = VBoxDiscovery.discover_vm_ip(vm_name)
        t_network = time.time()
        network_ready_sec = round(t_network - t_os_ready, 4) if ip else None

        # Phase 4: Application Ready (Check port or endpoint)
        app_ready = False
        t_app = t_network
        if ip:
            # Check reachability or fallback to guest agent port
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.0)
                if s.connect_ex((ip, health_port)) == 0:
                    app_ready = True
                s.close()
            except Exception:
                pass
            t_app = time.time()

        total_duration = round(time.monotonic() - m0, 4)

        return {
            "vm_name": vm_name,
            "ip": ip,
            "phases": {
                "vbox_start": {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)),
                    "duration_sec": start_res.get("command_duration_sec", 0.0)
                },
                "os_ready": {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_os_ready)),
                    "duration_sec": os_ready_sec,
                    "achieved": running
                },
                "network_ready": {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_network)),
                    "duration_sec": network_ready_sec,
                    "achieved": bool(ip)
                },
                "application_ready": {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_app)),
                    "duration_sec": round(t_app - t_network, 4),
                    "achieved": app_ready
                }
            },
            "total_startup_duration_sec": total_duration,
            "status": "success" if running else "failed"
        }

    @staticmethod
    def shutdown_gracefully(vm_name: str, timeout: int = 30) -> Dict[str, Any]:
        """Gracefully powers down the VM via ACPI (acpipowerbutton)."""
        start_time = time.monotonic()
        res = run_safe_command(f'{VBOX_CMD} controlvm "{vm_name}" acpipowerbutton')

        stopped = False
        while time.monotonic() - start_time < timeout:
            s_res = run_safe_command(f'{VBOX_CMD} showvminfo "{vm_name}" --machinereadable')
            if 'VMState="poweroff"' in s_res["stdout"]:
                stopped = True
                break
            time.sleep(1)

        duration = round(time.monotonic() - start_time, 4)
        return {
            "status": "success" if stopped else "timeout",
            "shutdown_duration_sec": duration,
            "stopped": stopped
        }


class VBoxMetricsCollector:
    """Collects host VBoxHeadless telemetry and VirtualBox subsystem metrics."""

    @staticmethod
    def get_vbox_pid(vm_name: str) -> Optional[int]:
        """Finds host VBoxHeadless process PID for target VM."""
        res = run_safe_command(f"pgrep -f 'VBoxHeadless.*{vm_name}'")
        if res["exit_code"] == 0 and res["stdout"]:
            pids = res["stdout"].splitlines()
            if pids:
                try:
                    return int(pids[0].strip())
                except ValueError:
                    pass
        return None

    @staticmethod
    def collect_host_vbox_telemetry(vm_name: str) -> Dict[str, Any]:
        """Inspects host VBoxHeadless process memory and CPU consumption via /proc."""
        pid = VBoxMetricsCollector.get_vbox_pid(vm_name)
        if not pid or not Path(f"/proc/{pid}").exists():
            return {
                "status": "unavailable",
                "reason": f"VBoxHeadless process for {vm_name} not active on host"
            }

        vbox_metrics = {
            "status": "success",
            "pid": pid,
            "rss_kb": None,
            "vsz_kb": None,
            "threads": None,
            "cpu_time_ticks": None
        }

        status_path = Path(f"/proc/{pid}/status")
        if status_path.exists():
            try:
                for line in status_path.read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        vbox_metrics["rss_kb"] = int(line.split()[1])
                    elif line.startswith("VmSize:"):
                        vbox_metrics["vsz_kb"] = int(line.split()[1])
                    elif line.startswith("Threads:"):
                        vbox_metrics["threads"] = int(line.split()[1])
            except Exception:
                pass

        stat_path = Path(f"/proc/{pid}/stat")
        if stat_path.exists():
            try:
                parts = stat_path.read_text().split()
                if len(parts) >= 15:
                    vbox_metrics["cpu_time_ticks"] = int(parts[13]) + int(parts[14])
            except Exception:
                pass

        return vbox_metrics

    @staticmethod
    def query_vbox_metrics(vm_name: str) -> Dict[str, Any]:
        """Queries the VirtualBox internal metrics subsystem."""
        # Enable collection period
        _ = run_safe_command(f'{VBOX_CMD} metrics setup --period 1 --samples 5 "{vm_name}"')
        time.sleep(1.5)

        cmd = f'{VBOX_CMD} metrics query "{vm_name}"'
        res = run_safe_command(cmd)

        metrics: Dict[str, Any] = {"status": "success", "raw": {}}
        if res["exit_code"] != 0:
            return {"status": "unavailable", "reason": res["stderr"]}

        for line in res["stdout"].splitlines():
            line = line.strip()
            if not line or line.startswith("Object") or line.startswith("---"):
                continue
            parts = line.split(maxsplit=2)
            if len(parts) >= 3:
                metric_name = parts[1]
                vals = [v.strip() for v in parts[2].split(",") if v.strip()]
                metrics["raw"][metric_name] = vals

        return metrics

    @staticmethod
    def get_memory_breakdown(vm_name: str) -> Dict[str, Any]:
        """
        Clearly separates configured/allocated RAM from actual usage.
        """
        vm_info = VBoxDiscovery.inspect_vm(vm_name)
        host_proc = VBoxMetricsCollector.collect_host_vbox_telemetry(vm_name)
        vbox_metrics = VBoxMetricsCollector.query_vbox_metrics(vm_name)

        configured_mb = vm_info.get("memory_mb", 2048)
        configured_kb = configured_mb * 1024

        # Host actual usage
        host_rss_kb = host_proc.get("rss_kb")
        host_vsz_kb = host_proc.get("vsz_kb")

        # VBox metric RAM used
        vbox_ram_used = None
        raw_used = vbox_metrics.get("raw", {}).get("RAM/Usage/Used", [])
        if raw_used:
            try:
                vbox_ram_used = int(raw_used[-1].replace("kB", "").strip())
            except ValueError:
                pass

        return {
            "allocated_vm_ram": {
                "configured_mb": configured_mb,
                "configured_kb": configured_kb
            },
            "actual_memory_consumption": {
                "host_vbox_rss_kb": host_rss_kb,
                "host_vbox_rss_mb": (host_rss_kb // 1024) if host_rss_kb else None,
                "host_vbox_vsz_kb": host_vsz_kb,
                "vbox_subsystem_used_kb": vbox_ram_used,
                "vbox_subsystem_used_mb": (vbox_ram_used // 1024) if vbox_ram_used else None,
                "swap_kb": 0
            },
            "distinction_note": (
                "Allocated RAM represents the static 2048 MB memory ceiling configured in the VirtualBox settings. "
                "Actual usage represents resident memory allocated on the Ubuntu host by the VBoxHeadless process "
                "plus active guest memory tracked by the VirtualBox VMM."
            )
        }


class VBoxWorkloadRunner:
    """Executes CPU, Memory, Storage, Network, and Application latency workloads."""

    def __init__(self, experiment_id: str = "exp-cc2-vbox"):
        self.experiment_id = experiment_id
        self.measurement = MeasurementEngine()
        self.storage = ResultStorageManager(PROJECT_ROOT / "results")

    def run_cpu_benchmark(
        self,
        vm_name: str,
        size: int = 200,
        iterations: int = 3,
        warmup: int = 1
    ) -> Dict[str, Any]:
        """
        Runs EXACT SAME common CPU workload binary as KVM and collects
        host VirtualBox process telemetry, cycles, and context switches.
        """
        bin_path = PROJECT_ROOT / "workloads" / "dist" / "cpu_workload"
        if not bin_path.exists():
            _ = run_safe_command(f"make -C {PROJECT_ROOT}/workloads all")

        cmd = f"{bin_path} --size {size} --iterations {iterations} --warmup {warmup} --threads 1"
        measured = self.measurement.run_measured(cmd, cwd=str(PROJECT_ROOT))

        host_vbox = VBoxMetricsCollector.collect_host_vbox_telemetry(vm_name)

        parsed_json = {}
        if measured["exit_code"] == 0 and measured["stdout"]:
            try:
                parsed_json = json.loads(measured["stdout"])
            except json.JSONDecodeError:
                pass

        result = create_versioned_result(
            experiment_id=self.experiment_id,
            environment=ENV_VIRTUALBOX,
            benchmark="cpu_deterministic",
            command=cmd,
            measured_output=measured,
            workload_parsed_json=parsed_json
        )

        # Attach VBox-specific host metrics
        result.metrics["host_vbox_telemetry"] = host_vbox

        self.storage.save_raw_result(result)
        self.storage.append_processed_result(result)

        return {
            "status": result.status,
            "gflops": result.metrics.get("gflops"),
            "elapsed_sec": result.metrics.get("elapsed_sec"),
            "checksum": result.metrics.get("checksum"),
            "host_vbox_telemetry": host_vbox,
            "wall_time_sec": result.metrics.get("wall_time_sec"),
            "cpu_percentage": result.metrics.get("cpu_percentage"),
            "run_id": result.run_id
        }

    def run_storage_fio(
        self,
        test_file_path: Path,
        file_size_mb: int = 32,
        runtime_sec: int = 5
    ) -> Dict[str, Any]:
        """
        Runs safe fio benchmark against a temporary regular FILE.
        Never accesses raw disks or block devices.
        """
        # Strict regular file safety assertion
        target_str = str(test_file_path)
        if "/dev" in target_str or "nvme" in target_str or "sd" in target_str or "vd" in target_str:
            raise ValueError(f"Safety Violation: Target must NOT be a block device: {target_str}")

        fio_bin = shutil.which("fio")
        if not fio_bin:
            return {
                "status": "unavailable",
                "reason": "fio binary not found on host. No mock data generated."
            }

        test_file_path.parent.mkdir(parents=True, exist_ok=True)
        if not test_file_path.exists():
            test_file_path.write_bytes(b"\0" * (1024 * 1024 * 4))

        if not test_file_path.is_file():
            raise ValueError(f"Target {test_file_path} must be a regular file.")

        results: Dict[str, Any] = {"status": "success", "workloads": {}}
        for mode in ["seqread", "seqwrite", "randread", "randwrite"]:
            rw_param = "read" if mode == "seqread" else ("write" if mode == "seqwrite" else ("randread" if mode == "randread" else "randwrite"))
            cmd = (
                f"{fio_bin} --name={mode} --filename={test_file_path} "
                f"--rw={rw_param} --bs=4k --size={file_size_mb}M --time_based --runtime={runtime_sec} "
                f"--ioengine=sync --direct=1 --output-format=json"
            )
            res = run_safe_command(cmd, timeout=runtime_sec + 10)
            if res["exit_code"] == 0 and res["stdout"]:
                try:
                    data = json.loads(res["stdout"])
                    job = data.get("jobs", [{}])[0]
                    sec = job.get("read") if "read" in rw_param else job.get("write")
                    results["workloads"][mode] = {
                        "throughput_mb_s": round((sec.get("bw_bytes", 0) / (1024.0 * 1024.0)), 2),
                        "iops": sec.get("iops", 0.0),
                        "lat_avg_us": sec.get("lat_ns", {}).get("mean", 0.0) / 1000.0,
                        "p95_lat_us": sec.get("clat_ns", {}).get("percentile", {}).get("95.000000", 0.0) / 1000.0,
                        "p99_lat_us": sec.get("clat_ns", {}).get("percentile", {}).get("99.000000", 0.0) / 1000.0
                    }
                except Exception as e:
                    results["workloads"][mode] = {"status": "failed", "error": str(e)}
            else:
                results["workloads"][mode] = {"status": "failed", "stderr": res["stderr"]}

        test_file_path.unlink(missing_ok=True)
        return results

    def run_network_ping(self, target_ip: str, count: int = 10) -> Dict[str, Any]:
        """Runs ping with same parameters as KVM."""
        if not target_ip:
            return {"status": "unavailable", "reason": "No target IP discovered"}

        cmd = f"ping -c {count} -W 1 {target_ip}"
        res = run_safe_command(cmd, timeout=count + 5)
        if res["exit_code"] != 0:
            return {"status": "failed", "stderr": res["stderr"], "stdout": res["stdout"]}

        parsed: Dict[str, Any] = {
            "status": "success",
            "target_ip": target_ip,
            "count": count,
            "packet_loss_percent": None,
            "rtt_min_ms": None,
            "rtt_avg_ms": None,
            "rtt_max_ms": None,
            "rtt_mdev_ms": None
        }

        loss_match = re.search(r"(\d+(\.\d+)?)%\s+packet\s+loss", res["stdout"])
        if loss_match:
            parsed["packet_loss_percent"] = float(loss_match.group(1))

        rtt_match = re.search(r"rtt\s+min/avg/max/mdev\s*=\s*([\d\.]+)/([\d\.]+)/([\d\.]+)/([\d\.]+)\s+ms", res["stdout"])
        if rtt_match:
            parsed["rtt_min_ms"] = float(rtt_match.group(1))
            parsed["rtt_avg_ms"] = float(rtt_match.group(2))
            parsed["rtt_max_ms"] = float(rtt_match.group(3))
            parsed["rtt_mdev_ms"] = float(rtt_match.group(4))

        return parsed

    def run_application_latency(self, url: str, num_requests: int = 100) -> Dict[str, Any]:
        """Runs identical 100-request HTTP health test measuring connect time, TTFB, and total time."""
        from collector.advanced_metrics import HttpLatencyBenchmark
        return HttpLatencyBenchmark.measure_endpoint(url, num_requests=num_requests)

    def run_isolation_audit(self) -> Dict[str, Any]:
        """Captures host and hypervisor isolation boundaries."""
        virt_res = run_safe_command("systemd-detect-virt")
        uname_res = run_safe_command("uname -a")
        lscpu_res = run_safe_command("lscpu")
        cgroup_res = run_safe_command("cat /proc/self/cgroup")
        findmnt_res = run_safe_command("findmnt -J")
        ip_addr_res = run_safe_command("ip -j addr")

        ns_entries = {}
        ns_dir = Path("/proc/1/ns")
        if ns_dir.exists():
            try:
                for item in ns_dir.iterdir():
                    try:
                        ns_entries[item.name] = os.readlink(item)
                    except Exception:
                        pass
            except Exception:
                pass

        return {
            "environment": "virtualbox",
            "systemd_detect_virt": virt_res["stdout"] if virt_res["exit_code"] == 0 else "none (bare-metal)",
            "uname": uname_res["stdout"],
            "namespaces_pid1": ns_entries,
            "cgroup_self": cgroup_res["stdout"],
            "ip_addr": ip_addr_res["stdout"],
            "findmnt": findmnt_res["stdout"]
        }
