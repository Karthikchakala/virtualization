"""
common.py - Common data schemas, safety guards, and utility functions for CC2 Benchmarking.
Strictly adheres to:
- No fabricated data
- No hardcoded results
- Missing data preserved as None/omitted, NEVER converted to 0
- Rigid status tracking: success, failed, unavailable
- Comprehensive safety guards against destructive operations
"""

import os
import re
import sys
import json
import time
import uuid
import subprocess
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List

# Allowed statuses
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_UNAVAILABLE = "unavailable"
VALID_STATUSES = {STATUS_SUCCESS, STATUS_FAILED, STATUS_UNAVAILABLE}

# Environments
ENV_HOST = "host"
ENV_KVM = "kvm"
ENV_VIRTUALBOX = "virtualbox"
ENV_LXC = "lxc"
VALID_ENVIRONMENTS = {ENV_HOST, ENV_KVM, ENV_VIRTUALBOX, ENV_LXC}

# Prohibited dangerous patterns - zero tolerance
PROHIBITED_COMMAND_PATTERNS = [
    r"\bmkfs\b",
    r"\bfdisk\b",
    r"\bparted\b",
    r"\bwipefs\b",
    r"\bdd\s+.*of=/dev/(nvme|sd|vd|loop|mapper)",
    r">+\s*/dev/(nvme|sd|vd|loop|mapper)",
    r"\brm\s+-rf\s+/(boot|etc|sys|proc|dev|root|usr|var|home)",
    r"\bgrub-install\b",
    r"\bupdate-grub\b",
    r"\befibootmgr\b",
    r"\bvirsh\s+undefine\b",
    r"\bvirsh\s+destroy\b.*--remove-all-storage",
    r"\bVBoxManage\s+unregistervm\s+.*--delete",
    r"\blxc-destroy\b",
]

class SafetyViolationError(Exception):
    """Raised when a command violates safety guidelines."""
    pass

class SafetyValidator:
    """Validates commands to guarantee non-destructive execution."""

    @staticmethod
    def validate_command(command_str: str) -> None:
        """
        Validates that a shell command contains NO destructive operations.
        Raises SafetyViolationError if dangerous pattern detected.
        """
        for pattern in PROHIBITED_COMMAND_PATTERNS:
            if re.search(pattern, command_str, re.IGNORECASE):
                raise SafetyViolationError(
                    f"Command rejected by safety guard: matches prohibited pattern '{pattern}'. Command: {command_str}"
                )

        # Check for direct block device writes
        if re.search(r"/dev/(nvme[0-9]n[0-9]|sd[a-z]|vd[a-z])", command_str):
            # Only allowed if strictly read-only inspection (e.g. lsblk, smartctl -i, findmnt)
            allowed_prefixes = ("lsblk", "findmnt", "blkid", "hdparm -I", "smartctl -i", "fdisk -l", "parted -l")
            cmd_stripped = command_str.strip()
            if not any(cmd_stripped.startswith(p) for p in allowed_prefixes):
                if ">" in command_str or "of=" in command_str:
                    raise SafetyViolationError(
                        f"Direct block device write forbidden! Command: {command_str}"
                    )

    @staticmethod
    def is_safe(command_str: str) -> bool:
        try:
            SafetyValidator.validate_command(command_str)
            return True
        except SafetyViolationError:
            return False

@dataclass
class BenchmarkResult:
    """
    Standard result schema mandated by specification.
    Every displayed result MUST be traceable to raw command output.
    """
    environment: str
    benchmark: str
    run_id: str
    timestamp: str
    command: str
    exit_code: int
    stdout: str
    stderr: str
    parsed_metrics: Dict[str, Any]
    status: str

    def __post_init__(self):
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{self.status}'. Must be one of {VALID_STATUSES}")
        if self.environment not in VALID_ENVIRONMENTS:
            raise ValueError(f"Invalid environment '{self.environment}'. Must be one of {VALID_ENVIRONMENTS}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkResult":
        return cls(
            environment=data["environment"],
            benchmark=data["benchmark"],
            run_id=data["run_id"],
            timestamp=data["timestamp"],
            command=data["command"],
            exit_code=int(data["exit_code"]),
            stdout=data["stdout"],
            stderr=data["stderr"],
            parsed_metrics=data.get("parsed_metrics", {}),
            status=data["status"]
        )

def run_safe_command(
    command_str: str,
    cwd: Optional[str] = None,
    timeout: int = 60,
    env_vars: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Executes a shell command after safety validation.
    Returns a dictionary with exit_code, stdout, stderr, execution_time_sec.
    """
    SafetyValidator.validate_command(command_str)

    run_env = os.environ.copy()
    if env_vars:
        run_env.update(env_vars)

    start_time = time.monotonic()
    try:
        proc = subprocess.run(
            command_str,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=run_env
        )
        elapsed = time.monotonic() - start_time
        return {
            "command": command_str,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "execution_time_sec": elapsed,
            "timed_out": False
        }
    except subprocess.TimeoutExpired as e:
        elapsed = time.monotonic() - start_time
        return {
            "command": command_str,
            "exit_code": -1,
            "stdout": e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
            "stderr": f"Command timed out after {timeout} seconds. {e.stderr if e.stderr else ''}",
            "execution_time_sec": elapsed,
            "timed_out": True
        }
    except Exception as e:
        elapsed = time.monotonic() - start_time
        return {
            "command": command_str,
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
            "execution_time_sec": elapsed,
            "timed_out": False
        }

def create_result_record(
    environment: str,
    benchmark: str,
    command: str,
    cmd_output: Dict[str, Any],
    parsed_metrics: Optional[Dict[str, Any]] = None,
    status_override: Optional[str] = None
) -> BenchmarkResult:
    """Helper to construct a validated BenchmarkResult instance."""
    now_iso = datetime.now(timezone.utc).isoformat()
    run_id = f"{benchmark}-{environment}-{uuid.uuid4().hex[:8]}"

    if status_override:
        status = status_override
    elif cmd_output.get("exit_code") == 0:
        status = STATUS_SUCCESS
    elif cmd_output.get("timed_out") or cmd_output.get("exit_code") != 0:
        status = STATUS_FAILED
    else:
        status = STATUS_UNAVAILABLE

    return BenchmarkResult(
        environment=environment,
        benchmark=benchmark,
        run_id=run_id,
        timestamp=now_iso,
        command=command,
        exit_code=cmd_output.get("exit_code", -1),
        stdout=cmd_output.get("stdout", ""),
        stderr=cmd_output.get("stderr", ""),
        parsed_metrics=parsed_metrics or {},
        status=status
    )
