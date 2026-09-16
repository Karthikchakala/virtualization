#!/usr/bin/env python3
"""
benchmark/runner/environments/host.py - Host Bare-Metal Environment Adapter.

Provides the reference baseline adapter executing directly on the bare-metal
Ubuntu host. Implements the complete BaseEnvironmentAdapter contract.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

from .base import BaseEnvironmentAdapter, ExecutionResult, IdentityResult, NormalizedState
from .transport import LocalTransport
from ..config import EnvironmentConfig


class HostAdapter(BaseEnvironmentAdapter):
    """
    Adapter for direct bare-metal host execution.
    Serves as the reference baseline for virtualization overhead comparisons.
    """

    def __init__(self, config: Optional[EnvironmentConfig] = None):
        if config is None:
            # Default host configuration
            config = EnvironmentConfig(
                name="host",
                display_name="Host Ubuntu (Bare-Metal)",
                classification="Bare-metal / Hardware Baseline",
                virtualization_type="none",
                transport="local",
                target_path="/tmp/cc2_workloads"
            )
        super().__init__(config)
        self.transport = LocalTransport()

    def verify(self) -> bool:
        """
        Verifies local host execution readiness.
        """
        try:
            # Check basic utilities
            for utility in ["sh", "uname", "sha256sum"]:
                if not shutil.which(utility):
                    return False

            # Verify kernel is introspectable
            res = self.transport.execute("uname -r", timeout=5)
            if not res.success:
                return False

            return True
        except Exception:
            return False

    def prepare(self) -> Dict[str, Any]:
        """
        Ensures local workload scratch directory exists with proper permissions.
        """
        self.target_path.mkdir(parents=True, exist_ok=True)
        return {
            "status": "ready",
            "environment": self.name,
            "target_path": str(self.target_path),
            "prepared": True
        }

    def deploy_workload(self, local_path: Union[str, Path], target_dest: Optional[str] = None) -> Dict[str, Any]:
        """
        Verifies and deploys a workload binary to the host target directory.
        """
        src = Path(local_path).resolve()
        if not src.exists() or not src.is_file():
            return {
                "deployed": False,
                "error": f"Source binary '{src}' does not exist",
                "destination": None
            }

        dest_path = Path(target_dest) if target_dest else (self.target_path / src.name)
        src_sha256 = self.transport.compute_sha256(str(src))

        # Check if already deployed with identical hash
        if dest_path.exists() and dest_path.is_file():
            dest_sha256 = self.transport.compute_sha256(str(dest_path))
            if dest_sha256 == src_sha256:
                return {
                    "deployed": True,
                    "transferred": False,
                    "sha256": dest_sha256,
                    "destination": str(dest_path)
                }

        # Copy binary
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        copied = self.transport.copy_file(src, str(dest_path))
        if not copied:
            return {
                "deployed": False,
                "error": "Failed to copy file to destination",
                "destination": str(dest_path)
            }

        # Verify hash
        dest_sha256 = self.transport.compute_sha256(str(dest_path))
        if dest_sha256 != src_sha256:
            return {
                "deployed": False,
                "error": f"Post-deploy hash mismatch: expected {src_sha256}, got {dest_sha256}",
                "destination": str(dest_path)
            }

        return {
            "deployed": True,
            "transferred": True,
            "sha256": dest_sha256,
            "destination": str(dest_path)
        }

    def execute(
        self,
        cmd: Union[str, List[str]],
        timeout: int = 60,
        env_vars: Optional[Dict[str, str]] = None
    ) -> ExecutionResult:
        """
        Executes command directly on host via LocalTransport.
        """
        return self.transport.execute(cmd, timeout=timeout, env_vars=env_vars)

    def collect_metrics(
        self,
        pid: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Captures host telemetry (CPU ticks, memory, thermals, load averages).
        """
        metrics: Dict[str, Any] = {
            "timestamp": time.time(),
            "loadavg": list(os.getloadavg()),
            "logical_cpus": os.cpu_count() or 1
        }

        # Host memory from /proc/meminfo
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            try:
                for line in meminfo.read_text().splitlines():
                    if line.startswith("MemTotal:"):
                        metrics["host_mem_total_kb"] = int(line.split()[1])
                    elif line.startswith("MemAvailable:"):
                        metrics["host_mem_available_kb"] = int(line.split()[1])
            except Exception:
                pass

        # Host thermals if readable
        thermal_dir = Path("/sys/class/thermal")
        if thermal_dir.exists():
            try:
                temps = {}
                for zone in thermal_dir.glob("thermal_zone*"):
                    temp_f = zone / "temp"
                    type_f = zone / "type"
                    if temp_f.exists() and type_f.exists():
                        z_type = type_f.read_text().strip()
                        z_temp = int(temp_f.read_text().strip()) / 1000.0
                        temps[z_type] = z_temp
                if temps:
                    metrics["thermals_celsius"] = temps
            except Exception:
                pass

        # Target PID telemetry if provided
        if pid and pid > 0:
            pid_status = Path(f"/proc/{pid}/status")
            if pid_status.exists():
                try:
                    for line in pid_status.read_text().splitlines():
                        if line.startswith("VmRSS:"):
                            metrics["pid_vm_rss_kb"] = int(line.split()[1])
                        elif line.startswith("VmSize:"):
                            metrics["pid_vm_size_kb"] = int(line.split()[1])
                except Exception:
                    pass

        return metrics

    def cleanup(self) -> bool:
        """
        Host cleanup is strictly non-destructive.
        """
        return True

    def get_identity(self) -> IdentityResult:
        """
        Introspects host hardware, kernel, and systemd virtualization detection.
        """
        kernel_res = self.transport.execute("uname -r", timeout=5)
        kernel = kernel_res.stdout.strip() if kernel_res.success else None

        hostname_res = self.transport.execute("hostname", timeout=5)
        hostname = hostname_res.stdout.strip() if hostname_res.success else None

        # OS release
        os_release = "Linux"
        os_file = Path("/etc/os-release")
        if os_file.exists():
            try:
                for line in os_file.read_text().splitlines():
                    if line.startswith("PRETTY_NAME="):
                        os_release = line.split("=", 1)[1].strip('"')
                        break
            except Exception:
                pass

        # CPU model
        cpu_model = "Unknown"
        cpu_file = Path("/proc/cpuinfo")
        if cpu_file.exists():
            try:
                for line in cpu_file.read_text().splitlines():
                    if "model name" in line:
                        cpu_model = line.split(":", 1)[1].strip()
                        break
            except Exception:
                pass

        # RAM in MB
        memory_mb = 0
        mem_file = Path("/proc/meminfo")
        if mem_file.exists():
            try:
                for line in mem_file.read_text().splitlines():
                    if line.startswith("MemTotal:"):
                        memory_mb = int(line.split()[1]) // 1024
                        break
            except Exception:
                pass

        # Virtualization detection
        virt_detect = "none (bare-metal)"
        virt_res = self.transport.execute("systemd-detect-virt", timeout=5)
        if virt_res.success and virt_res.stdout.strip():
            virt_detect = virt_res.stdout.strip()

        return IdentityResult(
            environment=self.name,
            classification=self.classification,
            virtualization_type=self.virtualization_type,
            kernel_release=kernel,
            os_release=os_release,
            hostname=hostname,
            vcpus=os.cpu_count() or 1,
            memory_mb=memory_mb,
            ip_address="127.0.0.1",
            mac_address=None,
            hypervisor_version=None,
            systemd_detect_virt=virt_detect,
            is_shared_kernel=False,
            raw_details={
                "cpu_model": cpu_model,
                "logical_cpus": os.cpu_count() or 1
            }
        )

    def get_status(self) -> str:
        """Host is always running."""
        return NormalizedState.RUNNING
