#!/usr/bin/env python3
"""
benchmark/runner/environments/virtualbox.py - VirtualBox Type-2 Hypervisor Adapter.

Orchestrates Oracle VM VirtualBox (Type-2 hosted hypervisor) via VBoxManage CLI
and non-interactive SSH transport (default forwarded port 127.0.0.1:2222).
Strictly non-destructive: never runs VBoxManage unregistervm --delete.
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
from .transport import SSHTransport
from ..config import EnvironmentConfig, mask_secret


class VirtualBoxAdapter(BaseEnvironmentAdapter):
    """
    Adapter for Oracle VM VirtualBox Type-2 hosted hypervisor.
    """

    def __init__(self, config: Optional[EnvironmentConfig] = None):
        if config is None:
            config = EnvironmentConfig(
                name="virtualbox",
                display_name="Oracle VM VirtualBox (Type-2)",
                classification="Hosted Hypervisor (Type-2)",
                virtualization_type="virtualbox",
                transport="ssh",
                target_path="/tmp/cc2_workloads",
                vm_name="Ubuntu-Server-VBox",
                ssh_host="127.0.0.1",
                ssh_port=2222,
                ssh_user="karthik-chakala"
            )
        super().__init__(config)
        self.vm_name = config.vm_name or "Ubuntu-Server-VBox"
        self.vbox_bin = shutil.which("VBoxManage") or "VBoxManage"

        # Initialize SSH transport to forwarded port
        self.transport = SSHTransport(
            host=config.ssh_host or "127.0.0.1",
            port=config.ssh_port or 2222,
            user=config.ssh_user,
            key_path=config.ssh_key_path,
            password=config.ssh_password,
            connect_timeout_sec=5
        )

    def _run_vboxmanage(self, args: List[str], timeout: int = 10) -> subprocess.CompletedProcess:
        """Runs a safe VBoxManage command."""
        cmd = [self.vbox_bin] + args
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def get_status(self) -> str:
        """
        Queries VM status via VBoxManage list runningvms and showvminfo.
        Returns NormalizedState: 'running', 'stopped', 'unavailable', 'error'.
        """
        if not shutil.which("VBoxManage"):
            return NormalizedState.UNAVAILABLE

        try:
            # Check running VMs first
            res = self._run_vboxmanage(["list", "runningvms"], timeout=5)
            if res.returncode == 0 and f'"{self.vm_name}"' in res.stdout:
                return NormalizedState.RUNNING

            # Check if registered at all
            list_res = self._run_vboxmanage(["list", "vms"], timeout=5)
            if list_res.returncode == 0 and f'"{self.vm_name}"' in list_res.stdout:
                return NormalizedState.STOPPED

            return NormalizedState.UNAVAILABLE
        except Exception:
            return NormalizedState.ERROR

    def verify(self) -> bool:
        """
        Verifies VBoxManage CLI tool and VM registration.
        """
        if not shutil.which("VBoxManage"):
            return False

        try:
            res = self._run_vboxmanage(["list", "vms"], timeout=5)
            return res.returncode == 0 and f'"{self.vm_name}"' in res.stdout
        except Exception:
            return False

    def prepare(self) -> Dict[str, Any]:
        """
        Ensures VirtualBox VM is running and accessible via SSH on forwarded port.
        If stopped, issues VBoxManage startvm --type headless and measures phase timings.
        """
        status = self.get_status()
        if status == NormalizedState.UNAVAILABLE:
            return {
                "status": "unavailable",
                "ready": False,
                "reason": f"VirtualBox VM '{self.vm_name}' not registered or VBoxManage missing"
            }

        if status == NormalizedState.RUNNING:
            reachable = self.transport.is_reachable(timeout_sec=5)
            return {
                "status": "already_running",
                "ready": reachable,
                "endpoint": f"{self.transport.host}:{self.transport.port}",
                "ssh_ready": reachable
            }

        if status == NormalizedState.STOPPED:
            timings: Dict[str, float] = {}
            t0 = time.perf_counter()

            # Phase 1: startvm headless
            start_res = self._run_vboxmanage(["startvm", self.vm_name, "--type", "headless"], timeout=20)
            timings["vbox_start_sec"] = time.perf_counter() - t0
            if start_res.returncode != 0:
                return {
                    "status": "failed",
                    "ready": False,
                    "reason": f"VBoxManage startvm failed: {start_res.stderr.strip()}",
                    "timings": timings
                }

            # Phase 2: Polling for running state
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

            # Phase 3: Polling for SSH reachability on forwarded port
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
                "endpoint": f"{self.transport.host}:{self.transport.port}",
                "timings": timings
            }

        return {"status": status, "ready": False}

    def deploy_workload(self, local_path: Union[str, Path], target_dest: Optional[str] = None) -> Dict[str, Any]:
        """
        Deploys workload binary to VirtualBox guest via SSH and verifies SHA256.
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

        # 3. Transfer binary via SSHTransport
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
        Executes command on VirtualBox guest via SSHTransport.
        """
        return self.transport.execute(cmd, timeout=timeout, env_vars=env_vars)

    def collect_metrics(
        self,
        pid: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Collects VirtualBox host process and guest telemetry:
        1. VBoxManage metrics query (RAM, CPU load).
        2. Host VBoxHeadless process PID telemetry (VmRSS, VmSize).
        """
        metrics: Dict[str, Any] = {
            "timestamp": time.time(),
            "environment": self.name,
            "vm_name": self.vm_name
        }

        # 1. VirtualBox internal metrics
        try:
            q_res = self._run_vboxmanage(["metrics", "query", self.vm_name], timeout=5)
            if q_res.returncode == 0:
                metrics["vbox_metrics_raw"] = q_res.stdout
        except Exception:
            pass

        # 2. Host VBoxHeadless PID telemetry
        try:
            p_res = subprocess.run(
                f"pgrep -f 'VBoxHeadless.*{self.vm_name}'",
                shell=True,
                capture_output=True,
                text=True,
                timeout=3
            )
            if p_res.returncode == 0 and p_res.stdout.strip():
                vbox_pid = int(p_res.stdout.strip().splitlines()[0])
                metrics["host_vbox_pid"] = vbox_pid
                status_file = Path(f"/proc/{vbox_pid}/status")
                if status_file.exists():
                    for line in status_file.read_text().splitlines():
                        if line.startswith("VmRSS:"):
                            metrics["host_vbox_rss_kb"] = int(line.split()[1])
                        elif line.startswith("VmSize:"):
                            metrics["host_vbox_vsz_kb"] = int(line.split()[1])
        except Exception:
            pass

        return metrics

    def cleanup(self) -> bool:
        """
        Non-destructive quenching of lingering workload processes inside VM.
        """
        if self.get_status() == NormalizedState.RUNNING and self.transport.is_reachable(timeout_sec=2):
            self.transport.execute("pkill -f '_workload' || true", timeout=5)
        return True

    def get_identity(self) -> IdentityResult:
        """
        Introspects VirtualBox VM topology via showvminfo and remote queries.
        """
        vcpus = 1
        memory_mb = 0
        vbox_version = None

        # Introspect VirtualBox version
        try:
            ver_res = self._run_vboxmanage(["--version"], timeout=3)
            if ver_res.returncode == 0:
                vbox_version = ver_res.stdout.strip()
        except Exception:
            pass

        # Introspect VM topology via showvminfo --machinereadable
        raw_info: Dict[str, str] = {}
        try:
            info_res = self._run_vboxmanage(["showvminfo", self.vm_name, "--machinereadable"], timeout=5)
            if info_res.returncode == 0:
                for line in info_res.stdout.splitlines():
                    if "=" in line:
                        k, _, v = line.partition("=")
                        raw_info[k.strip().strip('"')] = v.strip().strip('"')

                if "cpus" in raw_info:
                    try:
                        vcpus = int(raw_info["cpus"])
                    except ValueError:
                        pass
                if "memory" in raw_info:
                    try:
                        memory_mb = int(raw_info["memory"])
                    except ValueError:
                        pass
        except Exception:
            pass

        kernel = None
        hostname = None
        virt_detect = "oracle"

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
            os_release="Ubuntu (VirtualBox Guest)",
            hostname=hostname or self.vm_name,
            vcpus=vcpus,
            memory_mb=memory_mb,
            ip_address=self.transport.host,
            mac_address=raw_info.get("macaddress1"),
            hypervisor_version=f"VirtualBox {vbox_version}" if vbox_version else "VirtualBox",
            systemd_detect_virt=virt_detect,
            is_shared_kernel=False,
            raw_details={
                "vm_name": self.vm_name,
                "uuid": raw_info.get("HardwareUUID") or raw_info.get("UUID"),
                "ssh_forwarded_port": self.transport.port
            }
        )
