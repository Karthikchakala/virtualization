#!/usr/bin/env python3
"""
test_kvm_adapter.py - Unit and integration tests for KVM/QEMU benchmark adapter.
Tests:
- KVM Discovery (preferred VM, state, vCPU, RAM, disk, network, machine type, firmware)
- KVM Memory Breakdown (allocated vs actual consumption)
- KVM Disk Test (fio regular file validation, rejection of block devices)
- KVM Network Test (ping metrics parsing, iperf3 missing handling)
- KVM Isolation Audit (namespaces, cgroups, virtualization layer)
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmark.kvm_adapter import (
    KvmDiscovery,
    KvmLifecycle,
    KvmMetricsCollector,
    KvmStorageBenchmark,
    KvmNetworkBenchmark,
    KvmAppLatencyBenchmark,
    KvmIsolationAudit
)

class TestKvmAdapter(unittest.TestCase):

    def test_kvm_discovery_preferred_vm(self):
        vm_name = KvmDiscovery.get_preferred_vm("ubuntu")
        self.assertIsNotNone(vm_name, "Should discover an existing VM")
        self.assertEqual(vm_name, "ubuntu24.04")

        details = KvmDiscovery.inspect_vm(vm_name)
        self.assertEqual(details["name"], "ubuntu24.04")
        self.assertEqual(details["vcpus"], 2)
        self.assertEqual(details["memory_mb"], 2048)
        self.assertIn("pc-q35", details["machine_type"])
        self.assertEqual(details["firmware"], "BIOS")
        self.assertIn("devices", details["disk"])
        self.assertIn("interfaces", details["network"])

    def test_kvm_memory_breakdown_distinction(self):
        vm_name = KvmDiscovery.get_preferred_vm()
        breakdown = KvmMetricsCollector.get_memory_breakdown(vm_name)
        
        self.assertIn("allocated_vm_ram", breakdown)
        self.assertIn("actual_memory_consumption", breakdown)
        self.assertEqual(breakdown["allocated_vm_ram"]["configured_mb"], 2048)
        self.assertIn("distinction_note", breakdown)

    def test_kvm_storage_rejects_block_devices(self):
        with self.assertRaises(ValueError):
            KvmStorageBenchmark.run_fio_file_benchmark(Path("/dev/sda"))
        with self.assertRaises(ValueError):
            KvmStorageBenchmark.run_fio_file_benchmark(Path("/dev/nvme0n1"))

    def test_kvm_storage_safe_file_benchmark(self):
        test_file = PROJECT_ROOT / "results" / "test_fio_safe.dat"
        res = KvmStorageBenchmark.run_fio_file_benchmark(test_file, file_size_mb=4, runtime_sec=1)
        self.assertIn("status", res)
        # On this host, fio is not installed, so status should be 'unavailable'
        if res["status"] == "unavailable":
            self.assertIn("fio binary not found", res["reason"])
        else:
            self.assertEqual(res["status"], "success")

    def test_kvm_network_ping_parsing(self):
        # Test against local bridge address
        res = KvmNetworkBenchmark.run_ping_test("192.168.122.1", count=3)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["packet_loss_percent"], 0.0)
        self.assertIsNotNone(res["rtt_avg_ms"])
        self.assertGreater(res["rtt_avg_ms"], 0.0)

    def test_kvm_network_iperf3_unavailable(self):
        # iperf3 is not installed on host, so must gracefully report unavailable
        res = KvmNetworkBenchmark.run_iperf3_test("192.168.122.1")
        self.assertEqual(res["status"], "unavailable")
        self.assertIn("iperf3 binary not found", res["reason"])

    def test_kvm_isolation_audit(self):
        audit = KvmIsolationAudit.collect_host_isolation()
        self.assertEqual(audit["environment"], "host")
        self.assertIn("systemd_detect_virt", audit)
        self.assertIn("namespaces_pid1", audit)
        self.assertIn("cgroup_self", audit)

if __name__ == "__main__":
    unittest.main()
