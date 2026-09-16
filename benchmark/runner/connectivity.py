#!/usr/bin/env python3
"""
benchmark/runner/connectivity.py - Non-Destructive Connectivity & Health Diagnostics.

Executes safe, read-only diagnostic checks:
1. Host: Introspects local OS, kernel, CPU, and RAM.
2. KVM/QEMU: Checks libvirt hypervisor status, VM state, dynamic IP, and SSH reachability.
3. VirtualBox: Checks VBoxManage hypervisor status, VM state, and SSH reachability on 127.0.0.1:2222.
4. Native LXC: Checks container state, and tests local lxc-attach execution.

STRICT SAFETY GUARANTEES:
- Runs ONLY harmless inspection commands: 'uname -r', 'id', 'hostname', 'sha256sum --version'.
- NEVER executes benchmark workloads.
- NEVER modifies disks or partitions.
- NEVER exposes passwords or secrets in terminal output or logs.
- Never fabricates success; accurately reports 'unavailable' with transparent reasons.
"""

import os
import re
import sys
import time
import shutil
import select
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

from .config import AppConfig, EnvironmentConfig, mask_secret

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ==============================================================================
# Safe Non-Interactive SSH Transport Probe
# ==============================================================================

def run_safe_ssh_probe(
    host: str,
    port: int,
    user: Optional[str],
    command: str,
    key_path: Optional[str] = None,
    password: Optional[str] = None,
    timeout_sec: int = 5
) -> Dict[str, Any]:
    """
    Executes a harmless command over SSH without exposing credentials in process listings.
    Supports SSH key authentication (preferred) and secure non-interactive password entry via PTY.
    """
    if not host:
        return {
            "status": "unavailable",
            "exit_code": -1,
            "stdout": "",
            "stderr": "No target host specified",
            "reason": "Host address is missing or not yet discovered"
        }

    ssh_bin = shutil.which("ssh")
    if not ssh_bin:
        return {
            "status": "unavailable",
            "exit_code": -1,
            "stdout": "",
            "stderr": "ssh binary not found on host",
            "reason": "OpenSSH client is not installed"
        }

    # Normalize user
    target_user = user or os.environ.get("USER", "root")
    destination = f"{target_user}@{host}"

    # Base SSH options
    ssh_opts = [
        "-p", str(port),
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", f"ConnectTimeout={timeout_sec}",
        "-o", "LogLevel=ERROR",
    ]

    # Precedence 1: SSH Key Authentication
    expanded_key: Optional[Path] = None
    if key_path and key_path.strip():
        expanded_key = Path(os.path.expanduser(key_path.strip()))
        if expanded_key.exists():
            ssh_opts.extend(["-i", str(expanded_key), "-o", "BatchMode=yes"])
            cmd_list = [ssh_bin] + ssh_opts + [destination, command]
            try:
                res = subprocess.run(
                    cmd_list,
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec + 5
                )
                return {
                    "status": "success" if res.returncode == 0 else "failed",
                    "exit_code": res.returncode,
                    "stdout": res.stdout.strip(),
                    "stderr": res.stderr.strip(),
                    "auth_used": "key",
                    "reason": res.stderr.strip() if res.returncode != 0 else ""
                }
            except subprocess.TimeoutExpired:
                return {
                    "status": "unavailable",
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": "SSH connection timed out",
                    "auth_used": "key",
                    "reason": f"Connection to {destination}:{port} timed out after {timeout_sec}s"
                }
            except Exception as e:
                return {
                    "status": "failed",
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": str(e),
                    "auth_used": "key",
                    "reason": str(e)
                }

    # Precedence 2: Password Authentication via pseudo-terminal (PTY)
    # Never passes password on command line arguments
    if password and password.strip():
        import pty
        cmd_list = [ssh_bin] + ssh_opts + [
            "-o", "PreferredAuthentications=password,keyboard-interactive",
            "-o", "PubkeyAuthentication=no",
            destination,
            command
        ]

        master_fd, slave_fd = pty.openpty()
        try:
            proc = subprocess.Popen(
                cmd_list,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True
            )
            os.close(slave_fd)  # Close slave in parent process

            output_chunks: List[bytes] = []
            password_sent = False
            start_time = time.time()

            while True:
                if time.time() - start_time > timeout_sec + 5:
                    proc.kill()
                    return {
                        "status": "unavailable",
                        "exit_code": -1,
                        "stdout": "",
                        "stderr": "SSH password prompt timed out",
                        "auth_used": "password",
                        "reason": f"Password authentication to {destination}:{port} timed out"
                    }

                r, _, _ = select.select([master_fd], [], [], 0.5)
                if r:
                    try:
                        chunk = os.read(master_fd, 1024)
                        if not chunk:
                            break
                        output_chunks.append(chunk)
                        combined = b"".join(output_chunks).decode("utf-8", errors="ignore")

                        # Look for password prompt
                        if not password_sent and re.search(r"password:\s*$", combined, re.IGNORECASE):
                            os.write(master_fd, (password + "\n").encode("utf-8"))
                            password_sent = True
                            # Clear buffer so prompt isn't retained in output
                            output_chunks = []
                    except OSError:
                        break

                if proc.poll() is not None:
                    # Read any remaining bytes
                    try:
                        while True:
                            r, _, _ = select.select([master_fd], [], [], 0.1)
                            if not r:
                                break
                            chunk = os.read(master_fd, 1024)
                            if not chunk:
                                break
                            output_chunks.append(chunk)
                    except OSError:
                        pass
                    break

            os.close(master_fd)
            proc.wait()

            clean_stdout = b"".join(output_chunks).decode("utf-8", errors="ignore").strip()
            # Sanitize any accidental password echo
            if password in clean_stdout:
                clean_stdout = clean_stdout.replace(password, "********")

            return {
                "status": "success" if proc.returncode == 0 else "failed",
                "exit_code": proc.returncode,
                "stdout": clean_stdout,
                "stderr": "" if proc.returncode == 0 else "Authentication failed or connection closed",
                "auth_used": "password",
                "reason": "" if proc.returncode == 0 else "SSH authentication failed or command returned non-zero"
            }
        except Exception as e:
            try:
                os.close(master_fd)
            except Exception:
                pass
            return {
                "status": "failed",
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "auth_used": "password",
                "reason": str(e)
            }

    # Precedence 3: Batch Mode / Agent fallback
    ssh_opts.append("-o")
    ssh_opts.append("BatchMode=yes")
    cmd_list = [ssh_bin] + ssh_opts + [destination, command]
    try:
        res = subprocess.run(cmd_list, capture_output=True, text=True, timeout=timeout_sec + 3)
        return {
            "status": "success" if res.returncode == 0 else "unavailable",
            "exit_code": res.returncode,
            "stdout": res.stdout.strip(),
            "stderr": res.stderr.strip(),
            "auth_used": "agent_or_known_key",
            "reason": res.stderr.strip() if res.returncode != 0 else ""
        }
    except Exception as e:
        return {
            "status": "unavailable",
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
            "auth_used": "none",
            "reason": str(e)
        }


