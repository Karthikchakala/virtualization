#!/usr/bin/env python3
"""
benchmark/runner/environments/base.py - Base Environment Adapter Contract.

Defines the abstract interface and normalized data structures for all
environment adapters (Host, KVM/QEMU, VirtualBox, and Native LXC).
The benchmark engine interacts strictly through this common abstraction layer,
ensuring zero environment-specific branching logic in the execution engine.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

from ..config import EnvironmentConfig, mask_secret


class NormalizedState:
    """
    Standardized lifecycle state vocabulary across all virtualization technologies.
    """
    RUNNING = "running"
    STOPPED = "stopped"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    UNKNOWN = "unknown"

    ALL = {RUNNING, STOPPED, UNAVAILABLE, ERROR, UNKNOWN}

    @classmethod
    def is_valid(cls, state: str) -> bool:
        return state in cls.ALL


@dataclass
class ExecutionResult:
    """
    Standardized container for command execution results across any transport.
    """
    exit_code: int
    stdout: str
    stderr: str
    duration_sec: float
    timed_out: bool = False
    status: str = "success"  # "success", "failed", "timeout", "unavailable"
    command: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and self.status == "success"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_sec": round(self.duration_sec, 6),
            "timed_out": self.timed_out,
            "status": self.status,
            "command": self.command,
            "metadata": self.metadata
        }


@dataclass
class IdentityResult:
    """
    Standardized identity specification for an execution environment.
    """
    environment: str
    classification: str
    virtualization_type: str
    kernel_release: Optional[str] = None
    os_release: Optional[str] = None
    hostname: Optional[str] = None
    vcpus: int = 1
    memory_mb: int = 0
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    hypervisor_version: Optional[str] = None
    systemd_detect_virt: Optional[str] = None
    is_shared_kernel: bool = False
    raw_details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "environment": self.environment,
            "classification": self.classification,
            "virtualization_type": self.virtualization_type,
            "kernel_release": self.kernel_release,
            "os_release": self.os_release,
            "hostname": self.hostname,
            "vcpus": self.vcpus,
            "memory_mb": self.memory_mb,
            "ip_address": self.ip_address,
            "mac_address": self.mac_address,
            "hypervisor_version": self.hypervisor_version,
            "systemd_detect_virt": self.systemd_detect_virt,
            "is_shared_kernel": self.is_shared_kernel,
            "raw_details": self.raw_details
        }


class BaseEnvironmentAdapter(ABC):
    """
    Abstract Base Class for all Virtualization and OS Environment Adapters.

    Subclasses must implement:
    1. verify() -> bool
    2. prepare() -> Dict[str, Any]
    3. deploy_workload(local_path, target_dest) -> Dict[str, Any]
    4. execute(cmd, timeout, env_vars) -> ExecutionResult
    5. collect_metrics(pid, metadata) -> Dict[str, Any]
    6. cleanup() -> bool
    7. get_identity() -> IdentityResult
    8. get_status() -> str
    """

    def __init__(self, config: EnvironmentConfig):
        self.config = config
        self._target_path = Path(config.target_path) if config.target_path else Path("/tmp/cc2_workloads")

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def display_name(self) -> str:
        return self.config.display_name

    @property
    def classification(self) -> str:
        return self.config.classification

    @property
    def virtualization_type(self) -> str:
        return self.config.virtualization_type

    @property
    def transport_name(self) -> str:
        return self.config.transport

    @property
    def target_path(self) -> Path:
        return self._target_path

    @abstractmethod
    def verify(self) -> bool:
        """
        Verifies that management daemons, CLI utilities, and transport prerequisites
        are accessible. Returns True if verified, False otherwise.
        Must NEVER throw unhandled exceptions or run benchmark workloads.
        """
        pass

    @abstractmethod
    def prepare(self) -> Dict[str, Any]:
        """
        Ensures the environment is in a ready state.
        If stopped, may boot/start target VM or container and wait for network/app readiness.
        Returns a dictionary recording preparation timings and status.
        """
        pass

    @abstractmethod
    def deploy_workload(self, local_path: Union[str, Path], target_dest: Optional[str] = None) -> Dict[str, Any]:
        """
        Verifies local binary, checks target destination, transfers if needed,
        and verifies remote SHA256 matches.
        Must NEVER silently recompile workloads on the target.
        """
        pass

    @abstractmethod
    def execute(
        self,
        cmd: Union[str, List[str]],
        timeout: int = 60,
        env_vars: Optional[Dict[str, str]] = None
    ) -> ExecutionResult:
        """
        Executes a command inside the target environment via its transport mechanism.
        Enforces execution timeouts, captures stdout/stderr, and returns ExecutionResult.
        All commands must be validated through SafetyValidator before execution.
        """
        pass

    @abstractmethod
    def collect_metrics(
        self,
        pid: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Captures environment-specific telemetry during or immediately following execution.
        Host: CPU ticks, thermals, memory.
        KVM: Libvirt domstats, host QEMU PID telemetry.
        VirtualBox: VBoxManage metrics, VBoxHeadless PID telemetry.
        LXC: Unified Cgroups v2 (cpu.stat, memory.current, memory.peak).
        """
        pass

    @abstractmethod
    def cleanup(self) -> bool:
        """
        Gracefully terminates lingering workload processes and enforces
        post-execution cooldown. Safe and non-destructive.
        """
        pass

    @abstractmethod
    def get_identity(self) -> IdentityResult:
        """
        Queries and returns environment hardware topology, vCPUs, RAM ceiling,
        kernel release (uname -r), virtualization type, and network endpoints.
        Never fabricates values.
        """
        pass

    @abstractmethod
    def get_status(self) -> str:
        """
        Returns one of NormalizedState: 'running', 'stopped', 'unavailable', 'error', 'unknown'.
        """
        pass

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(name='{self.name}', "
            f"classification='{self.classification}', "
            f"transport='{self.transport_name}', "
            f"status='{self.get_status()}')"
        )
