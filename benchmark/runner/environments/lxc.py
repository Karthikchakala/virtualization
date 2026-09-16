#!/usr/bin/env python3
"""
benchmark/runner/environments/lxc.py - Native LXC OS-Level Container Adapter.

Orchestrates native Linux Containers (OS-level virtualization) via native LXC
tooling (lxc-info, lxc-start, lxc-stop, lxc-attach) and the Linux kernel's
unified cgroups v2 hierarchy.
Strictly native LXC: NO Docker, NO LXD, NO SSH required for execution.
Proves empirical kernel sharing with near-zero virtualization overhead.
"""

import hashlib
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

from .base import BaseEnvironmentAdapter, ExecutionResult, IdentityResult, NormalizedState
from .transport import LxcAttachTransport
from ..config import EnvironmentConfig, mask_secret


class LxcAdapter(BaseEnvironmentAdapter):
    """
    Adapter for Native LXC OS-level virtualization.
    """

    def __init__(self, config: Optional[EnvironmentConfig] = None):
        if config is None:
            config = EnvironmentConfig(
                name="lxc",
                display_name="Native Linux Containers (LXC)",
                classification="OS-Level Virtualization (Containerization)",
                virtualization_type="lxc",
                transport="lxc-attach",
                target_path="/tmp/cc2_workloads",
                container_name="lxc-ubuntu"
            )
        super().__init__(config)
        self.container_name = config.container_name or "lxc-ubuntu"
        self.rootfs_path = Path(f"/var/lib/lxc/{self.container_name}/rootfs")
        self.cgroup2_root = Path("/sys/fs/cgroup")

        # Initialize transport strictly with lxc-attach
        self.transport = LxcAttachTransport(
            container_name=self.container_name,
            rootfs_path=self.rootfs_path
        )

    def _run_lxc_cmd(self, cmd_name: str, args: List[str], timeout: int = 10) -> subprocess.CompletedProcess:
        """Runs a safe, non-destructive native LXC CLI command."""
        bin_path = shutil.which(cmd_name) or cmd_name
        full_cmd = [bin_path] + args
        return subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)

    def get_status(self) -> str:
        """
        Queries container status via lxc-info -n <name> -s.
        Returns NormalizedState: 'running', 'stopped', 'unavailable', 'error'.
        """
        if not shutil.which("lxc-info"):
            return NormalizedState.UNAVAILABLE

        try:
            res = self._run_lxc_cmd("lxc-info", ["-n", self.container_name, "-s"], timeout=5)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if "State:" in line:
                        raw_state = line.split(":", 1)[1].strip().upper()
                        if raw_state == "RUNNING":
                            return NormalizedState.RUNNING
                        elif raw_state in ("STOPPED", "FROZEN"):
                            return NormalizedState.STOPPED
                        else:
                            return NormalizedState.UNKNOWN

            # Fallback: check if container directory exists on disk
            container_dir = Path(f"/var/lib/lxc/{self.container_name}")
            if container_dir.exists():
                return NormalizedState.STOPPED

            return NormalizedState.UNAVAILABLE
        except Exception:
            return NormalizedState.ERROR

    def verify(self) -> bool:
        """
        Verifies lxc-info and lxc-attach CLI availability and container registration.
        """
        if not shutil.which("lxc-info") or not shutil.which("lxc-attach"):
            return False

        try:
            # Check if container is recognized by lxc-info
            res = self._run_lxc_cmd("lxc-info", ["-n", self.container_name, "-s"], timeout=5)
            if res.returncode == 0:
                return True

            # Or container folder exists
            container_dir = Path(f"/var/lib/lxc/{self.container_name}")
            return container_dir.exists() and container_dir.is_dir()
        except Exception:
            return False

    def prepare(self) -> Dict[str, Any]:
        """
        Ensures LXC container is running and lxc-attach is functional.
        If stopped, starts container via lxc-start and measures startup phases.
        """
        status = self.get_status()
        if status == NormalizedState.UNAVAILABLE:
            return {
                "status": "unavailable",
                "ready": False,
                "reason": f"LXC container '{self.container_name}' not found on host"
            }

        if status == NormalizedState.RUNNING:
            test_res = self.transport.execute("uname -r", timeout=5)
            return {
                "status": "already_running",
                "ready": test_res.success,
                "attach_ready": test_res.success
            }

        if status == NormalizedState.STOPPED:
            timings: Dict[str, float] = {}
            t0 = time.perf_counter()

            # Phase 1: lxc-start -d
            start_res = self._run_lxc_cmd("lxc-start", ["-n", self.container_name, "-d"], timeout=15)
            timings["lxc_start_sec"] = time.perf_counter() - t0
            if start_res.returncode != 0:
                return {
                    "status": "failed",
                    "ready": False,
                    "reason": f"lxc-start failed: {start_res.stderr.strip()}",
                    "timings": timings
                }

            # Phase 2: Wait for state RUNNING
            timeout_sec = self.config.readiness_timeout_sec
            running_acquired = False
            while time.perf_counter() - t0 < timeout_sec:
                if self.get_status() == NormalizedState.RUNNING:
                    running_acquired = True
                    break
                time.sleep(0.5)

            timings["state_running_sec"] = time.perf_counter() - t0
            if not running_acquired:
                return {
                    "status": "timeout",
                    "ready": False,
                    "reason": "Container did not reach 'RUNNING' state in time",
                    "timings": timings
                }

            # Phase 3: Wait for lxc-attach responsiveness
            attach_ready = False
            while time.perf_counter() - t0 < timeout_sec:
                if self.transport.execute("/bin/true", timeout=3).success:
                    attach_ready = True
                    break
                time.sleep(1)

            timings["attach_ready_sec"] = time.perf_counter() - t0
            return {
                "status": "running" if attach_ready else "attach_failed",
                "ready": attach_ready,
                "timings": timings
            }

        return {"status": status, "ready": False}

    def deploy_workload(self, local_path: Union[str, Path], target_dest: Optional[str] = None) -> Dict[str, Any]:
        """
        Deploys workload binary into container via lxc-attach or direct rootfs copy.
        Verifies SHA256 checksum inside the container.
        """
        src = Path(local_path).resolve()
        if not src.exists() or not src.is_file():
            return {
                "deployed": False,
                "error": f"Local binary '{src}' does not exist",
                "destination": None
            }

        remote_dest = target_dest or f"{self.target_path}/{src.name}"

        # 1. Compute local SHA256
        h = hashlib.sha256()
        with open(src, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        src_sha256 = h.hexdigest()

        # 2. Check remote hash
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
                "error": "Failed to transfer binary into LXC container",
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
        Executes command inside container via LxcAttachTransport.
        """
        return self.transport.execute(cmd, timeout=timeout, env_vars=env_vars)

    def _locate_cgroup_dir(self) -> Optional[Path]:
        """Finds cgroup v2 directory for the container payload."""
        candidates = [
            self.cgroup2_root / "lxc.payload" / self.container_name,
            self.cgroup2_root / f"lxc.payload.{self.container_name}",
            self.cgroup2_root / "lxc" / self.container_name,
            self.cgroup2_root / self.container_name
        ]
        for c in candidates:
            if c.exists() and c.is_dir():
                return c
        return None

    def collect_metrics(
        self,
        pid: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Collects Unified Cgroups v2 telemetry:
        cpu.stat (usage_usec, user_usec, system_usec),
        memory.current, memory.peak.
        """
        metrics: Dict[str, Any] = {
            "timestamp": time.time(),
            "environment": self.name,
            "container_name": self.container_name
        }

        cg_dir = self._locate_cgroup_dir()
        if cg_dir:
            metrics["cgroup_path"] = str(cg_dir)

            # cpu.stat
            cpu_stat_file = cg_dir / "cpu.stat"
            if cpu_stat_file.exists():
                try:
                    for line in cpu_stat_file.read_text().splitlines():
                        parts = line.split()
                        if len(parts) == 2:
                            k, v = parts[0], parts[1]
                            try:
                                metrics[f"cgroup_{k}"] = int(v)
                            except ValueError:
                                pass
                except Exception:
                    pass

            # memory.current
            mem_current_file = cg_dir / "memory.current"
            if mem_current_file.exists():
                try:
                    metrics["cgroup_memory_current_bytes"] = int(mem_current_file.read_text().strip())
                except Exception:
                    pass

            # memory.peak
            mem_peak_file = cg_dir / "memory.peak"
            if mem_peak_file.exists():
                try:
                    metrics["cgroup_memory_peak_bytes"] = int(mem_peak_file.read_text().strip())
                except Exception:
                    pass
        else:
            metrics["cgroup_status"] = "cgroup_dir_not_found"

        return metrics

    def cleanup(self) -> bool:
        """
        Non-destructive quenching of lingering workload processes inside container.
        """
        if self.get_status() == NormalizedState.RUNNING:
            self.transport.execute("pkill -f '_workload' || true", timeout=5)
        return True

    def get_identity(self) -> IdentityResult:
        """
        Introspects container identity and proves Linux kernel sharing.
        """
        # Discover host kernel for proof of sharing
        host_kernel = None
        try:
            h_res = subprocess.run(["uname", "-r"], capture_output=True, text=True, timeout=3)
            if h_res.returncode == 0:
                host_kernel = h_res.stdout.strip()
        except Exception:
            pass

        container_kernel = None
        hostname = None
        virt_detect = "lxc"
        ip_addr = None

        if self.get_status() == NormalizedState.RUNNING:
            # Query kernel inside container
            k_res = self.transport.execute("uname -r", timeout=5)
            if k_res.success:
                container_kernel = k_res.stdout.strip()

            h_res = self.transport.execute("hostname", timeout=5)
            if h_res.success:
                hostname = h_res.stdout.strip()

            v_res = self.transport.execute("systemd-detect-virt", timeout=5)
            if v_res.success and v_res.stdout.strip():
                virt_detect = v_res.stdout.strip()

            # Query container IP via lxc-info -i
            try:
                ip_res = self._run_lxc_cmd("lxc-info", ["-n", self.container_name, "-i"], timeout=3)
                if ip_res.returncode == 0:
                    for line in ip_res.stdout.splitlines():
                        if "IP:" in line:
                            ip_addr = line.split(":", 1)[1].strip()
                            break
            except Exception:
                pass

        # Kernel is shared if container matches host kernel
        is_shared = (host_kernel is not None and container_kernel == host_kernel)

        return IdentityResult(
            environment=self.name,
            classification=self.classification,
            virtualization_type=self.virtualization_type,
            kernel_release=container_kernel or host_kernel,
            os_release="Ubuntu (Native LXC Container)",
            hostname=hostname or self.container_name,
            vcpus=os.cpu_count() or 1,
            memory_mb=0,
            ip_address=ip_addr,
            mac_address=None,
            hypervisor_version="Native LXC (cgroups v2)",
            systemd_detect_virt=virt_detect,
            is_shared_kernel=is_shared,
            raw_details={
                "container_name": self.container_name,
                "host_kernel": host_kernel,
                "container_kernel": container_kernel,
                "kernel_shared": is_shared
            }
        )
