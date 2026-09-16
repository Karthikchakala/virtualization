#!/usr/bin/env python3
"""
benchmark/runner/environments/transport.py - Transport Abstractions for CC2.

Provides unified, secure transport mechanisms for dispatching commands and files:
1. LocalTransport: Direct host execution with safety filtering.
2. SSHTransport: Remote execution over SSH with key preference, PTY-based password
   handling (no credential leakage in process table), and base64 streaming.
3. LxcAttachTransport: Container execution strictly using native lxc-attach.

STRICT SAFETY:
- Every command is validated through SafetyValidator before dispatch.
- Passwords are never passed via CLI arguments and are masked in representations and logs.
- Never runs benchmark workloads during connection probes or transports.
"""

import os
import re
import sys
import time
import base64
import shlex
import shutil
import select
import hashlib
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

from .base import ExecutionResult
from ..config import mask_secret

# Try importing SafetyValidator from collector.common
try:
    from collector.common import SafetyValidator, SafetyViolationError
except ImportError:
    # Fallback safety validator if collector is not in pythonpath directly
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from collector.common import SafetyValidator, SafetyViolationError


class BaseTransport(ABC):
    """
    Abstract interface for environment command execution and file transport.
    """

    @abstractmethod
    def execute(
        self,
        cmd: Union[str, List[str]],
        timeout: int = 60,
        env_vars: Optional[Dict[str, str]] = None
    ) -> ExecutionResult:
        """Executes a command inside the target environment."""
        pass

    @abstractmethod
    def copy_file(self, local_path: Union[str, Path], remote_dest: str) -> bool:
        """Transfers a local file into the target environment."""
        pass

    @abstractmethod
    def read_file(self, remote_path: str) -> Optional[str]:
        """Reads remote file text content."""
        pass

    @abstractmethod
    def compute_sha256(self, remote_path: str) -> Optional[str]:
        """Computes the SHA256 digest of a remote file."""
        pass

    @abstractmethod
    def is_reachable(self, timeout_sec: int = 5) -> bool:
        """Verifies if transport endpoint is currently reachable."""
        pass


# ==============================================================================
# Local Transport (Host)
# ==============================================================================

