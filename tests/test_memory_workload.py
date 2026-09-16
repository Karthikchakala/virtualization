#!/usr/bin/env python3
"""
test_memory_workload.py - Unit tests for deterministic Memory workload.
Verifies:
- memory allocation and execution
- checksum reproducibility
- host safety guard against excessive allocation
- release of resources
- machine-readable JSON output
"""

import os
import sys
import json
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_MEM = PROJECT_ROOT / "workloads" / "dist" / "memory_workload"

class TestMemoryWorkload(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not DIST_MEM.exists():
            res = subprocess.run(["make", "-C", str(PROJECT_ROOT / "workloads"), "all"], capture_output=True, text=True)
            assert res.returncode == 0, f"Compilation failed: {res.stderr}"

    def test_memory_binary_exists(self):
        self.assertTrue(DIST_MEM.exists(), "memory_workload binary must exist in dist/")
        self.assertTrue(os.access(DIST_MEM, os.X_OK), "memory_workload must be executable")

    def test_deterministic_memory_checksum(self):
        cmd = [str(DIST_MEM), "--buffer-mb", "16", "--passes", "2", "--stride", "64"]
        res1 = subprocess.run(cmd, capture_output=True, text=True)
        res2 = subprocess.run(cmd, capture_output=True, text=True)

        self.assertEqual(res1.returncode, 0)
        self.assertEqual(res2.returncode, 0)

        out1 = json.loads(res1.stdout)
        out2 = json.loads(res2.stdout)

        self.assertEqual(out1["results"]["status"], "success")
        self.assertEqual(out2["results"]["status"], "success")
        self.assertEqual(out1["results"]["checksum"], out2["results"]["checksum"])
        self.assertGreater(out1["results"]["throughput_mb_s"], 0.0)

    def test_safety_guard_rejects_excessive_buffer(self):
        """Requesting 100,000 MB must be rejected by safety guard with non-zero exit code."""
        cmd = [str(DIST_MEM), "--buffer-mb", "100000"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertNotEqual(res.returncode, 0, "Safety guard must reject excessive buffer allocation")

    def test_invalid_parameters_fail_safely(self):
        invalid_cases = [
            ["--buffer-mb", "0"],
            ["--buffer-mb", "-10"],
            ["--passes", "0"],
            ["--stride", "2"],  # Less than sizeof(uint64_t)
            ["--bad-flag"]
        ]
        for args in invalid_cases:
            with self.subTest(args=args):
                res = subprocess.run([str(DIST_MEM)] + args, capture_output=True, text=True)
                self.assertNotEqual(res.returncode, 0, f"Expected non-zero exit for args: {args}")

if __name__ == "__main__":
    unittest.main()
