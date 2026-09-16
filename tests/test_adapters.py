#!/usr/bin/env python3
"""
tests/test_adapters.py - Unit Test Suite for Unified Environment Adapters.

Tests:
1. NormalizedState vocabulary and validation.
2. ExecutionResult & IdentityResult data models and serialization.
3. LocalTransport execution, timeout, and safety validation.
4. SSHTransport authentication precedence, credential masking, and safety guards.
5. LxcAttachTransport native execution and safety guards.
6. HostAdapter complete lifecycle (verify, prepare, deploy, execute, metrics, identity, status).
7. KvmAdapter virsh wrapping, status normalization, and telemetry parsing.
8. VirtualBoxAdapter VBoxManage wrapping, forwarded port routing, and telemetry parsing.
9. LxcAdapter native lxc-attach verification, cgroups v2 metrics, and kernel sharing proof.
10. create_adapter factory and diagnostic runner.
"""

import os
import sys
import unittest
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmark.runner.config import EnvironmentConfig
from benchmark.runner.environments import (
    BaseEnvironmentAdapter,
    NormalizedState,
    ExecutionResult,
    IdentityResult,
    BaseTransport,
    LocalTransport,
    SSHTransport,
    LxcAttachTransport,
    HostAdapter,
    KvmAdapter,
    VirtualBoxAdapter,
    LxcAdapter,
    create_adapter,
    list_registered_adapters,
    run_diagnostics
)
from collector.common import SafetyViolationError


class TestNormalizedModels(unittest.TestCase):
    """Verifies NormalizedState, ExecutionResult, and IdentityResult data structures."""

    def test_normalized_states(self):
        self.assertTrue(NormalizedState.is_valid("running"))
        self.assertTrue(NormalizedState.is_valid("stopped"))
        self.assertTrue(NormalizedState.is_valid("unavailable"))
        self.assertTrue(NormalizedState.is_valid("error"))
        self.assertTrue(NormalizedState.is_valid("unknown"))
        self.assertFalse(NormalizedState.is_valid("paused"))
        self.assertFalse(NormalizedState.is_valid("shut off"))

    def test_execution_result_contract(self):
        res = ExecutionResult(
            exit_code=0,
            stdout="success output",
            stderr="",
            duration_sec=0.123456,
            timed_out=False,
            status="success",
            command="uname -r"
        )
        self.assertTrue(res.success)
        d = res.to_dict()
        self.assertEqual(d["exit_code"], 0)
        self.assertEqual(d["stdout"], "success output")
        self.assertFalse(d["timed_out"])
        self.assertEqual(d["duration_sec"], 0.123456)

        fail_res = ExecutionResult(
            exit_code=1,
            stdout="",
            stderr="error",
            duration_sec=0.01,
            timed_out=False,
            status="failed"
        )
        self.assertFalse(fail_res.success)

        timeout_res = ExecutionResult(
            exit_code=-1,
            stdout="",
            stderr="timed out",
            duration_sec=5.0,
            timed_out=True,
            status="timeout"
        )
        self.assertFalse(timeout_res.success)

    def test_identity_result_contract(self):
        ident = IdentityResult(
            environment="kvm",
            classification="Type-1-like",
            virtualization_type="kvm",
            kernel_release="6.8.0-generic",
            vcpus=2,
            memory_mb=2048,
            ip_address="192.168.122.100",
            systemd_detect_virt="kvm",
            is_shared_kernel=False
        )
        d = ident.to_dict()
        self.assertEqual(d["environment"], "kvm")
        self.assertEqual(d["vcpus"], 2)
        self.assertEqual(d["memory_mb"], 2048)
        self.assertEqual(d["ip_address"], "192.168.122.100")
        self.assertEqual(d["systemd_detect_virt"], "kvm")
        self.assertFalse(d["is_shared_kernel"])


