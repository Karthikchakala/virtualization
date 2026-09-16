#!/usr/bin/env python3
"""
benchmark/runner/environments/kvm.py - KVM/QEMU Hardware Virtualization Adapter.

Orchestrates KVM/QEMU virtual machines (Type-1-like hardware-assisted virtualization)
via libvirt (virsh) and non-interactive SSH transport.
Strictly non-destructive: never runs virsh destroy --remove-all-storage or undefine.
"""

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

from .base import BaseEnvironmentAdapter, ExecutionResult, IdentityResult, NormalizedState
from .transport import SSHTransport
from ..config import EnvironmentConfig, mask_secret


class KvmAdapter(BaseEnvironmentAdapter):
    """
    Adapter for KVM/QEMU hardware-assisted virtualization.
    """

    def __init__(self, config: Optional[EnvironmentConfig] = None):
        if config is None:
            config = EnvironmentConfig(
                name="kvm",
                display_name="KVM/QEMU Hardware Virtualization",
                classification="Hardware-assisted Virtualization (Type-1-like)",
                virtualization_type="kvm",
                transport="ssh",
                target_path="/tmp/cc2_workloads",
                vm_name="ubuntu24.04",
                ssh_port=22,
                ssh_user="karthik-chakala"
            )
        super().__init__(config)
        self.vm_name = config.vm_name or "ubuntu24.04"
        self.virsh_cmd = "virsh -c qemu:///system"

        # Initialize transport with configured or default settings
        self.transport = SSHTransport(
            host=config.ssh_host or "",
            port=config.ssh_port or 22,
            user=config.ssh_user,
            key_path=config.ssh_key_path,
            password=config.ssh_password,
            connect_timeout_sec=5
        )

    def _run_virsh(self, subcommand: str, timeout: int = 10) -> subprocess.CompletedProcess:
        """Runs a safe, read-only or lifecycle virsh command."""
        cmd = f"{self.virsh_cmd} {subcommand}"
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)

    def discover_ip(self) -> Optional[str]:
        """
        Dynamically discovers guest IP from virsh net-dhcp-leases or virbr0.status.
        """
        if self.config.ssh_host and self.config.ssh_host.strip():
            return self.config.ssh_host.strip()

        # Attempt 1: virsh net-dhcp-leases default
        try:
            res = self._run_virsh("net-dhcp-leases default", timeout=5)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if "ipv4" in line:
                        parts = line.split()
                        for p in parts:
                            if "/" in p:
                                cand_ip = p.split("/")[0]
                                if cand_ip.replace(".", "").isdigit():
                                    return cand_ip
        except Exception:
            pass

        # Attempt 2: virbr0.status file
        virbr_status = Path("/var/lib/libvirt/dnsmasq/virbr0.status")
        if virbr_status.exists():
            try:
                data = json.loads(virbr_status.read_text())
                if isinstance(data, list) and data:
                    return data[-1].get("ip-address")
            except Exception:
                pass

        return None

    def _ensure_transport_host(self) -> bool:
        """Ensures the SSH transport is pointed at the current guest IP."""
        if not self.transport.host:
            ip = self.discover_ip()
            if ip:
                self.transport.host = ip
                return True
            return False
        return True

    def get_status(self) -> str:
        """
        Queries VM status via virsh domstate.
        Returns NormalizedState: 'running', 'stopped', 'unavailable', 'error'.
        """
        if not shutil.which("virsh"):
            return NormalizedState.UNAVAILABLE

        try:
            res = self._run_virsh(f"domstate {self.vm_name}", timeout=5)
            if res.returncode != 0:
                return NormalizedState.UNAVAILABLE

            raw_state = res.stdout.strip().lower()
            if "running" in raw_state:
                return NormalizedState.RUNNING
            elif any(s in raw_state for s in ["shut off", "shutoff", "pmsuspended", "paused"]):
                return NormalizedState.STOPPED
            else:
                return NormalizedState.UNKNOWN
        except Exception:
            return NormalizedState.ERROR

    def verify(self) -> bool:
        """
        Verifies virsh availability and VM existence.
        """
        if not shutil.which("virsh"):
            return False

        try:
            res = self._run_virsh(f"dominfo {self.vm_name}", timeout=5)
            return res.returncode == 0
        except Exception:
            return False

    def prepare(self) -> Dict[str, Any]:
        """
        Ensures KVM VM is running and accessible via SSH.
        If stopped, issues virsh start and measures boot phase timings.
        """
        status = self.get_status()
        if status == NormalizedState.UNAVAILABLE:
            return {
                "status": "unavailable",
                "ready": False,
                "reason": f"KVM domain '{self.vm_name}' not available in libvirt"
            }

        if status == NormalizedState.RUNNING:
            self._ensure_transport_host()
            reachable = self.transport.is_reachable(timeout_sec=5)
            return {
                "status": "already_running",
                "ready": reachable,
                "ip": self.transport.host,
                "ssh_ready": reachable
            }

        if status == NormalizedState.STOPPED:
            timings: Dict[str, float] = {}
            t0 = time.perf_counter()

            # Phase 1: virsh start
            start_res = self._run_virsh(f"start {self.vm_name}", timeout=15)
            timings["virsh_start_sec"] = time.perf_counter() - t0
            if start_res.returncode != 0:
                return {
                    "status": "failed",
                    "ready": False,
                    "reason": f"virsh start failed: {start_res.stderr.strip()}",
                    "timings": timings
                }

            # Phase 2: Wait for running state
            timeout_sec = self.config.readiness_timeout_sec
            running_acquired = False
            while time.perf_counter() - t0 < timeout_sec:
                if self.get_status() == NormalizedState.RUNNING:
                    running_acquired = True
                    break
                time.sleep(1)

            timings["state_running_sec"] = time.perf_counter() - t0
            if not running_acquired:
                return {
                    "status": "timeout",
                    "ready": False,
                    "reason": "VM did not reach 'running' state in time",
                    "timings": timings
                }

            # Phase 3: Wait for IP acquisition
            ip_acquired = False
            while time.perf_counter() - t0 < timeout_sec:
                if self._ensure_transport_host():
                    ip_acquired = True
                    break
                time.sleep(1)

            timings["network_ready_sec"] = time.perf_counter() - t0
            if not ip_acquired:
                return {
                    "status": "timeout",
                    "ready": False,
                    "reason": "Failed to resolve guest dynamic IP from DHCP leases",
                    "timings": timings
                }

            # Phase 4: Wait for SSH reachability
            ssh_acquired = False
            while time.perf_counter() - t0 < timeout_sec:
                if self.transport.is_reachable(timeout_sec=3):
                    ssh_acquired = True
                    break
                time.sleep(1.5)

            timings["ssh_ready_sec"] = time.perf_counter() - t0
            return {
                "status": "running" if ssh_acquired else "ssh_failed",
                "ready": ssh_acquired,
                "ip": self.transport.host,
                "timings": timings
            }

        return {"status": status, "ready": False}

    def deploy_workload(self, local_path: Union[str, Path], target_dest: Optional[str] = None) -> Dict[str, Any]:
        """
        Deploys workload binary to KVM guest and verifies SHA256 hash.
        """
        src = Path(local_path).resolve()
        if not src.exists() or not src.is_file():
            return {
                "deployed": False,
                "error": f"Local binary '{src}' does not exist",
                "destination": None
            }

        self._ensure_transport_host()
        remote_dest = target_dest or f"{self.target_path}/{src.name}"

        # 1. Compute local SHA256
        import hashlib
        h = hashlib.sha256()
        with open(src, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        src_sha256 = h.hexdigest()

        # 2. Check if remote binary exists with identical hash
        remote_sha256 = self.transport.compute_sha256(remote_dest)
        if remote_sha256 == src_sha256:
            return {
                "deployed": True,
                "transferred": False,
                "sha256": remote_sha256,
                "destination": remote_dest
            }

        # 3. Transfer binary
        copied = self.transport.copy_file(src, remote_dest)
        if not copied:
            return {
                "deployed": False,
                "error": "Failed to transfer binary via SSHTransport",
                "destination": remote_dest
            }

        # 4. Verify remote hash post-transfer
        remote_sha256 = self.transport.compute_sha256(remote_dest)
        if remote_sha256 != src_sha256:
            return {
                "deployed": False,
                "error": f"Post-deploy hash mismatch: expected {src_sha256}, got {remote_sha256}",
                "destination": remote_dest
            }

        return {
            "deployed": True,
            "transferred": True,
            "sha256": remote_sha256,
            "destination": remote_dest
        }

    def execute(
        self,
        cmd: Union[str, List[str]],
        timeout: int = 60,
        env_vars: Optional[Dict[str, str]] = None
    ) -> ExecutionResult:
        """
        Executes command on KVM guest via SSHTransport.
        """
        self._ensure_transport_host()
        return self.transport.execute(cmd, timeout=timeout, env_vars=env_vars)

    def collect_metrics(
        self,
        pid: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Collects KVM hypervisor telemetry:
        1. Libvirt domstats (cpu.time, balloon RAM).
        2. Host QEMU process PID telemetry (VmRSS, VmSize).
        """
        metrics: Dict[str, Any] = {
            "timestamp": time.time(),
            "environment": self.name,
            "vm_name": self.vm_name
        }

        # 1. Libvirt domstats
        try:
            res = self._run_virsh(f"domstats {self.vm_name} --cpu-total --balloon", timeout=5)
            if res.returncode == 0:
                domstats: Dict[str, Any] = {}
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if "=" in line:
                        k, v = line.split("=", 1)
                        domstats[k.strip()] = v.strip()
                metrics["domstats"] = domstats
                if "cpu.time" in domstats:
                    try:
                        metrics["cpu_time_ns"] = int(domstats["cpu.time"])
                    except ValueError:
                        pass
                if "balloon.current" in domstats:
                    try:
                        metrics["balloon_current_kb"] = int(domstats["balloon.current"])
                    except ValueError:
                        pass
        except Exception as e:
            metrics["domstats_error"] = str(e)

        # 2. Host QEMU PID telemetry
        try:
            # Look up host QEMU process for this VM
            pgrep_cmd = f"pgrep -f 'qemu-system.*{self.vm_name}'"
            p_res = subprocess.run(pgrep_cmd, shell=True, capture_output=True, text=True, timeout=3)
            if p_res.returncode == 0 and p_res.stdout.strip():
                qemu_pid = int(p_res.stdout.strip().splitlines()[0])
                metrics["host_qemu_pid"] = qemu_pid
                status_file = Path(f"/proc/{qemu_pid}/status")
                if status_file.exists():
                    for line in status_file.read_text().splitlines():
                        if line.startswith("VmRSS:"):
                            metrics["host_qemu_rss_kb"] = int(line.split()[1])
                        elif line.startswith("VmSize:"):
                            metrics["host_qemu_vsz_kb"] = int(line.split()[1])
        except Exception:
            pass

        return metrics

    def cleanup(self) -> bool:
        """
        Non-destructive quenching of lingering workload processes.
        """
        self._ensure_transport_host()
        if self.get_status() == NormalizedState.RUNNING and self.transport.is_reachable(timeout_sec=2):
            self.transport.execute("pkill -f '_workload' || true", timeout=5)
        return True

    def get_identity(self) -> IdentityResult:
        """
        Queries KVM guest identity and hardware specifications.
        """
        vcpus = 1
        memory_mb = 0
        mac_address = None

        # Query libvirt dominfo
        try:
            res = self._run_virsh(f"dominfo {self.vm_name}", timeout=5)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if "CPU(s):" in line:
                        try:
                            vcpus = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
                    elif "Max memory:" in line:
                        try:
                            memory_mb = int(line.split(":", 1)[1].replace("KiB", "").strip()) // 1024
                        except ValueError:
                            pass
        except Exception:
            pass

        self._ensure_transport_host()
        kernel = None
        hostname = None
        virt_detect = "kvm"

        if self.get_status() == NormalizedState.RUNNING and self.transport.is_reachable(timeout_sec=3):
            k_res = self.transport.execute("uname -r", timeout=5)
            if k_res.success:
                kernel = k_res.stdout.strip()
            h_res = self.transport.execute("hostname", timeout=5)
            if h_res.success:
                hostname = h_res.stdout.strip()
            v_res = self.transport.execute("systemd-detect-virt", timeout=5)
            if v_res.success and v_res.stdout.strip():
                virt_detect = v_res.stdout.strip()

        return IdentityResult(
            environment=self.name,
            classification=self.classification,
            virtualization_type=self.virtualization_type,
            kernel_release=kernel,
            os_release="Ubuntu (KVM Guest)",
            hostname=hostname or self.vm_name,
            vcpus=vcpus,
            memory_mb=memory_mb,
            ip_address=self.transport.host,
            mac_address=mac_address,
            hypervisor_version="QEMU/KVM (libvirt)",
            systemd_detect_virt=virt_detect,
            is_shared_kernel=False,
            raw_details={
                "vm_name": self.vm_name,
                "libvirt_uri": "qemu:///system"
            }
        )
