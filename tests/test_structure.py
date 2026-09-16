#!/usr/bin/env python3
"""
test_structure.py - Verifies the required project folder layout.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class TestProjectStructure(unittest.TestCase):

    def test_required_directories_exist(self):
        required_dirs = [
            "benchmark",
            "workloads",
            "collector",
            "analysis",
            "results",
            "dashboard",
            "docs",
            "tests"
        ]
        for dirname in required_dirs:
            p = PROJECT_ROOT / dirname
            self.assertTrue(p.exists(), f"Required directory '{dirname}' missing at {p}")
            self.assertTrue(p.is_dir(), f"'{dirname}' must be a directory")

    def test_key_files_exist(self):
        required_files = [
            PROJECT_ROOT / "collector" / "common.py",
            PROJECT_ROOT / "collector" / "inventory_collector.py",
            PROJECT_ROOT / "collector" / "env_discovery.sh",
            PROJECT_ROOT / "workloads" / "cpu_workload.c",
            PROJECT_ROOT / "workloads" / "memory_workload.c",
            PROJECT_ROOT / "workloads" / "Makefile",
            PROJECT_ROOT / "benchmark" / "driver.py",
            PROJECT_ROOT / "analysis" / "stats.py",
            PROJECT_ROOT / "analysis" / "validator.py",
            PROJECT_ROOT / "results" / "host_inventory.json",
        ]
        for f in required_files:
            self.assertTrue(f.exists(), f"Required file missing: {f}")

if __name__ == "__main__":
    unittest.main()
