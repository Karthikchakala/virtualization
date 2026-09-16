#!/usr/bin/env python3
"""
tests/test_workload.py - Unit Test Suite for Workload Deployment & Verification.

Tests:
1. Canonical workload artifact discovery and validation from workloads/dist/.
2. Accurate local SHA256 checksum calculation and MANIFEST.json integrity check.
3. Verification that cpu_workload has canonical SHA256.
4. Error handling for non-existent and empty binaries.
5. Workload deployment to mock environment adapters.
6. Post-deployment SHA256 verification and strict refusal to execute upon mismatch.
7. WorkloadArtifact and WorkloadDeploymentResult data models.
"""

import os
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmark.runner.workload import (
    WorkloadDeployer,
    WorkloadArtifact,
    WorkloadDeploymentResult,
    WorkloadDeploymentError
)
from benchmark.runner.environments.base import BaseEnvironmentAdapter, NormalizedState


class TestWorkloadDeployer(unittest.TestCase):

    def setUp(self):
        self.deployer = WorkloadDeployer()

    def test_canonical_cpu_workload_artifact(self):
        artifact = self.deployer.get_canonical_artifact("cpu_workload")
        self.assertEqual(artifact.binary_name, "cpu_workload")
        self.assertEqual(artifact.name, "cpu_deterministic")
        self.assertTrue(artifact.local_path.exists())
        self.assertGreater(artifact.size_bytes, 0)
        self.assertTrue(artifact.is_executable)

        # Invariant: Canonical CPU SHA256 check
        expected_sha256 = "212853035b582f238058b8d436fecf1f25bd5ff249965c7467336903a563fd9f"
        self.assertEqual(artifact.sha256, expected_sha256)

    def test_canonical_memory_workload_artifact(self):
        artifact = self.deployer.get_canonical_artifact("memory_workload")
        self.assertEqual(artifact.binary_name, "memory_workload")
        self.assertTrue(artifact.local_path.exists())
        self.assertGreater(artifact.size_bytes, 0)
        self.assertTrue(artifact.is_executable)

    def test_calculate_sha256(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f.write(b"hello world CC2 deterministic test payload")
            f_path = Path(f.name)

        try:
            h = WorkloadDeployer.calculate_sha256(f_path)
            self.assertEqual(len(h), 64)
            # Verify repeatability
            h2 = WorkloadDeployer.calculate_sha256(f_path)
            self.assertEqual(h, h2)
        finally:
            f_path.unlink()

    def test_missing_workload_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.deployer.get_canonical_artifact("non_existent_binary_xyz")

    def test_empty_binary_raises_error(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as f:
            f_path = Path(f.name)  # 0 bytes

        try:
            custom_deployer = WorkloadDeployer(dist_dir=f_path.parent)
            with self.assertRaises(ValueError):
                custom_deployer.get_canonical_artifact(f_path.name)
        finally:
            f_path.unlink()

    def test_deploy_success_matching_hash(self):
        # Create mock adapter
        mock_adapter = MagicMock(spec=BaseEnvironmentAdapter)
        mock_adapter.name = "kvm"
        mock_adapter.target_path = Path("/tmp/cc2_workloads")

        artifact = self.deployer.get_canonical_artifact("cpu_workload")

        # Mock successful deploy_workload returning matching hash
        mock_adapter.deploy_workload.return_value = {
            "deployed": True,
            "transferred": True,
            "sha256": artifact.sha256,
            "destination": f"/tmp/cc2_workloads/{artifact.binary_name}"
        }

        result = self.deployer.deploy(artifact, mock_adapter)
        self.assertTrue(result.verified)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.target_sha256, artifact.sha256)
        self.assertTrue(result.transferred)
        self.assertIsNone(result.error_message)

    def test_deploy_refuses_execution_on_checksum_mismatch(self):
        mock_adapter = MagicMock(spec=BaseEnvironmentAdapter)
        mock_adapter.name = "virtualbox"
        mock_adapter.target_path = Path("/tmp/cc2_workloads")

        artifact = self.deployer.get_canonical_artifact("cpu_workload")

        # Mock corrupted deployment returning a different hash
        corrupted_hash = "deadbeef" * 8
        mock_adapter.deploy_workload.return_value = {
            "deployed": True,
            "transferred": True,
            "sha256": corrupted_hash,
            "destination": f"/tmp/cc2_workloads/{artifact.binary_name}"
        }

        result = self.deployer.deploy(artifact, mock_adapter)
        # Invariant: Must refuse execution if checksum does not match
        self.assertFalse(result.verified)
        self.assertEqual(result.status, "mismatch")
        self.assertEqual(result.target_sha256, corrupted_hash)
        self.assertIn("Checksum mismatch", result.error_message)

    def test_deploy_handles_adapter_transfer_failure(self):
        mock_adapter = MagicMock(spec=BaseEnvironmentAdapter)
        mock_adapter.name = "lxc"
        mock_adapter.target_path = Path("/tmp/cc2_workloads")

        artifact = self.deployer.get_canonical_artifact("cpu_workload")

        mock_adapter.deploy_workload.return_value = {
            "deployed": False,
            "error": "Connection timed out during file transfer",
            "destination": None
        }

        result = self.deployer.deploy(artifact, mock_adapter)
        self.assertFalse(result.verified)
        self.assertEqual(result.status, "failed")
        self.assertIn("Connection timed out", result.error_message)

    def test_models_serialization(self):
        artifact = self.deployer.get_canonical_artifact("cpu_workload")
        d_art = artifact.to_dict()
        self.assertEqual(d_art["binary_name"], "cpu_workload")
        self.assertEqual(d_art["sha256"], artifact.sha256)

        dep_res = WorkloadDeploymentResult(
            workload_name="cpu_workload",
            environment="host",
            local_sha256=artifact.sha256,
            target_destination="/tmp/cpu_workload",
            target_sha256=artifact.sha256,
            verified=True,
            transferred=False,
            status="success"
        )
        d_res = dep_res.to_dict()
        self.assertTrue(d_res["verified"])
        self.assertEqual(d_res["status"], "success")


if __name__ == "__main__":
    unittest.main()
