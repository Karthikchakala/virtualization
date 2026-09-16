#!/usr/bin/env python3
"""
test_lxc_adapter.py - Unit and integration tests for Native LXC benchmark adapter.
Tests:
- LXC Discovery (preferred container, state, CPU/memory limits, rootfs, network bridge, cgroups v2)
- LXC Memory Breakdown (cgroups v2 limits vs actual memory consumption)
- LXC CPU Workload (exact same common CPU workload binary as KVM and VirtualBox)
- LXC Memory Workload (exact same deterministic memory workload binary)
- LXC Storage Safety (fio regular file validation, rejection of block devices)
- LXC Network (ping metrics parsing, iperf3 missing handling)
- LXC Application Latency (100 HTTP health requests: connection time, TTFB, total time, p95, p99)
- LXC Startup Profiling (phase timestamps and cumulative duration)
- LXC Isolation & Kernel Sharing Proof (demonstrating container kernel == host kernel)
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

from benchmark.lxc_adapter import (
    LxcDiscovery,
    LxcLifecycle,
    LxcMetricsCollector,
    LxcIsolationAudit,
    LxcWorkloadRunner
)

class TestLxcAdapter(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.container_name = LxcDiscovery.get_preferred_container("ubuntu")
        cls.runner = LxcWorkloadRunner(experiment_id="exp-test-lxc")

    def test_lxc_discovery(self):
        self.assertIsNotNone(self.container_name, "Should discover LXC container")
        self.assertEqual(self.container_name, "lxc-ubuntu")

        details = LxcDiscovery.inspect_container(self.container_name)
        self.assertEqual(details["name"], "lxc-ubuntu")
        self.assertIn("virtualization_type", details)
        self.assertIn("OS-level virtualization", details["virtualization_type"])
        self.assertEqual(details["cgroups"]["version"], "v2")
        self.assertIn("cpu", details["cgroups"]["controllers_available"])
        self.assertIn("memory", details["cgroups"]["controllers_available"])
        self.assertEqual(details["network"]["bridge"], "lxcbr0")
        self.assertEqual(details["network"]["bridge_ip"], "10.0.3.1")
        self.assertEqual(details["host_kernel"], details["container_kernel"])

    def test_lxc_memory_breakdown(self):
        breakdown = LxcMetricsCollector.get_memory_breakdown(self.container_name)
        self.assertIn("configured_memory_limit", breakdown)
        self.assertIn("actual_memory_consumption", breakdown)
        self.assertIn("distinction_note", breakdown)
        # Verify note explains cgroups v2 boundary vs active RSS
        self.assertIn("cgroups v2 boundary", breakdown["distinction_note"])
        self.assertIn("virtio-balloon", breakdown["distinction_note"])

    def test_lxc_cpu_workload(self):
        """Runs the exact same CPU workload binary as KVM and VirtualBox."""
        res = self.runner.run_cpu_benchmark(self.container_name, size=100, iterations=2, warmup=0)
        self.assertEqual(res["status"], "success")
        self.assertGreater(res["gflops"], 0.0)
        self.assertIsNotNone(res["checksum"])
        self.assertTrue(res["checksum"].startswith("0x"))
        self.assertIn("cgroup_telemetry", res)
        self.assertIn("cpu", res["cgroup_telemetry"])

    def test_lxc_memory_workload(self):
        """Runs the exact same deterministic memory workload binary."""
        res = self.runner.run_memory_benchmark(self.container_name, buffer_mb=16, passes=2, stride=64)
        self.assertEqual(res["status"], "success")
        self.assertGreater(res["throughput_mb_s"], 0.0)
        self.assertIsNotNone(res["checksum"])
        self.assertTrue(res["checksum"].startswith("0x"))
        self.assertIn("memory_breakdown", res)

    def test_lxc_storage_rejects_block_devices(self):
        with self.assertRaises(ValueError):
            self.runner.run_storage_fio(Path("/dev/sda"))
        with self.assertRaises(ValueError):
            self.runner.run_storage_fio(Path("/dev/nvme0n1p6"))

    def test_lxc_storage_safe_fio(self):
        test_file = PROJECT_ROOT / "results" / "test_lxc_fio.dat"
        res = self.runner.run_storage_fio(test_file, file_size_mb=4, runtime_sec=1)
        self.assertIn("status", res)
        if res["status"] == "unavailable":
            self.assertIn("fio binary not found", res["reason"])
        else:
            self.assertEqual(res["status"], "success")

    def test_lxc_network_ping(self):
        # Ping bridge interface or loopback
        res = self.runner.run_network_ping("127.0.0.1", count=3)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["packet_loss_percent"], 0.0)
        self.assertIsNotNone(res["rtt_avg_ms"])
        self.assertGreaterEqual(res["rtt_avg_ms"], 0.0)

    def test_lxc_network_iperf3_unavailable(self):
        res = self.runner.run_iperf3_test("127.0.0.1", duration=1)
        self.assertEqual(res["status"], "unavailable")
        self.assertIn("iperf3 binary not found", res["reason"])

    def test_lxc_application_latency_100_requests(self):
        """Tests application latency engine with 100 HTTP requests."""
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"healthy"}')

        server = socketserver.TCPServer(("127.0.0.1", 0), QuietHandler)
        port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            url = f"http://127.0.0.1:{port}/health"
            res = self.runner.run_application_latency(url, num_requests=100)
            self.assertEqual(res["status"], "success")
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

    def test_lxc_startup_profiling(self):
        """Tests startup phase profiling and structure."""
        startup_report = LxcLifecycle.measure_full_startup(self.container_name, timeout=2)
        self.assertEqual(startup_report["container_name"], self.container_name)
        self.assertIn("phases", startup_report)
        phases = startup_report["phases"]
        self.assertIn("lxc_start", phases)
        self.assertIn("container_ready", phases)
        self.assertIn("network_ready", phases)
        self.assertIn("application_ready", phases)
        self.assertIn("total_startup_duration_sec", startup_report)

    def test_lxc_isolation_and_kernel_sharing(self):
        """Empirically demonstrates that LXC shares the host Linux kernel."""
        audit = LxcIsolationAudit.audit_isolation(self.container_name)
        self.assertEqual(audit["environment"], "lxc")
        self.assertTrue(audit["kernel_shared"])
        self.assertEqual(audit["host_kernel_release"], audit["container_kernel_release"])
        self.assertIn("kernel_sharing_proof", audit)
        self.assertIn("namespaces_self", audit)
        self.assertIn("net", audit["namespaces_self"])
        self.assertIn("pid", audit["namespaces_self"])
        self.assertIn("mnt", audit["namespaces_self"])
        self.assertIn("cgroup", audit["namespaces_self"])
        self.assertIn("uts", audit["namespaces_self"])

if __name__ == "__main__":
    unittest.main()