# ==============================================================================
# Individual Environment Probes
# ==============================================================================

def check_host_connectivity() -> Dict[str, Any]:
    """Inspects local host execution capabilities without running benchmarks."""
    report = {
        "status": "available",
        "os": "unknown",
        "kernel": "unknown",
        "cpu": "unknown",
        "logical_cpus": os.cpu_count() or 0
    }
    try:
        uname_res = subprocess.run(["uname", "-r"], capture_output=True, text=True)
        if uname_res.returncode == 0:
            report["kernel"] = uname_res.stdout.strip()

        # Read /etc/os-release
        os_release = Path("/etc/os-release")
        if os_release.exists():
            for line in os_release.read_text().splitlines():
                if line.startswith("PRETTY_NAME="):
                    report["os"] = line.split("=", 1)[1].strip('"')

        # Read CPU model from /proc/cpuinfo
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.exists():
            for line in cpuinfo.read_text().splitlines():
                if "model name" in line:
                    report["cpu"] = line.split(":", 1)[1].strip()
                    break
    except Exception as e:
        report["status"] = "degraded"
        report["error"] = str(e)

    return report


def check_kvm_connectivity(config: EnvironmentConfig, timeout_sec: int = 5) -> Dict[str, Any]:
    """Non-destructively probes libvirt daemon, VM status, and SSH reachability."""
    report = {
        "vm_name": config.vm_name or "ubuntu24.04",
        "hypervisor": "unavailable",
        "guest_state": "unknown",
        "discovered_ip": None,
        "ssh_status": "unavailable",
        "guest_kernel": None,
        "guest_hostname": None,
        "guest_user_id": None,
        "sha256sum_available": False,
        "reason": ""
    }

    # 1. Check virsh CLI availability
    virsh_bin = shutil.which("virsh")
    if not virsh_bin:
        report["reason"] = "virsh command not found on host"
        return report

    # 2. Check libvirt hypervisor status and VM state
    mgmt_cmd = f"{virsh_bin} -c qemu:///system domstate {report['vm_name']}"
    try:
        res = subprocess.run(mgmt_cmd, shell=True, capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            report["hypervisor"] = "available"
            report["guest_state"] = res.stdout.strip()
        else:
            report["hypervisor"] = "available"
            report["guest_state"] = "not_found"
            report["reason"] = f"VM '{report['vm_name']}' not found in libvirt: {res.stderr.strip()}"
            return report
    except Exception as e:
        report["reason"] = f"Failed connecting to libvirt daemon: {e}"
        return report

    # 3. Dynamic IP Discovery
    discovered_ip = config.ssh_host
    if not discovered_ip:
        # Check libvirt DHCP leases
        leases_cmd = f"{virsh_bin} -c qemu:///system net-dhcp-leases default"
        try:
            l_res = subprocess.run(leases_cmd, shell=True, capture_output=True, text=True, timeout=5)
            if l_res.returncode == 0:
                for line in l_res.stdout.splitlines():
                    if "ipv4" in line:
                        parts = line.split()
                        for p in parts:
                            if "/" in p and p.split("/")[0].replace(".", "").isdigit():
                                discovered_ip = p.split("/")[0]
                                break
        except Exception:
            pass

    # Check virbr0.status file
    if not discovered_ip:
        virbr_status = Path("/var/lib/libvirt/dnsmasq/virbr0.status")
        if virbr_status.exists():
            try:
                import json
                data = json.loads(virbr_status.read_text())
                if isinstance(data, list) and data:
                    discovered_ip = data[-1].get("ip-address")
            except Exception:
                pass

    report["discovered_ip"] = discovered_ip

    # 4. If VM is not running, stop here safely
    if report["guest_state"].lower() != "running":
        report["ssh_status"] = "unavailable"
        report["reason"] = f"Guest is currently in '{report['guest_state']}' state (offline)"
        return report

    # 5. Probe SSH reachability with harmless read-only inspection
    if not discovered_ip:
        report["ssh_status"] = "unavailable"
        report["reason"] = "Guest IP address could not be resolved from libvirt"
        return report

    probe_res = run_safe_ssh_probe(
        host=discovered_ip,
        port=config.ssh_port,
        user=config.ssh_user,
        command="uname -r; hostname; id; sha256sum --version | head -n 1",
        key_path=config.ssh_key_path,
        password=config.ssh_password,
        timeout_sec=timeout_sec
    )

    if probe_res["status"] == "success":
        report["ssh_status"] = "OK"
        lines = probe_res["stdout"].splitlines()
        if len(lines) >= 1:
            report["guest_kernel"] = lines[0].strip()
        if len(lines) >= 2:
            report["guest_hostname"] = lines[1].strip()
        if len(lines) >= 3:
            report["guest_user_id"] = lines[2].strip()
        if any("sha256sum" in l for l in lines):
            report["sha256sum_available"] = True
    else:
        report["ssh_status"] = "unavailable"
        report["reason"] = probe_res.get("reason", "SSH connection failed")

    return report


def check_vbox_connectivity(config: EnvironmentConfig, timeout_sec: int = 5) -> Dict[str, Any]:
    """Non-destructively probes VirtualBox CLI, VM state, and SSH reachability."""
    report = {
        "vm_name": config.vm_name or "Ubuntu-Server-VBox",
        "hypervisor": "unavailable",
        "guest_state": "unknown",
        "ssh_endpoint": f"{config.ssh_host or '127.0.0.1'}:{config.ssh_port}",
        "ssh_status": "unavailable",
        "guest_kernel": None,
        "guest_hostname": None,
        "guest_user_id": None,
        "reason": ""
    }

    # 1. Check VBoxManage CLI availability
    vbox_bin = shutil.which("VBoxManage")
    if not vbox_bin:
        report["reason"] = "VBoxManage command not found on host"
        return report

    # 2. Check VM registration and state
    try:
        list_res = subprocess.run([vbox_bin, "list", "vms"], capture_output=True, text=True, timeout=5)
        if list_res.returncode == 0 and report["vm_name"] in list_res.stdout:
            report["hypervisor"] = "available"
        else:
            report["hypervisor"] = "available"
            report["guest_state"] = "not_registered"
            report["reason"] = f"VM '{report['vm_name']}' not registered with VirtualBox"
            return report

        # Check if running
        running_res = subprocess.run([vbox_bin, "list", "runningvms"], capture_output=True, text=True, timeout=5)
        if running_res.returncode == 0 and report["vm_name"] in running_res.stdout:
            report["guest_state"] = "running"
        else:
            report["guest_state"] = "powered_off"
            report["ssh_status"] = "unavailable"
            report["reason"] = "Guest is powered off (offline)"
            return report
    except Exception as e:
        report["reason"] = f"Failed querying VirtualBox: {e}"
        return report

    # 3. Probe SSH on configured host/port (defaults to 127.0.0.1:2222)
    target_host = config.ssh_host or "127.0.0.1"
    probe_res = run_safe_ssh_probe(
        host=target_host,
        port=config.ssh_port,
        user=config.ssh_user,
        command="uname -r; hostname; id",
        key_path=config.ssh_key_path,
        password=config.ssh_password,
        timeout_sec=timeout_sec
    )

    if probe_res["status"] == "success":
        report["ssh_status"] = "OK"
        lines = probe_res["stdout"].splitlines()
        if len(lines) >= 1:
            report["guest_kernel"] = lines[0].strip()
        if len(lines) >= 2:
            report["guest_hostname"] = lines[1].strip()
        if len(lines) >= 3:
            report["guest_user_id"] = lines[2].strip()
    else:
        report["ssh_status"] = "unavailable"
        report["reason"] = probe_res.get("reason", "SSH connection failed on forwarded port")

    return report


def check_lxc_connectivity(config: EnvironmentConfig) -> Dict[str, Any]:
    """Non-destructively probes native LXC container state and lxc-attach execution."""
    c_name = config.container_name or "lxc-ubuntu"
    report = {
        "container_name": c_name,
        "hypervisor": "unavailable",
        "container_state": "unknown",
        "lxc_attach_status": "unavailable",
        "guest_kernel": None,
        "guest_user_id": None,
        "discovered_ip": None,
        "reason": ""
    }

    # 1. Check native LXC CLI availability
    lxc_info_bin = shutil.which("lxc-info")
    if not lxc_info_bin:
        report["reason"] = "lxc-info command not found on host"
        return report

    report["hypervisor"] = "available (Native LXC)"

    # 2. Check container state via lxc-info -n <name> -s
    try:
        info_res = subprocess.run([lxc_info_bin, "-n", c_name, "-s"], capture_output=True, text=True, timeout=5)
        if info_res.returncode == 0:
            for line in info_res.stdout.splitlines():
                if "State:" in line:
                    report["container_state"] = line.split(":", 1)[1].strip()
        else:
            # Check if directory exists in /var/lib/lxc
            c_dir = Path(f"/var/lib/lxc/{c_name}")
            if c_dir.exists():
                report["container_state"] = "EXISTS_ON_DISK"
                if "Insufficent privileges" in info_res.stderr or "Permission denied" in info_res.stderr:
                    report["reason"] = "Requires elevated permissions to control /var/lib/lxc container"
            else:
                report["container_state"] = "not_found"
                report["reason"] = f"Container '{c_name}' not found"
                return report
    except Exception as e:
        report["reason"] = f"Error querying lxc-info: {e}"
        return report

    # 3. Check for lease IP
    leases_file = Path("/var/lib/misc/dnsmasq.lxcbr0.leases")
    if leases_file.exists():
        try:
            for line in leases_file.read_text().splitlines():
                parts = line.split()
                if len(parts) >= 4 and (c_name.lower() in parts[3].lower() or parts[3] == c_name):
                    report["discovered_ip"] = parts[2]
                    break
        except Exception:
            pass

    # 4. If container is not running, stop here safely
    if report["container_state"] != "RUNNING":
        report["lxc_attach_status"] = "unavailable"
        if not report["reason"]:
            report["reason"] = f"Container is in '{report['container_state']}' state (offline)"
        return report

    # 5. Test harmless lxc-attach execution
    lxc_attach_bin = shutil.which("lxc-attach")
    if not lxc_attach_bin:
        report["lxc_attach_status"] = "unavailable"
        report["reason"] = "lxc-attach binary not found"
        return report

    try:
        cmd = [lxc_attach_bin, "-n", c_name, "--", "sh", "-c", "uname -r; id"]
        attach_res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if attach_res.returncode == 0:
            report["lxc_attach_status"] = "OK"
            lines = attach_res.stdout.splitlines()
            if len(lines) >= 1:
                report["guest_kernel"] = lines[0].strip()
            if len(lines) >= 2:
                report["guest_user_id"] = lines[1].strip()
        else:
            report["lxc_attach_status"] = "unavailable"
            report["reason"] = attach_res.stderr.strip() or "lxc-attach returned non-zero"
    except Exception as e:
        report["lxc_attach_status"] = "unavailable"
        report["reason"] = f"lxc-attach execution failed: {e}"

    return report


# ==============================================================================
# Master Diagnostic CLI Reporter
# ==============================================================================

def run_connectivity_check(config: AppConfig) -> Dict[str, Any]:
    """Runs all non-destructive diagnostics and prints an formatted summary."""
    print("CC2 Configuration & Non-Destructive Connectivity Diagnostic")
    print("===========================================================")

    # Configuration summary
    env_loaded_msg = f"loaded ({config.env_file_path})" if config.env_file_loaded else "not found (using defaults/.env.example)"
    print("\nConfiguration Status:")
    print(f"  .env file:         {env_loaded_msg}")
    print(f"  environments.yaml: valid ({len(config.environments)} environments defined)")
    print(f"  benchmark.yaml:    valid ({len(config.benchmarks)} benchmarks defined)")
    print(f"  secret masking:    active (passwords masked as '********')")

    results: Dict[str, Any] = {}

    # 1. Host Baseline Probe
    print("\nHost Baseline:")
    host_res = check_host_connectivity()
    results["host"] = host_res
    print(f"  status:        {host_res['status']}")
    print(f"  OS:            {host_res.get('os')}")
    print(f"  kernel:        {host_res.get('kernel')}")
    print(f"  CPU model:     {host_res.get('cpu')}")
    print(f"  logical CPUs:  {host_res.get('logical_cpus')}")

    # 2. KVM Probe
    print("\nKVM / QEMU:")
    kvm_cfg = config.get_env("kvm")
    kvm_res = check_kvm_connectivity(kvm_cfg, timeout_sec=config.settings.ssh_connect_timeout_sec)
    results["kvm"] = kvm_res
    print(f"  VM name:       {kvm_res['vm_name']}")
    print(f"  hypervisor:    {kvm_res['hypervisor']}")
    print(f"  guest state:   {kvm_res['guest_state']}")
    print(f"  discovered IP: {kvm_res['discovered_ip'] or '(none / offline)'}")
    print(f"  auth method:   {kvm_cfg.auth_method}")
    print(f"  SSH transport: {kvm_res['ssh_status']}" + (f" ({kvm_res['reason']})" if kvm_res['reason'] else ""))
    if kvm_res.get("guest_kernel"):
        print(f"  guest kernel:  {kvm_res['guest_kernel']}")
    if kvm_res.get("guest_user_id"):
        print(f"  guest identity:{kvm_res['guest_user_id']}")

    # 3. VirtualBox Probe
    print("\nVirtualBox:")
    vbox_cfg = config.get_env("virtualbox")
    vbox_res = check_vbox_connectivity(vbox_cfg, timeout_sec=config.settings.ssh_connect_timeout_sec)
    results["virtualbox"] = vbox_res
    print(f"  VM name:       {vbox_res['vm_name']}")
    print(f"  hypervisor:    {vbox_res['hypervisor']}")
    print(f"  guest state:   {vbox_res['guest_state']}")
    print(f"  SSH endpoint:  {vbox_res['ssh_endpoint']}")
    print(f"  auth method:   {vbox_cfg.auth_method}")
    print(f"  SSH transport: {vbox_res['ssh_status']}" + (f" ({vbox_res['reason']})" if vbox_res['reason'] else ""))
    if vbox_res.get("guest_kernel"):
        print(f"  guest kernel:  {vbox_res['guest_kernel']}")
    if vbox_res.get("guest_user_id"):
        print(f"  guest identity:{vbox_res['guest_user_id']}")

    # 4. Native LXC Probe
    print("\nNative LXC:")
    lxc_cfg = config.get_env("lxc")
    lxc_res = check_lxc_connectivity(lxc_cfg)
    results["lxc"] = lxc_res
    print(f"  container:     {lxc_res['container_name']}")
    print(f"  hypervisor:    {lxc_res['hypervisor']}")
    print(f"  state:         {lxc_res['container_state']}")
    print(f"  discovered IP: {lxc_res['discovered_ip'] or '(none / offline)'}")
    print(f"  transport:     lxc-attach")
    print(f"  lxc-attach:    {lxc_res['lxc_attach_status']}" + (f" ({lxc_res['reason']})" if lxc_res['reason'] else ""))
    if lxc_res.get("guest_kernel"):
        print(f"  guest kernel:  {lxc_res['guest_kernel']}")
    if lxc_res.get("guest_user_id"):
        print(f"  guest identity:{lxc_res['guest_user_id']}")

    print("\n" + "=" * 59)
    print("Non-destructive diagnostic check completed cleanly.")
    print("Zero benchmark workloads were executed.")
    print("Zero disks or guest filesystems were modified.")
    print("=" * 59)

    return results


if __name__ == "__main__":
    from .config import get_config
    cfg = get_config(reload=True)
    run_connectivity_check(cfg)
