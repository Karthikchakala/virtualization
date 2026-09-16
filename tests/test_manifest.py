#!/usr/bin/env python3
"""
test_manifest.py - Unit tests for workloads/MANIFEST.json and package integrity.
Verifies:
- workloads/dist/ contains binaries
- MANIFEST.json exists and is valid
- SHA256 recorded in MANIFEST.json matches actual file checksums
"""

import sys
import json
import hashlib
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_FILE = PROJECT_ROOT / "workloads" / "MANIFEST.json"
DIST_DIR = PROJECT_ROOT / "workloads" / "dist"

def calculate_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

class TestManifest(unittest.TestCase):

    def test_manifest_file_exists(self):
        self.assertTrue(MANIFEST_FILE.exists(), "workloads/MANIFEST.json must exist")

    def test_manifest_checksums_match_dist_binaries(self):
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.assertIn("package_name", manifest)
        self.assertIn("compiler", manifest)
        self.assertIn("compiler_version", manifest)
        self.assertIn("workloads", manifest)

        for w in manifest["workloads"]:
            binary_name = w["binary"]
            binary_path = DIST_DIR / binary_name
            self.assertTrue(binary_path.exists(), f"Binary {binary_name} missing from dist/")

            actual_sha256 = calculate_sha256(binary_path)
            self.assertEqual(
                actual_sha256,
                w["sha256"],
                f"SHA256 mismatch for {binary_name}! Manifest: {w['sha256']}, Actual: {actual_sha256}"
            )

if __name__ == "__main__":
    unittest.main()