class TestTransports(unittest.TestCase):
    """Verifies LocalTransport, SSHTransport, and LxcAttachTransport."""

    def test_local_transport_safe_execution(self):
        transport = LocalTransport()
        res = transport.execute("echo 'test_local'", timeout=5)
        self.assertTrue(res.success)
        self.assertEqual(res.stdout.strip(), "test_local")
        self.assertGreater(res.duration_sec, 0.0)

    def test_local_transport_blocks_destructive_commands(self):
        transport = LocalTransport()
        with self.assertRaises(SafetyViolationError):
            transport.execute("mkfs.ext4 /dev/nvme0n1", timeout=5)

        with self.assertRaises(SafetyViolationError):
            transport.execute("dd if=/dev/zero of=/dev/sda bs=1M", timeout=5)

    def test_local_transport_timeout(self):
        transport = LocalTransport()
        res = transport.execute("sleep 5", timeout=1)
        self.assertTrue(res.timed_out)
        self.assertFalse(res.success)
        self.assertEqual(res.status, "timeout")

    def test_local_transport_copy_and_sha256(self):
        transport = LocalTransport()
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source.txt"
            src.write_text("transport_test_data")
            dst = Path(tmpdir) / "dest" / "target.txt"

            copied = transport.copy_file(src, str(dst))
            self.assertTrue(copied)
            self.assertTrue(dst.exists())
            self.assertEqual(transport.read_file(str(dst)), "transport_test_data")

            src_hash = transport.compute_sha256(str(src))
            dst_hash = transport.compute_sha256(str(dst))
            self.assertIsNotNone(src_hash)
            self.assertEqual(src_hash, dst_hash)

    def test_ssh_transport_credentials_masking(self):
        transport = SSHTransport(
            host="192.168.122.179",
            port=22,
            user="testuser",
            password="super_secret_password_123"
        )
        repr_str = repr(transport)
        self.assertNotIn("super_secret_password_123", repr_str)
        self.assertIn("********", repr_str)
        self.assertEqual(transport.auth_method, "password")

    def test_ssh_transport_blocks_destructive_commands(self):
        transport = SSHTransport(host="192.168.122.179", port=22)
        with self.assertRaises(SafetyViolationError):
            transport.execute("rm -rf /etc", timeout=5)

    def test_lxc_attach_transport_command_structure(self):
        transport = LxcAttachTransport(container_name="lxc-ubuntu")
        repr_str = repr(transport)
        self.assertIn("lxc-ubuntu", repr_str)

        with self.assertRaises(SafetyViolationError):
            transport.execute("fdisk /dev/sda", timeout=5)


class TestHostAdapter(unittest.TestCase):
    """Tests the Host bare-metal baseline adapter."""

    def setUp(self):
        self.adapter = HostAdapter()

    def test_host_verification_and_status(self):
        self.assertTrue(self.adapter.verify())
        self.assertEqual(self.adapter.get_status(), NormalizedState.RUNNING)
        self.assertEqual(self.adapter.transport_name, "local")

    def test_host_prepare(self):
        prep = self.adapter.prepare()
        self.assertEqual(prep["status"], "ready")
        self.assertTrue(prep["prepared"])
        self.assertTrue(Path(prep["target_path"]).exists())

    def test_host_deploy_workload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_bin = Path(tmpdir) / "dummy_workload"
            dummy_bin.write_bytes(b"\x7fELFtestbinarypayload")
            dest = Path(tmpdir) / "scratch" / "dummy_workload"

            # 1. First deployment: transfers file
            res1 = self.adapter.deploy_workload(dummy_bin, target_dest=str(dest))
            self.assertTrue(res1["deployed"])
            self.assertTrue(res1["transferred"])
            self.assertTrue(dest.exists())

            # 2. Second deployment: skips transfer because hash is identical
            res2 = self.adapter.deploy_workload(dummy_bin, target_dest=str(dest))
            self.assertTrue(res2["deployed"])
            self.assertFalse(res2["transferred"])

    def test_host_metrics_and_identity(self):
        metrics = self.adapter.collect_metrics()
        self.assertIn("loadavg", metrics)
        self.assertIn("logical_cpus", metrics)

        ident = self.adapter.get_identity()
        self.assertEqual(ident.environment, "host")
        self.assertIsNotNone(ident.kernel_release)
        self.assertFalse(ident.is_shared_kernel)
        self.assertIn("bare-metal", ident.systemd_detect_virt.lower())