class LocalTransport(BaseTransport):
    """
    Transport for host-local execution with non-destructive safety validation.
    """

    def __init__(self):
        pass

    def execute(
        self,
        cmd: Union[str, List[str]],
        timeout: int = 60,
        env_vars: Optional[Dict[str, str]] = None
    ) -> ExecutionResult:
        cmd_str = cmd if isinstance(cmd, str) else shlex.join(cmd)

        # 1. Enforce safety validation
        SafetyValidator.validate_command(cmd_str)

        # 2. Build environment
        run_env = os.environ.copy()
        if env_vars:
            run_env.update(env_vars)

        start_time = time.perf_counter()
        try:
            res = subprocess.run(
                cmd_str,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=run_env
            )
            duration = time.perf_counter() - start_time
            return ExecutionResult(
                exit_code=res.returncode,
                stdout=res.stdout,
                stderr=res.stderr,
                duration_sec=duration,
                timed_out=False,
                status="success" if res.returncode == 0 else "failed",
                command=cmd_str
            )
        except subprocess.TimeoutExpired as te:
            duration = time.perf_counter() - start_time
            stdout = te.stdout.decode("utf-8", errors="ignore") if isinstance(te.stdout, bytes) else (te.stdout or "")
            stderr = te.stderr.decode("utf-8", errors="ignore") if isinstance(te.stderr, bytes) else (te.stderr or "")
            return ExecutionResult(
                exit_code=-1,
                stdout=stdout,
                stderr=stderr + f"\n[Execution timed out after {timeout} seconds]",
                duration_sec=duration,
                timed_out=True,
                status="timeout",
                command=cmd_str
            )
        except Exception as e:
            duration = time.perf_counter() - start_time
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_sec=duration,
                timed_out=False,
                status="failed",
                command=cmd_str
            )

    def copy_file(self, local_path: Union[str, Path], remote_dest: str) -> bool:
        src = Path(local_path).resolve()
        if not src.exists() or not src.is_file():
            return False

        dst = Path(remote_dest).resolve()
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        os.chmod(str(dst), 0o755)
        return True

    def read_file(self, remote_path: str) -> Optional[str]:
        p = Path(remote_path)
        if p.exists() and p.is_file():
            try:
                return p.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    def compute_sha256(self, remote_path: str) -> Optional[str]:
        p = Path(remote_path)
        if not p.exists() or not p.is_file():
            return None
        h = hashlib.sha256()
        try:
            with open(p, "rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None

    def is_reachable(self, timeout_sec: int = 5) -> bool:
        return True

    def __repr__(self) -> str:
        return "LocalTransport()"


# ==============================================================================
# SSH Transport (KVM / VirtualBox)
# ==============================================================================

class SSHTransport(BaseTransport):
    """
    Secure SSH Transport with deterministic authentication precedence:
    1. SSH Key Authentication (-i key_path -o BatchMode=yes)
    2. Password Authentication via PTY (openpty() - zero exposure in CLI / logs)
    3. Agent / known_hosts fallback (-o BatchMode=yes)
    """

    def __init__(
        self,
        host: str,
        port: int = 22,
        user: Optional[str] = None,
        key_path: Optional[str] = None,
        password: Optional[str] = None,
        connect_timeout_sec: int = 5
    ):
        self.host = host
        self.port = int(port)
        self.user = user or os.environ.get("USER", "root")
        self.key_path = key_path.strip() if key_path else None
        self._password = password.strip() if password else None
        self.connect_timeout_sec = connect_timeout_sec

    @property
    def destination(self) -> str:
        return f"{self.user}@{self.host}"

    @property
    def auth_method(self) -> str:
        if self.key_path:
            expanded = Path(os.path.expanduser(self.key_path))
            if expanded.exists():
                return "key"
        if self._password:
            return "password"
        return "agent_or_none"

    def execute(
        self,
        cmd: Union[str, List[str]],
        timeout: int = 60,
        env_vars: Optional[Dict[str, str]] = None
    ) -> ExecutionResult:
        cmd_str = cmd if isinstance(cmd, str) else shlex.join(cmd)

        # 1. Enforce safety validation
        SafetyValidator.validate_command(cmd_str)

        if not self.host:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="SSH target host address is missing or empty",
                duration_sec=0.0,
                status="unavailable",
                command=cmd_str
            )

        ssh_bin = shutil.which("ssh")
        if not ssh_bin:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="ssh binary not found on host system",
                duration_sec=0.0,
                status="unavailable",
                command=cmd_str
            )

        # Wrap with environment variables if specified
        remote_cmd = cmd_str
        if env_vars:
            env_prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in env_vars.items())
            remote_cmd = f"export {env_prefix}; {cmd_str}"

        # Base SSH CLI options
        ssh_opts = [
            "-p", str(self.port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", f"ConnectTimeout={self.connect_timeout_sec}",
            "-o", "LogLevel=ERROR",
        ]

        # ----------------------------------------------------------------------
        # Precedence 1: SSH Key Authentication
        # ----------------------------------------------------------------------
        if self.auth_method == "key" and self.key_path:
            expanded_key = Path(os.path.expanduser(self.key_path))
            full_cmd = [ssh_bin] + ssh_opts + ["-i", str(expanded_key), "-o", "BatchMode=yes", self.destination, remote_cmd]
            start_time = time.perf_counter()
            try:
                res = subprocess.run(
                    full_cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
                duration = time.perf_counter() - start_time
                return ExecutionResult(
                    exit_code=res.returncode,
                    stdout=res.stdout,
                    stderr=res.stderr,
                    duration_sec=duration,
                    timed_out=False,
                    status="success" if res.returncode == 0 else "failed",
                    command=cmd_str,
                    metadata={"auth_method": "key", "host": self.host, "port": self.port}
                )
            except subprocess.TimeoutExpired as te:
                duration = time.perf_counter() - start_time
                stdout = te.stdout.decode("utf-8", errors="ignore") if isinstance(te.stdout, bytes) else (te.stdout or "")
                stderr = te.stderr.decode("utf-8", errors="ignore") if isinstance(te.stderr, bytes) else (te.stderr or "")
                return ExecutionResult(
                    exit_code=-1,
                    stdout=stdout,
                    stderr=stderr + f"\n[SSH execution timed out after {timeout} seconds]",
                    duration_sec=duration,
                    timed_out=True,
                    status="timeout",
                    command=cmd_str,
                    metadata={"auth_method": "key", "host": self.host, "port": self.port}
                )
            except Exception as e:
                duration = time.perf_counter() - start_time
                return ExecutionResult(
                    exit_code=-1,
                    stdout="",
                    stderr=str(e),
                    duration_sec=duration,
                    status="failed",
                    command=cmd_str,
                    metadata={"auth_method": "key"}
                )

        # ----------------------------------------------------------------------
        # Precedence 2: Password Authentication via pseudo-terminal (PTY)
        # ----------------------------------------------------------------------
        if self.auth_method == "password" and self._password:
            import pty
            full_cmd = [ssh_bin] + ssh_opts + [
                "-o", "PreferredAuthentications=password,keyboard-interactive",
                "-o", "PubkeyAuthentication=no",
                self.destination,
                remote_cmd
            ]

            start_time = time.perf_counter()
            master_fd, slave_fd = pty.openpty()
            try:
                proc = subprocess.Popen(
                    full_cmd,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    close_fds=True
                )
                os.close(slave_fd)

                output_chunks: List[bytes] = []
                password_sent = False

                while True:
                    if time.perf_counter() - start_time > timeout:
                        proc.kill()
                        try:
                            os.close(master_fd)
                        except OSError:
                            pass
                        proc.wait()
                        duration = time.perf_counter() - start_time
                        return ExecutionResult(
                            exit_code=-1,
                            stdout="",
                            stderr=f"[SSH execution timed out after {timeout} seconds]",
                            duration_sec=duration,
                            timed_out=True,
                            status="timeout",
                            command=cmd_str,
                            metadata={"auth_method": "password"}
                        )

                    r, _, _ = select.select([master_fd], [], [], 0.5)
                    if r:
                        try:
                            chunk = os.read(master_fd, 2048)
                            if not chunk:
                                break
                            output_chunks.append(chunk)
                            combined = b"".join(output_chunks).decode("utf-8", errors="ignore")

                            if not password_sent and re.search(r"password:\s*$", combined, re.IGNORECASE):
                                os.write(master_fd, (self._password + "\n").encode("utf-8"))
                                password_sent = True
                                output_chunks = []
                        except OSError:
                            break

                    if proc.poll() is not None:
                        # Flush remaining output
                        try:
                            while True:
                                r, _, _ = select.select([master_fd], [], [], 0.1)
                                if not r:
                                    break
                                chunk = os.read(master_fd, 2048)
                                if not chunk:
                                    break
                                output_chunks.append(chunk)
                        except OSError:
                            pass
                        break

                try:
                    os.close(master_fd)
                except OSError:
                    pass
                proc.wait()
                duration = time.perf_counter() - start_time

                clean_output = b"".join(output_chunks).decode("utf-8", errors="ignore")
                # Sanitize echoed password if any
                if self._password in clean_output:
                    clean_output = clean_output.replace(self._password, "********")

                is_success = proc.returncode == 0
                return ExecutionResult(
                    exit_code=proc.returncode,
                    stdout=clean_output if is_success else "",
                    stderr="" if is_success else clean_output,
                    duration_sec=duration,
                    timed_out=False,
                    status="success" if is_success else "failed",
                    command=cmd_str,
                    metadata={"auth_method": "password", "host": self.host, "port": self.port}
                )
            except Exception as e:
                try:
                    os.close(master_fd)
                except Exception:
                    pass
                duration = time.perf_counter() - start_time
                return ExecutionResult(
                    exit_code=-1,
                    stdout="",
                    stderr=str(e),
                    duration_sec=duration,
                    status="failed",
                    command=cmd_str,
                    metadata={"auth_method": "password"}
                )

        # ----------------------------------------------------------------------
        # Precedence 3: Batch Mode / Agent fallback
        # ----------------------------------------------------------------------
        full_cmd = [ssh_bin] + ssh_opts + ["-o", "BatchMode=yes", self.destination, remote_cmd]
        start_time = time.perf_counter()
        try:
            res = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            duration = time.perf_counter() - start_time
            return ExecutionResult(
                exit_code=res.returncode,
                stdout=res.stdout,
                stderr=res.stderr,
                duration_sec=duration,
                timed_out=False,
                status="success" if res.returncode == 0 else "failed",
                command=cmd_str,
                metadata={"auth_method": "agent_or_none", "host": self.host, "port": self.port}
            )
        except subprocess.TimeoutExpired as te:
            duration = time.perf_counter() - start_time
            stdout = te.stdout.decode("utf-8", errors="ignore") if isinstance(te.stdout, bytes) else (te.stdout or "")
            stderr = te.stderr.decode("utf-8", errors="ignore") if isinstance(te.stderr, bytes) else (te.stderr or "")
            return ExecutionResult(
                exit_code=-1,
                stdout=stdout,
                stderr=stderr + f"\n[SSH execution timed out after {timeout} seconds]",
                duration_sec=duration,
                timed_out=True,
                status="timeout",
                command=cmd_str,
                metadata={"auth_method": "agent_or_none"}
            )
        except Exception as e:
            duration = time.perf_counter() - start_time
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_sec=duration,
                status="failed",
                command=cmd_str,
                metadata={"auth_method": "agent_or_none"}
            )

    def copy_file(self, local_path: Union[str, Path], remote_dest: str) -> bool:
        """
        Transfers local file to remote destination via robust base64 streaming over SSH.
        Works consistently across all auth methods (keys, PTY passwords, agent).
        """
        src = Path(local_path).resolve()
        if not src.exists() or not src.is_file():
            return False

        try:
            binary_bytes = src.read_bytes()
            b64_str = base64.b64encode(binary_bytes).decode("ascii")
        except Exception:
            return False

        # Prepare remote destination directory and decode stream
        remote_dir = str(Path(remote_dest).parent)
        deploy_script = (
            f"mkdir -p '{remote_dir}' && "
            f"base64 -d << 'EOF' > '{remote_dest}'\n{b64_str}\nEOF\n"
            f"chmod 755 '{remote_dest}'"
        )

        res = self.execute(deploy_script, timeout=90)
        return res.success

    def read_file(self, remote_path: str) -> Optional[str]:
        res = self.execute(f"cat '{remote_path}'", timeout=15)
        return res.stdout if res.success else None

    def compute_sha256(self, remote_path: str) -> Optional[str]:
        res = self.execute(f"sha256sum '{remote_path}'", timeout=15)
        if res.success and res.stdout.strip():
            parts = res.stdout.strip().split()
            if parts and len(parts[0]) == 64:
                return parts[0]
        return None

    def is_reachable(self, timeout_sec: int = 5) -> bool:
        if not self.host:
            return False
        res = self.execute("uname -r", timeout=timeout_sec)
        return res.success

    def __repr__(self) -> str:
        return (
            f"SSHTransport(host='{self.host}', port={self.port}, user='{self.user}', "
            f"auth_method='{self.auth_method}', password='{mask_secret(self._password)}', "
            f"key_path='{self.key_path}')"
        )


# ==============================================================================
# Native LXC Attach Transport (lxc-attach)
# ==============================================================================

class LxcAttachTransport(BaseTransport):
    """
    Transport strictly utilizing native lxc-attach.
    Never uses SSH, Docker, or LXD.
    """

    def __init__(self, container_name: str, rootfs_path: Optional[Union[str, Path]] = None):
        self.container_name = container_name
        self.rootfs_path = Path(rootfs_path) if rootfs_path else Path(f"/var/lib/lxc/{container_name}/rootfs")

    def execute(
        self,
        cmd: Union[str, List[str]],
        timeout: int = 60,
        env_vars: Optional[Dict[str, str]] = None
    ) -> ExecutionResult:
        cmd_str = cmd if isinstance(cmd, str) else shlex.join(cmd)

        # 1. Safety validation
        SafetyValidator.validate_command(cmd_str)

        lxc_attach_bin = shutil.which("lxc-attach")
        if not lxc_attach_bin:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="lxc-attach binary not found on host system",
                duration_sec=0.0,
                status="unavailable",
                command=cmd_str
            )

        # Build command wrapped in shell inside container
        inner_cmd = cmd_str
        if env_vars:
            env_prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in env_vars.items())
            inner_cmd = f"export {env_prefix}; {cmd_str}"

        full_cmd = [lxc_attach_bin, "-n", self.container_name, "--", "sh", "-c", inner_cmd]

        start_time = time.perf_counter()
        try:
            res = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            duration = time.perf_counter() - start_time
            return ExecutionResult(
                exit_code=res.returncode,
                stdout=res.stdout,
                stderr=res.stderr,
                duration_sec=duration,
                timed_out=False,
                status="success" if res.returncode == 0 else "failed",
                command=cmd_str,
                metadata={"container": self.container_name, "transport": "lxc-attach"}
            )
        except subprocess.TimeoutExpired as te:
            duration = time.perf_counter() - start_time
            stdout = te.stdout.decode("utf-8", errors="ignore") if isinstance(te.stdout, bytes) else (te.stdout or "")
            stderr = te.stderr.decode("utf-8", errors="ignore") if isinstance(te.stderr, bytes) else (te.stderr or "")
            return ExecutionResult(
                exit_code=-1,
                stdout=stdout,
                stderr=stderr + f"\n[lxc-attach timed out after {timeout} seconds]",
                duration_sec=duration,
                timed_out=True,
                status="timeout",
                command=cmd_str,
                metadata={"container": self.container_name, "transport": "lxc-attach"}
            )
        except Exception as e:
            duration = time.perf_counter() - start_time
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_sec=duration,
                status="failed",
                command=cmd_str,
                metadata={"container": self.container_name}
            )

    def copy_file(self, local_path: Union[str, Path], remote_dest: str) -> bool:
        src = Path(local_path).resolve()
        if not src.exists() or not src.is_file():
            return False

        # Attempt 1: Direct rootfs copy if accessible and writable
        if self.rootfs_path and self.rootfs_path.exists() and os.access(str(self.rootfs_path), os.W_OK):
            try:
                target_dest_clean = remote_dest.lstrip("/")
                dst = (self.rootfs_path / target_dest_clean).resolve()
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                os.chmod(str(dst), 0o755)
                return True
            except Exception:
                pass

        # Attempt 2: Stream base64 via lxc-attach
        try:
            binary_bytes = src.read_bytes()
            b64_str = base64.b64encode(binary_bytes).decode("ascii")
        except Exception:
            return False

        remote_dir = str(Path(remote_dest).parent)
        deploy_cmd = (
            f"mkdir -p '{remote_dir}' && "
            f"base64 -d << 'EOF' > '{remote_dest}'\n{b64_str}\nEOF\n"
            f"chmod 755 '{remote_dest}'"
        )
        res = self.execute(deploy_cmd, timeout=60)
        return res.success

    def read_file(self, remote_path: str) -> Optional[str]:
        res = self.execute(f"cat '{remote_path}'", timeout=10)
        return res.stdout if res.success else None

    def compute_sha256(self, remote_path: str) -> Optional[str]:
        res = self.execute(f"sha256sum '{remote_path}'", timeout=10)
        if res.success and res.stdout.strip():
            parts = res.stdout.strip().split()
            if parts and len(parts[0]) == 64:
                return parts[0]
        return None

    def is_reachable(self, timeout_sec: int = 5) -> bool:
        res = self.execute("uname -r", timeout=timeout_sec)
        return res.success

    def __repr__(self) -> str:
        return f"LxcAttachTransport(container='{self.container_name}')"
