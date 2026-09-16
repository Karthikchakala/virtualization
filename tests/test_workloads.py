#!/usr/bin/env python3
"""
test_workloads.py - Verifies deterministic execution of C benchmark workloads.
"""

import sys
import json
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class TestWorkloads(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Build workloads
        res = subprocess.run(["make", "-C", str(PROJECT_ROOT / "workloads"), "all"], capture_output=True, text=True)
        assert res.returncode == 0, f"Compilation failed: {res.stderr}"

    def test_cpu_workload_deterministic_output(self):
        bin_path = PROJECT_ROOT / "workloads" / "cpu_workload"
        self.assertTrue(bin_path.exists(), "cpu_workload binary not found")

        # Run twice with identical parameters
        res1 = subprocess.run([str(bin_path), "--size", "100", "--iterations", "2"], capture_output=True, text=True)
        res2 = subprocess.run([str(bin_path), "--size", "100", "--iterations", "2"], capture_output=True, text=True)

        self.assertEqual(res1.returncode, 0)
        self.assertEqual(res2.returncode, 0)

        data1 = json.loads(res1.stdout)
        data2 = json.loads(res2.stdout)

        self.assertEqual(data1["workload"], "cpu_deterministic")
        self.assertEqual(data1["status"], "success")
        self.assertGreater(data1["elapsed_sec"], 0.0)
        self.assertGreater(data1["gflops"], 0.0)
        # Verify deterministic mathematical output via identical checksum
        self.assertEqual(data1["checksum"], data2["checksum"], "Checksums must match for identical runs")

    def test_memory_workload_deterministic_output(self):
        bin_path = PROJECT_ROOT / "workloads" / "memory_workload"
        self.assertTrue(bin_path.exists(), "memory_workload binary not found")

        res1 = subprocess.run([str(bin_path), "--buffer-mb", "16", "--passes", "2"], capture_output=True, text=True)
        res2 = subprocess.run([str(bin_path), "--buffer-mb", "16", "--passes", "2"], capture_output=True, text=True)

        self.assertEqual(res1.returncode, 0)
        self.assertEqual(res2.returncode, 0)

        data1 = json.loads(res1.stdout)
        data2 = json.loads(res2.stdout)

        self.assertEqual(data1["workload"], "memory_deterministic")
        self.assertEqual(data1["status"], "success")
        self.assertGreater(data1["elapsed_sec"], 0.0)
        self.assertGreater(data1["throughput_mb_s"], 0.0)
        self.assertEqual(data1["checksum"], data2["checksum"], "Memory checksums must match for identical runs")

if __name__ == "__main__":
    unittest.main()