class TestKvmAdapter(unittest.TestCase):
    """Tests the KVM/QEMU libvirt adapter with mocks."""

    def setUp(self):
        cfg = EnvironmentConfig(
            name="kvm",
            display_name="KVM/QEMU",
            classification="Type-1-like",
            virtualization_type="kvm",
            transport="ssh",
            target_path="/tmp/cc2_workloads",
            vm_name="ubuntu24.04",
            ssh_host="192.168.122.179",
            ssh_port=22,
            ssh_user="karthik-chakala"
        )
        self.adapter = KvmAdapter(cfg)

    @patch("benchmark.runner.environments.kvm.shutil.which")
    @patch.object(KvmAdapter, "_run_virsh")
    def test_kvm_status_normalization(self, mock_virsh, mock_which):
        mock_which.return_value = "/usr/bin/virsh"

        # 1. Running state
        mock_virsh.return_value = subprocess.CompletedProcess(args="", returncode=0, stdout="running\n", stderr="")
        self.assertEqual(self.adapter.get_status(), NormalizedState.RUNNING)

        # 2. Stopped state (shut off)
        mock_virsh.return_value = subprocess.CompletedProcess(args="", returncode=0, stdout="shut off\n", stderr="")
        self.assertEqual(self.adapter.get_status(), NormalizedState.STOPPED)

        # 3. Domain not found
        mock_virsh.return_value = subprocess.CompletedProcess(args="", returncode=1, stdout="", stderr="domain not found")
        self.assertEqual(self.adapter.get_status(), NormalizedState.UNAVAILABLE)

    @patch.object(KvmAdapter, "_run_virsh")
    def test_kvm_domstats_parsing(self, mock_virsh):
        mock_virsh.return_value = subprocess.CompletedProcess(
            args="",
            returncode=0,
            stdout="cpu.time=1234567890\nballoon.current=2097152\nballoon.maximum=2097152\n",
            stderr=""
        )
        metrics = self.adapter.collect_metrics()
        self.assertEqual(metrics.get("cpu_time_ns"), 1234567890)
        self.assertEqual(metrics.get("balloon_current_kb"), 2097152)

    @patch.object(KvmAdapter, "get_status")
    def test_kvm_prepare_already_running(self, mock_status):
        mock_status.return_value = NormalizedState.RUNNING
        with patch.object(self.adapter.transport, "is_reachable", return_value=True):
            prep = self.adapter.prepare()
            self.assertEqual(prep["status"], "already_running")
            self.assertTrue(prep["ready"])


class TestVirtualBoxAdapter(unittest.TestCase):
    """Tests the VirtualBox VBoxManage adapter with mocks."""

    def setUp(self):
        cfg = EnvironmentConfig(
            name="virtualbox",
            display_name="VirtualBox",
            classification="Type-2",
            virtualization_type="virtualbox",
            transport="ssh",
            target_path="/tmp/cc2_workloads",
            vm_name="Ubuntu-Server-VBox",
            ssh_host="127.0.0.1",
            ssh_port=2222,
            ssh_user="karthik-chakala"
        )
        self.adapter = VirtualBoxAdapter(cfg)

    @patch("benchmark.runner.environments.virtualbox.shutil.which")
    @patch.object(VirtualBoxAdapter, "_run_vboxmanage")
    def test_vbox_status_normalization(self, mock_vbox, mock_which):
        mock_which.return_value = "/usr/bin/VBoxManage"

        # 1. Running VM
        mock_vbox.return_value = subprocess.CompletedProcess(
            args="",
            returncode=0,
            stdout='"Ubuntu-Server-VBox" {8a699556-1ddf-41cf-b252-c7c8b10255ac}\n',
            stderr=""
        )
        self.assertEqual(self.adapter.get_status(), NormalizedState.RUNNING)

        # 2. Registered but powered off
        def vbox_side_effect(args, timeout=10):
            if "runningvms" in args:
                return subprocess.CompletedProcess(args="", returncode=0, stdout="", stderr="")
            if "vms" in args:
                return subprocess.CompletedProcess(
                    args="",
                    returncode=0,
                    stdout='"Ubuntu-Server-VBox" {8a699556-1ddf-41cf-b252-c7c8b10255ac}\n',
                    stderr=""
                )
            return subprocess.CompletedProcess(args="", returncode=1, stdout="", stderr="")

        mock_vbox.side_effect = vbox_side_effect
        self.assertEqual(self.adapter.get_status(), NormalizedState.STOPPED)

    def test_vbox_forwarded_port_configuration(self):
        self.assertEqual(self.adapter.transport.host, "127.0.0.1")
        self.assertEqual(self.adapter.transport.port, 2222)


