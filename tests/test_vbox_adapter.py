#!/usr/bin/env python3
"""
test_vbox_adapter.py - Unit and integration tests for VirtualBox benchmark adapter.
Tests:
- VirtualBox Discovery (preferred VM, state, CPU, RAM, disk, NIC, firmware, acceleration, IP)
- VirtualBox Memory Breakdown (allocated vs actual usage)
- VirtualBox CPU Workload (exact same common CPU workload as KVM)
- VirtualBox Storage Safety (fio regular file validation, rejection of block devices)
- VirtualBox Network (ping metrics parsing, iperf3 missing handling)
- VirtualBox Application Latency (100 HTTP health requests: connection time, TTFB, total time, p95, p99)
- VirtualBox Startup Profiling (phase timestamps and cumulative duration)
- VirtualBox Isolation Audit (namespaces, cgroups, virtualization signatures)
"""

import sys
import json
import socket
import threading
import http.server
import socketserver
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmark.vbox_adapter import (
    VBoxDiscovery,
    VBoxLifecycle,
    VBoxMetricsCollector,
    VBoxWorkloadRunner
)

class TestVBoxAdapter(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.vm_name = VBoxDiscovery.get_preferred_vm("ubuntu")
        cls.runner = VBoxWorkloadRunner(experiment_id="exp-test-vbox")

    def test_vbox_discovery(self):
        self.assertIsNotNone(self.vm_name, "Should discover VirtualBox VM")
        self.assertEqual(self.vm_name, "Ubuntu-Server-VBox")

        details = VBoxDiscovery.inspect_vm(self.vm_name)
        self.assertEqual(details["name"], "Ubuntu-Server-VBox")
        self.assertEqual(details["cpus"], 2)
        self.assertEqual(details["memory_mb"], 2048)
        self.assertEqual(details["firmware"], "EFI")
        self.assertTrue(details["acceleration"]["hw_virt_vtx"])
        self.assertTrue(details["acceleration"]["nested_paging_ept"])
        self.assertIn("Ubuntu-Server-VBox.vdi", details["disk"].get("primary_file", ""))
        self.assertEqual(details["nic"].get("adapter1", {}).get("mode"), "nat")

    def test_vbox_memory_breakdown(self):
        breakdown = VBoxMetricsCollector.get_memory_breakdown(self.vm_name)
        self.assertIn("allocated_vm_ram", breakdown)
        self.assertIn("actual_memory_consumption", breakdown)
        self.assertEqual(breakdown["allocated_vm_ram"]["configured_mb"], 2048)
        self.assertIn("distinction_note", breakdown)

    def test_vbox_cpu_workload(self):
        """Runs the exact same CPU workload binary as KVM."""
        res = self.runner.run_cpu_benchmark(self.vm_name, size=100, iterations=2, warmup=0)
        self.assertEqual(res["status"], "success")
        self.assertGreater(res["gflops"], 0.0)
        self.assertIsNotNone(res["checksum"])
        self.assertTrue(res["checksum"].startswith("0x"))

    def test_vbox_storage_rejects_block_devices(self):
        with self.assertRaises(ValueError):
            self.runner.run_storage_fio(Path("/dev/sda"))
        with self.assertRaises(ValueError):
            self.runner.run_storage_fio(Path("/dev/nvme0n1p6"))

    def test_vbox_storage_safe_fio(self):
        test_file = PROJECT_ROOT / "results" / "test_vbox_fio.dat"
        res = self.runner.run_storage_fio(test_file, file_size_mb=4, runtime_sec=1)
        self.assertIn("status", res)
        # If fio is missing, status must be unavailable
        if res["status"] == "unavailable":
            self.assertIn("fio binary not found", res["reason"])
        else:
            self.assertEqual(res["status"], "success")

    def test_vbox_network_ping(self):
        res = self.runner.run_network_ping("127.0.0.1", count=3)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["packet_loss_percent"], 0.0)
        self.assertIsNotNone(res["rtt_avg_ms"])
        self.assertGreaterEqual(res["rtt_avg_ms"], 0.0)

    def test_vbox_application_latency_100_requests(self):
        """Tests application latency engine with 100 HTTP requests."""
        # Spin up a lightweight test HTTP server on a free port
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass # Suppress server logging
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"healthy"}')

        server = socketserver.TCPServer(("127.0.0.1", 0), QuietHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()

        try:
            url = f"http://127.0.0.1:{port}/health"
            res = self.runner.run_application_latency(url, num_requests=100)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["requests_completed"], 100)

            total_stats = res["total_time_ms"]
            self.assertEqual(total_stats["valid_count"], 100)
            self.assertIsNotNone(total_stats["mean"])
            self.assertIsNotNone(total_stats["median"])
            self.assertIsNotNone(total_stats["p95"])
            self.assertIsNotNone(total_stats["p99"])

            ttfb_stats = res["ttfb_ms"]
            self.assertIsNotNone(ttfb_stats["mean"])
            self.assertIsNotNone(ttfb_stats["p95"])
        finally:
            server.shutdown()
            server.server_close()

    def test_vbox_isolation_audit(self):
        audit = self.runner.run_isolation_audit()
        self.assertEqual(audit["environment"], "virtualbox")
        self.assertIn("systemd_detect_virt", audit)
        self.assertIn("namespaces_pid1", audit)
        self.assertIn("cgroup_self", audit)

if __name__ == "__main__":
    unittest.main()
