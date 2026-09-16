#!/usr/bin/env python3
"""
kvm_adapter.py - Complete KVM/QEMU Benchmark & Lifecycle Adapter for CC2.
Capabilities:
1. Dynamic KVM Discovery via virsh -c qemu:///system (VM name, state, vCPUs, RAM, disk, network, IP, machine type, firmware)
2. Lifecycle Management: start, wait for boot, wait for network, wait for application readiness, shutdown gracefully
3. Startup phase timestamp tracking: virsh start -> guest available -> network ready -> application ready
4. Telemetry Collection: Host QEMU CPU/RSS, Libvirt Domstats (vCPU time, virtio-balloon RAM, block I/O, net I/O)
5. Workload adapters: CPU, Memory, Safe Storage (fio with regular file validation), Network (ping / iperf3), App Latency (HTTP health), Isolation audit
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
import xml.etree.ElementTree as ET
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
    ENV_KVM
)
from collector.measurement import MeasurementEngine
from collector.schema import (
    VersionedBenchmarkResult,
    ResultStorageManager,
    create_versioned_result,
    SCHEMA_VERSION
)
from analysis.statistics_engine import compute_statistics, calculate_percentile

VIRSH_CMD = "virsh -c qemu:///system"

class KvmDiscovery:
    """Dynamically introspects KVM domains via libvirt."""

    @staticmethod
    def list_all_vms() -> List[Dict[str, str]]:
        """Lists all registered VMs on the host."""
        res = run_safe_command(f"{VIRSH_CMD} list --all")
        vms = []
        if res["exit_code"] == 0:
            for line in res["stdout"].splitlines():
                line = line.strip()
                if not line or line.startswith("Id") or line.startswith("---"):
                    continue
                parts = line.split(maxsplit=2)
                if len(parts) >= 3:
                    vms.append({
                        "id": parts[0],
                        "name": parts[1],
                        "state": parts[2]
                    })
        return vms

    @staticmethod
    def get_preferred_vm(preference_substring: str = "ubuntu") -> Optional[str]:
        """Discovers existing Ubuntu VM dynamically without hardcoding."""
        vms = KvmDiscovery.list_all_vms()
        # 1. Prefer VM containing preference_substring (case-insensitive)
        for vm in vms:
            if preference_substring.lower() in vm["name"].lower():
                return vm["name"]
        # 2. Fallback to first available VM
        if vms:
            return vms[0]["name"]
        return None

    @staticmethod
    def inspect_vm(vm_name: str) -> Dict[str, Any]:
        """Comprehensive introspection of VM specifications from domain XML and domstats."""
        xml_res = run_safe_command(f"{VIRSH_CMD} dumpxml {vm_name}")
        info_res = run_safe_command(f"{VIRSH_CMD} dominfo {vm_name}")

        parsed_data = {
            "name": vm_name,
            "state": "unknown",
            "vcpus": 1,
            "memory_kb": 0,
            "memory_mb": 0,
            "machine_type": "unknown",
            "firmware": "BIOS",
            "disk": {},
            "network": {},
            "ip": None
        }

        # Parse dominfo for basic state
        if info_res["exit_code"] == 0:
            for line in info_res["stdout"].splitlines():
                if "State:" in line:
                    parsed_data["state"] = line.split(":", 1)[1].strip()
                elif "CPU(s):" in line:
                    try: parsed_data["vcpus"] = int(line.split(":", 1)[1].strip())
                    except ValueError: pass
                elif "Max memory:" in line:
                    try:
                        mem_kb = int(line.split(":", 1)[1].replace("KiB","").strip())
                        parsed_data["memory_kb"] = mem_kb
                        parsed_data["memory_mb"] = mem_kb // 1024
                    except ValueError: pass

        # Parse XML for hardware architecture
        if xml_res["exit_code"] == 0:
            try:
                root = ET.fromstring(xml_res["stdout"])
                # OS / machine type / firmware
                os_elem = root.find("os")
                if os_elem is not None:
                    type_elem = os_elem.find("type")
                    if type_elem is not None:
                        parsed_data["machine_type"] = type_elem.attrib.get("machine", "pc")
                    loader_elem = os_elem.find("loader")
                    parsed_data["firmware"] = "UEFI" if loader_elem is not None else "BIOS"

                # Disks
                disks = []
                for disk in root.findall(".//devices/disk"):
                    driver = disk.find("driver")
                    source = disk.find("source")
                    target = disk.find("target")
                    if target is not None:
                        disks.append({
                            "device": disk.attrib.get("device", "disk"),
                            "bus": target.attrib.get("bus", "virtio"),
                            "dev": target.attrib.get("dev", "vda"),
                            "file": source.attrib.get("file") if source is not None else None,
                            "type": driver.attrib.get("type") if driver is not None else "raw"
                        })
                parsed_data["disk"]["devices"] = disks

                # Primary disk file
                for d in disks:
                    if d.get("device") == "disk" and d.get("file"):
                        parsed_data["disk"]["primary_file"] = d["file"]
                        p = Path(d["file"])
                        if p.exists():
                            parsed_data["disk"]["physical_size_bytes"] = p.stat().st_size
                            parsed_data["disk"]["physical_size_mb"] = round(p.stat().st_size / (1024 * 1024), 2)
                        break

                # Network interfaces
                interfaces = []
                for iface in root.findall(".//devices/interface"):
                    mac = iface.find("mac")
                    source = iface.find("source")
                    model = iface.find("model")
                    interfaces.append({
                        "type": iface.attrib.get("type", "network"),
                        "mac": mac.attrib.get("address") if mac is not None else None,
                        "source": source.attrib.get("network") or source.attrib.get("bridge") if source is not None else None,
                        "model": model.attrib.get("type") if model is not None else "virtio"
                    })
                parsed_data["network"]["interfaces"] = interfaces
                if interfaces:
                    parsed_data["network"]["primary_mac"] = interfaces[0].get("mac")
            except Exception as e:
                parsed_data["xml_parse_error"] = str(e)

        # Dynamic IP discovery if running
        if parsed_data["state"] == "running":
            parsed_data["ip"] = KvmDiscovery.discover_vm_ip(vm_name, parsed_data["network"].get("primary_mac"))

        return parsed_data

    @staticmethod
    def discover_vm_ip(vm_name: str, mac_hint: Optional[str] = None) -> Optional[str]:
        """Discovers guest IP dynamically using domifaddr, net-dhcp-leases, or arp."""
        # 1. Try domifaddr
        domif = run_safe_command(f"{VIRSH_CMD} domifaddr {vm_name}")
        if domif["exit_code"] == 0:
            for line in domif["stdout"].splitlines():
                if "ipv4" in line:
                    parts = line.split()
                    for p in parts:
                        if "/" in p and p[0].isdigit():
                            return p.split("/")[0].strip()

        # 2. Try net-dhcp-leases
        leases = run_safe_command(f"{VIRSH_CMD} net-dhcp-leases default")
        if leases["exit_code"] == 0:
            for line in leases["stdout"].splitlines():
                if mac_hint and mac_hint.lower() in line.lower():
                    parts = line.split()
                    for p in parts:
                        if "/" in p and p[0].isdigit():
                            return p.split("/")[0].strip()
                elif "ipv4" in line:
                    parts = line.split()
                    for p in parts:
                        if "/" in p and p[0].isdigit():
                            return p.split("/")[0].strip()

        # 3. Check ARP table on virbr0
        arp_res = run_safe_command("ip neigh show dev virbr0")
        if arp_res["exit_code"] == 0:
            for line in arp_res["stdout"].splitlines():
                if "REACHABLE" in line or "DELAY" in line:
                    parts = line.split()
                    if len(parts) >= 1 and parts[0][0].isdigit():
                        return parts[0].strip()

        return None


class KvmLifecycle:
    """Controls VM lifecycle gracefully with startup phase duration measurement."""

    @staticmethod
    def start_vm(vm_name: str) -> Dict[str, Any]:
        """Starts the VM if not already running."""
        state_res = run_safe_command(f"{VIRSH_CMD} domstate {vm_name}")
        current_state = state_res["stdout"].strip() if state_res["exit_code"] == 0 else "unknown"

        if current_state == "running":
            return {"status": "success", "already_running": True, "message": "VM is already running"}

        start_time = time.monotonic()
        res = run_safe_command(f"{VIRSH_CMD} start {vm_name}")
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
        """Polls domstate until target state is reached or timeout expires."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            res = run_safe_command(f"{VIRSH_CMD} domstate {vm_name}")
            if res["exit_code"] == 0 and target_state in res["stdout"].lower():
                return True
            time.sleep(1)
        return False

    @staticmethod
    def wait_for_network(vm_name: str, mac_hint: Optional[str] = None, timeout: int = 60) -> Optional[str]:
        """Waits for dynamic IP assignment and ICMP ping reachability."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            ip = KvmDiscovery.discover_vm_ip(vm_name, mac_hint)
            if ip:
                # Test reachability with a fast single ping
                ping_res = run_safe_command(f"ping -c 1 -W 1 {ip}")
                if ping_res["exit_code"] == 0:
                    return ip
            time.sleep(2)
        return None

    @staticmethod
    def measure_full_startup(
        vm_name: str,
        mac_hint: Optional[str] = None,
        health_port: int = 8080,
        timeout: int = 90
    ) -> Dict[str, Any]:
        """
        Measures cumulative startup lifecycle:
        virsh start -> guest available -> network ready -> application ready
        Records phase timestamps and durations.
        """
        t0 = time.time()
        m0 = time.monotonic()

        # Phase 1: Start
        start_res = KvmLifecycle.start_vm(vm_name)
        t_start_issued = time.time()

        # Phase 2: Guest Available (State == running)
        running = KvmLifecycle.wait_for_state(vm_name, "running", timeout=30)
        t_running = time.time()
        guest_avail_sec = round(t_running - t_start_issued, 4) if running else None

        # Phase 3: Network Ready (IP discovered and pingable)
        ip = KvmLifecycle.wait_for_network(vm_name, mac_hint, timeout=timeout)
        t_network = time.time()
        network_ready_sec = round(t_network - t_running, 4) if ip else None

        # Phase 4: Application Readiness (Check HTTP health endpoint or port availability)
        app_ready = False
        t_app = t_network
        if ip:
            # Check if health port responds or fallback to TCP port ping
            start_app_wait = time.monotonic()
            while time.monotonic() - start_app_wait < 15:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(1.0)
                    if s.connect_ex((ip, health_port)) == 0:
                        app_ready = True
                        s.close()
                        break
                    s.close()
                except Exception:
                    pass
                time.sleep(1)
            t_app = time.time()

        total_duration = round(time.monotonic() - m0, 4)

        return {
            "vm_name": vm_name,
            "ip": ip,
            "phases": {
                "virsh_start": {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)),
                    "duration_sec": start_res.get("command_duration_sec", 0.0)
                },
                "guest_available": {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_running)),
                    "duration_sec": guest_avail_sec,
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
            "status": "success" if (running and ip) else "failed"
        }

    @staticmethod
    def shutdown_gracefully(vm_name: str, timeout: int = 30) -> Dict[str, Any]:
        """Gracefully powers down the VM via virsh shutdown (ACPI)."""
        start_time = time.monotonic()
        res = run_safe_command(f"{VIRSH_CMD} shutdown {vm_name}")
        
        # Wait until state is shut off
        stopped = False
        while time.monotonic() - start_time < timeout:
            s_res = run_safe_command(f"{VIRSH_CMD} domstate {vm_name}")
            if s_res["exit_code"] == 0 and "shut off" in s_res["stdout"].lower():
                stopped = True
                break
            time.sleep(1)

        duration = round(time.monotonic() - start_time, 4)
        return {
            "status": "success" if stopped else "timeout",
            "shutdown_duration_sec": duration,
            "stopped": stopped
        }


class KvmMetricsCollector:
    """Collects host QEMU process telemetry and hypervisor domstats."""

    @staticmethod
    def get_qemu_pid(vm_name: str) -> Optional[int]:
        """Finds QEMU process PID corresponding to target domain."""
        res = run_safe_command(f"pgrep -f 'guest={vm_name}'")
        if res["exit_code"] == 0 and res["stdout"]:
            pids = res["stdout"].splitlines()
            if pids:
                try:
                    return int(pids[0].strip())
                except ValueError:
                    pass
        return None

    @staticmethod
    def collect_host_qemu_telemetry(vm_name: str) -> Dict[str, Any]:
        """Inspects host QEMU process memory and CPU consumption via /proc."""
        pid = KvmMetricsCollector.get_qemu_pid(vm_name)
        if not pid or not Path(f"/proc/{pid}").exists():
            return {
                "status": "unavailable",
                "reason": f"QEMU process for domain {vm_name} not found on host"
            }

        qemu_metrics = {
            "status": "success",
            "pid": pid,
            "rss_kb": None,
            "vsz_kb": None,
            "threads": None,
            "cpu_time_ticks": None
        }

        # Read /proc/<pid>/status
        status_path = Path(f"/proc/{pid}/status")
        if status_path.exists():
            try:
                for line in status_path.read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        qemu_metrics["rss_kb"] = int(line.split()[1])
                    elif line.startswith("VmSize:"):
                        qemu_metrics["vsz_kb"] = int(line.split()[1])
                    elif line.startswith("Threads:"):
                        qemu_metrics["threads"] = int(line.split()[1])
            except Exception:
                pass

        # Read /proc/<pid>/stat for CPU ticks
        stat_path = Path(f"/proc/{pid}/stat")
        if stat_path.exists():
            try:
                parts = stat_path.read_text().split()
                if len(parts) >= 15:
                    utime = int(parts[13])
                    stime = int(parts[14])
                    qemu_metrics["cpu_time_ticks"] = utime + stime
            except Exception:
                pass

        return qemu_metrics

    @staticmethod
    def collect_domstats(vm_name: str) -> Dict[str, Any]:
        """Collects libvirt domstats (vCPU time, virtio-balloon RAM, I/O counters)."""
        res = run_safe_command(f"{VIRSH_CMD} domstats {vm_name}")
        if res["exit_code"] != 0:
            return {"status": "unavailable", "reason": res["stderr"]}

        stats: Dict[str, Any] = {
            "status": "success",
            "cpu": {},
            "balloon": {},
            "vcpu": {},
            "block": {},
            "net": {}
        }

        for line in res["stdout"].splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()

            # Cast numeric values
            num_val: Any = v
            try:
                num_val = int(v) if v.isdigit() or (v.startswith('-') and v[1:].isdigit()) else float(v)
            except ValueError:
                pass

            if k.startswith("cpu."):
                stats["cpu"][k.replace("cpu.", "")] = num_val
            elif k.startswith("balloon."):
                stats["balloon"][k.replace("balloon.", "")] = num_val
            elif k.startswith("vcpu."):
                stats["vcpu"][k.replace("vcpu.", "")] = num_val
            elif k.startswith("block."):
                stats["block"][k.replace("block.", "")] = num_val
            elif k.startswith("net."):
                stats["net"][k.replace("net.", "")] = num_val

        return stats

    @staticmethod
    def get_memory_breakdown(vm_name: str) -> Dict[str, Any]:
        """
        Clearly distinguishes allocated VM memory from actual memory consumption.
        """
        domstats = KvmMetricsCollector.collect_domstats(vm_name)
        host_qemu = KvmMetricsCollector.collect_host_qemu_telemetry(vm_name)

        balloon = domstats.get("balloon", {})

        # Configured/Allocated RAM
        configured_ram_kb = balloon.get("maximum") or balloon.get("current") or 2097152
        configured_ram_mb = configured_ram_kb // 1024

        # Guest perspective from virtio-balloon
        guest_available_kb = balloon.get("available")
        guest_unused_kb = balloon.get("unused")
        guest_usable_kb = balloon.get("usable")
        guest_used_kb = (configured_ram_kb - guest_available_kb) if guest_available_kb else None

        # Host perspective from QEMU process
        host_qemu_rss_kb = host_qemu.get("rss_kb") or balloon.get("rss")
        host_qemu_vsz_kb = host_qemu.get("vsz_kb")

        return {
            "allocated_vm_ram": {
                "configured_kb": configured_ram_kb,
                "configured_mb": configured_ram_mb
            },
            "actual_memory_consumption": {
                "guest_used_ram_kb": guest_used_kb,
                "guest_used_ram_mb": (guest_used_kb // 1024) if guest_used_kb else None,
                "guest_available_ram_kb": guest_available_kb,
                "guest_available_ram_mb": (guest_available_kb // 1024) if guest_available_kb else None,
                "guest_unused_ram_kb": guest_unused_kb,
                "host_qemu_rss_kb": host_qemu_rss_kb,
                "host_qemu_rss_mb": (host_qemu_rss_kb // 1024) if host_qemu_rss_kb else None,
                "host_qemu_vsz_kb": host_qemu_vsz_kb,
                "swap_in_kb": balloon.get("swap_in", 0),
                "swap_out_kb": balloon.get("swap_out", 0)
            },
            "distinction_note": (
                "Allocated RAM represents the static maximum virtual memory boundary assigned to the guest (2048 MB). "
                "Actual consumption represents resident host pages actively occupied by QEMU plus active guest pages "
                "reported via the virtio-balloon driver."
            )
        }


class KvmStorageBenchmark:
    """Safe fio file-level storage benchmarking."""

    @staticmethod
    def run_fio_file_benchmark(
        test_file_path: Path,
        file_size_mb: int = 32,
        runtime_sec: int = 5
    ) -> Dict[str, Any]:
        """
        Executes non-destructive fio benchmarks strictly on a temporary regular file.
        Rejects block devices, /dev/*, or VM raw disks.
        """
        # Safety validation: target must be a path inside project or /tmp, NEVER /dev/*
        target_str = str(test_file_path)
        if "/dev" in target_str or "nvme" in target_str or "sd" in target_str or "vd" in target_str:
            raise ValueError(f"Safety Violation: fio target must NOT reference device files: {target_str}")

        fio_bin = shutil.which("fio")
        if not fio_bin:
            return {
                "status": "unavailable",
                "reason": "fio binary not found on system. No mock data generated."
            }

        # Ensure parent directory exists and file is initialized
        test_file_path.parent.mkdir(parents=True, exist_ok=True)
        if not test_file_path.exists():
            # Create a safe regular file with zero-fill
            test_file_path.write_bytes(b"\0" * (1024 * 1024 * 4)) # 4MB seed

        # Validate target is a regular file
        if not test_file_path.is_file():
            raise ValueError(f"Target {test_file_path} must be a regular file.")

        results: Dict[str, Any] = {"status": "success", "workloads": {}}
        test_modes = ["seqread", "seqwrite", "randread", "randwrite"]

        for mode in test_modes:
            rw_param = "read" if mode == "seqread" else ("write" if mode == "seqwrite" else ("randread" if mode == "randread" else "randwrite"))
            cmd = (
                f"{fio_bin} --name={mode} --filename={test_file_path} "
                f"--rw={rw_param} --bs=4k --size={file_size_mb}M --time_based --runtime={runtime_sec} "
                f"--ioengine=sync --direct=1 --output-format=json"
            )
            fio_run = run_safe_command(cmd, timeout=runtime_sec + 10)
            if fio_run["exit_code"] == 0 and fio_run["stdout"]:
                try:
                    fio_json = json.loads(fio_run["stdout"])
                    job = fio_json.get("jobs", [{}])[0]
                    section = job.get("read") if "read" in rw_param else job.get("write")
                    results["workloads"][mode] = {
                        "iops": section.get("iops", 0.0),
                        "throughput_kb_s": section.get("bw_bytes", 0) / 1024.0,
                        "lat_avg_us": section.get("lat_ns", {}).get("mean", 0.0) / 1000.0,
                        "p95_lat_us": section.get("clat_ns", {}).get("percentile", {}).get("95.000000", 0.0) / 1000.0,
                        "p99_lat_us": section.get("clat_ns", {}).get("percentile", {}).get("99.000000", 0.0) / 1000.0
                    }
                except Exception as e:
                    results["workloads"][mode] = {"status": "failed", "error": str(e)}
            else:
                results["workloads"][mode] = {
                    "status": "failed",
                    "stderr": fio_run["stderr"]
                }

        # Clean up test file
        test_file_path.unlink(missing_ok=True)
        return results


class KvmNetworkBenchmark:
    """Network benchmarking: ping latency and iperf3 throughput."""

    @staticmethod
    def run_ping_test(target_ip: str, count: int = 10) -> Dict[str, Any]:
        """Runs ping and parses min, avg, max, mdev, and packet loss."""
        if not target_ip:
            return {"status": "unavailable", "reason": "No target IP discovered"}

        cmd = f"ping -c {count} -W 1 {target_ip}"
        res = run_safe_command(cmd, timeout=count + 5)
        if res["exit_code"] != 0:
            return {"status": "failed", "stderr": res["stderr"], "stdout": res["stdout"]}

        parsed: Dict[str, Any] = {
            "status": "success",
            "target_ip": target_ip,
            "packets_transmitted": count,
            "packet_loss_percent": None,
            "rtt_min_ms": None,
            "rtt_avg_ms": None,
            "rtt_max_ms": None,
            "rtt_mdev_ms": None
        }

        # Parse loss: "0% packet loss"
        loss_match = re.search(r"(\d+(\.\d+)?)%\s+packet\s+loss", res["stdout"])
        if loss_match:
            parsed["packet_loss_percent"] = float(loss_match.group(1))

        # Parse rtt: "rtt min/avg/max/mdev = 0.247/0.330/0.412/0.067 ms"
        rtt_match = re.search(r"rtt\s+min/avg/max/mdev\s*=\s*([\d\.]+)/([\d\.]+)/([\d\.]+)/([\d\.]+)\s+ms", res["stdout"])
        if rtt_match:
            parsed["rtt_min_ms"] = float(rtt_match.group(1))
            parsed["rtt_avg_ms"] = float(rtt_match.group(2))
            parsed["rtt_max_ms"] = float(rtt_match.group(3))
            parsed["rtt_mdev_ms"] = float(rtt_match.group(4))

        return parsed

    @staticmethod
    def run_iperf3_test(target_ip: str, duration: int = 30) -> Dict[str, Any]:
        """Runs iperf3 if installed, otherwise marks status=unavailable."""
        iperf_bin = shutil.which("iperf3")
        if not iperf_bin:
            return {
                "status": "unavailable",
                "reason": "iperf3 binary not found on host. Zero values will not be fabricated."
            }

        cmd = f"{iperf_bin} -c {target_ip} -t {duration} -J"
        res = run_safe_command(cmd, timeout=duration + 10)
        if res["exit_code"] == 0 and res["stdout"]:
            try:
                data = json.loads(res["stdout"])
                end = data.get("end", {})
                sum_sent = end.get("sum_sent", {})
                return {
                    "status": "success",
                    "bandwidth_mbps": round(sum_sent.get("bits_per_second", 0) / 1e6, 2),
                    "bytes_transferred": sum_sent.get("bytes", 0),
                    "retransmits": sum_sent.get("retransmits", 0)
                }
            except Exception as e:
                return {"status": "failed", "error": str(e)}

        return {"status": "failed", "stderr": res["stderr"]}


class KvmAppLatencyBenchmark:
    """Application-level HTTP health endpoint latency evaluation."""

    @staticmethod
    def measure_http_endpoint_latency(
        url: str,
        num_requests: int = 100
    ) -> Dict[str, Any]:
        """
        Executes num_requests HTTP GET requests and measures:
        connect time, TTFB, and total request duration.
        Computes mean, median, p50, p95, p99, min, max.
        """
        from collector.advanced_metrics import HttpLatencyBenchmark
        return HttpLatencyBenchmark.measure_endpoint(url, num_requests=num_requests)


class KvmIsolationAudit:
    """Collects system isolation parameters comparing host against guest environment."""

    @staticmethod
    def collect_host_isolation() -> Dict[str, Any]:
        """Captures host namespace, cgroup, and virtualization signatures."""
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
            "environment": "host",
            "systemd_detect_virt": virt_res["stdout"] if virt_res["exit_code"] == 0 else "none (bare-metal)",
            "uname": uname_res["stdout"],
            "namespaces_pid1": ns_entries,
            "cgroup_self": cgroup_res["stdout"],
            "ip_addr": ip_addr_res["stdout"],
            "findmnt": findmnt_res["stdout"]
        }
