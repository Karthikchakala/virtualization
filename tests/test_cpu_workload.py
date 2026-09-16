#!/usr/bin/env python3
"""
test_cpu_workload.py - Unit tests for deterministic CPU workload.
Verifies:
- deterministic execution
- checksum reproducibility
- configurable workload sizes
- error handling and non-zero exit codes on invalid arguments
- valid machine-readable JSON output
"""

import os
import sys
import json
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_CPU = PROJECT_ROOT / "workloads" / "dist" / "cpu_workload"

class TestCpuWorkload(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not DIST_CPU.exists():
            res = subprocess.run(["make", "-C", str(PROJECT_ROOT / "workloads"), "all"], capture_output=True, text=True)
            assert res.returncode == 0, f"Compilation failed: {res.stderr}"

    def test_cpu_binary_exists(self):
        self.assertTrue(DIST_CPU.exists(), "cpu_workload binary must exist in dist/")
        self.assertTrue(os.access(DIST_CPU, os.X_OK), "cpu_workload must be executable")

    def test_deterministic_checksum(self):
        """Two separate runs with identical inputs must yield identical checksums."""
        cmd = [str(DIST_CPU), "--size", "120", "--iterations", "2", "--warmup", "0", "--threads", "1"]
        res1 = subprocess.run(cmd, capture_output=True, text=True)
        res2 = subprocess.run(cmd, capture_output=True, text=True)

        self.assertEqual(res1.returncode, 0)
        self.assertEqual(res2.returncode, 0)

        out1 = json.loads(res1.stdout)
        out2 = json.loads(res2.stdout)

        self.assertEqual(out1["results"]["status"], "success")
        self.assertEqual(out2["results"]["status"], "success")
        self.assertEqual(out1["results"]["checksum"], out2["results"]["checksum"])
        self.assertTrue(out1["results"]["checksum"].startswith("0x"))

    def test_configurable_size(self):
        cmd_small = [str(DIST_CPU), "--size", "50", "--iterations", "1", "--warmup", "0"]
        cmd_large = [str(DIST_CPU), "--size", "100", "--iterations", "1", "--warmup", "0"]

        res_small = subprocess.run(cmd_small, capture_output=True, text=True)
        res_large = subprocess.run(cmd_large, capture_output=True, text=True)

        self.assertEqual(res_small.returncode, 0)
        self.assertEqual(res_large.returncode, 0)

        out_small = json.loads(res_small.stdout)
        out_large = json.loads(res_large.stdout)

        self.assertNotEqual(out_small["results"]["checksum"], out_large["results"]["checksum"])
        self.assertGreater(out_large["results"]["total_flops"], out_small["results"]["total_flops"])

    def test_invalid_arguments_returns_nonzero(self):
        invalid_cases = [
            ["--size", "-5"],
            ["--size", "0"],
            ["--iterations", "0"],
            ["--warmup", "-1"],
            ["--threads", "0"],
            ["--unknown-flag"]
        ]
        for args in invalid_cases:
            with self.subTest(args=args):
                res = subprocess.run([str(DIST_CPU)] + args, capture_output=True, text=True)
                self.assertNotEqual(res.returncode, 0, f"Expected non-zero exit for args: {args}")

if __name__ == "__main__":
    import os
    unittest.main()