class TestLxcAdapter(unittest.TestCase):
    """Tests the native LXC adapter with mocks."""

    def setUp(self):
        cfg = EnvironmentConfig(
            name="lxc",
            display_name="Native LXC",
            classification="OS-Level Virtualization",
            virtualization_type="lxc",
            transport="lxc-attach",
            target_path="/tmp/cc2_workloads",
            container_name="lxc-ubuntu"
        )
        self.adapter = LxcAdapter(cfg)

    def test_lxc_transport_is_strictly_attach(self):
        # Enforce that LXC NEVER defaults to SSH or Docker
        self.assertEqual(self.adapter.transport_name, "lxc-attach")
        self.assertIsInstance(self.adapter.transport, LxcAttachTransport)
        self.assertNotIsInstance(self.adapter.transport, SSHTransport)

    @patch("benchmark.runner.environments.lxc.shutil.which")
    @patch.object(LxcAdapter, "_run_lxc_cmd")
    def test_lxc_status_normalization(self, mock_lxc, mock_which):
        mock_which.return_value = "/usr/bin/lxc-info"

        # 1. Running state
        mock_lxc.return_value = subprocess.CompletedProcess(
            args="",
            returncode=0,
            stdout="State:          RUNNING\n",
            stderr=""
        )
        self.assertEqual(self.adapter.get_status(), NormalizedState.RUNNING)

        # 2. Stopped state
        mock_lxc.return_value = subprocess.CompletedProcess(
            args="",
            returncode=0,
            stdout="State:          STOPPED\n",
            stderr=""
        )
        self.assertEqual(self.adapter.get_status(), NormalizedState.STOPPED)

    def test_lxc_kernel_sharing_proof(self):
        # Mocking container kernel matching host kernel
        def mock_exec_fn(cmd, timeout=60, env_vars=None):
            if "uname" in cmd:
                return ExecutionResult(exit_code=0, stdout="7.0.0-31-generic\n", stderr="", duration_sec=0.01, status="success")
            elif "hostname" in cmd:
                return ExecutionResult(exit_code=0, stdout="lxc-ubuntu\n", stderr="", duration_sec=0.01, status="success")
            elif "systemd-detect-virt" in cmd:
                return ExecutionResult(exit_code=0, stdout="lxc\n", stderr="", duration_sec=0.01, status="success")
            return ExecutionResult(exit_code=0, stdout="", stderr="", duration_sec=0.01, status="success")

        with patch.object(self.adapter, "get_status", return_value=NormalizedState.RUNNING), \
             patch.object(self.adapter.transport, "execute", side_effect=mock_exec_fn), \
             patch("subprocess.run") as mock_subproc:

            mock_subproc.return_value = subprocess.CompletedProcess(args="", returncode=0, stdout="7.0.0-31-generic\n", stderr="")

            ident = self.adapter.get_identity()
            self.assertTrue(ident.is_shared_kernel)
            self.assertEqual(ident.kernel_release, "7.0.0-31-generic")
            self.assertEqual(ident.systemd_detect_virt, "lxc")


class TestAdapterFactoryAndDiagnostics(unittest.TestCase):
    """Tests adapter instantiation through factory and non-destructive diagnostic runner."""

    def test_registered_adapters_list(self):
        adapters = list_registered_adapters()
        self.assertIn("host", adapters)
        self.assertIn("kvm", adapters)
        self.assertIn("virtualbox", adapters)
        self.assertIn("lxc", adapters)

    def test_factory_instantiates_all_types(self):
        host = create_adapter("host")
        self.assertIsInstance(host, HostAdapter)

        kvm = create_adapter("kvm")
        self.assertIsInstance(kvm, KvmAdapter)

        vbox = create_adapter("virtualbox")
        self.assertIsInstance(vbox, VirtualBoxAdapter)

        lxc = create_adapter("lxc")
        self.assertIsInstance(lxc, LxcAdapter)

    def test_factory_rejects_unknown(self):
        with self.assertRaises(ValueError):
            create_adapter("docker")

        with self.assertRaises(ValueError):
            create_adapter("xen")

    def test_diagnostics_execution(self):
        # Diagnostic runner must complete with 0 without running any benchmarks
        exit_code = run_diagnostics()
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
