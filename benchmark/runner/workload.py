#!/usr/bin/env python3
"""
benchmark/runner/workload.py - Common Workload Packaging & Deployment Subsystem.

Responsible for:
1. Identifying canonical workload binaries from workloads/dist/ and workloads/MANIFEST.json.
2. Calculating and validating local SHA256 checksums.
3. Tracking binary size, executable permissions, and metadata.
4. Deploying artifacts across all four environments (Host, KVM, VirtualBox, LXC)
   via environment adapters.
5. Verifying SHA256 post-deployment and strictly refusing to execute if checksums mismatch.
6. Returning structured deployment records without secret leakage.
"""

import os
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List, Union

from .environments.base import BaseEnvironmentAdapter

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DIST_DIR = PROJECT_ROOT / "workloads" / "dist"
MANIFEST_PATH = PROJECT_ROOT / "workloads" / "MANIFEST.json"


@dataclass
class WorkloadArtifact:
    """
    Metadata representation of a canonical workload binary artifact.
    """
    name: str
    binary_name: str
    version: Optional[str]
    local_path: Path
    size_bytes: int
    sha256: str
    is_executable: bool
    description: Optional[str] = None
    parameters_supported: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "binary_name": self.binary_name,
            "version": self.version,
            "local_path": str(self.local_path),
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "is_executable": self.is_executable,
            "description": self.description,
            "parameters_supported": self.parameters_supported
        }


@dataclass
class WorkloadDeploymentResult:
    """
    Structured record of a workload deployment to a target environment.
    """
    workload_name: str
    environment: str
    local_sha256: str
    target_destination: str
    target_sha256: Optional[str]
    verified: bool
    transferred: bool
    status: str  # "success", "mismatch", "failed", "unsupported"
    error_message: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workload_name": self.workload_name,
            "environment": self.environment,
            "local_sha256": self.local_sha256,
            "target_destination": self.target_destination,
            "target_sha256": self.target_sha256,
            "verified": self.verified,
            "transferred": self.transferred,
            "status": self.status,
            "error_message": self.error_message,
            "timestamp": self.timestamp
        }


class WorkloadDeploymentError(Exception):
    """Raised when workload deployment or verification fails."""
    pass


class WorkloadDeployer:
    """
    Manages canonical workload discovery, hash verification, and deployment.
    """

    def __init__(
        self,
        dist_dir: Optional[Path] = None,
        manifest_path: Optional[Path] = None
    ):
        self.dist_dir = dist_dir or DIST_DIR
        self.manifest_path = manifest_path or MANIFEST_PATH
        self._manifest_data = self._load_manifest()

    def _load_manifest(self) -> Dict[str, Any]:
        """Loads MANIFEST.json if available."""
        if self.manifest_path.exists() and self.manifest_path.is_file():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    @staticmethod
    def calculate_sha256(filepath: Path) -> str:
        """Calculates local SHA256 digest of a file in 64KB blocks."""
        if not filepath.exists() or not filepath.is_file():
            raise FileNotFoundError(f"File not found: {filepath}")

        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    def get_canonical_artifact(self, workload_or_binary: str) -> WorkloadArtifact:
        """
        Discovers canonical artifact from workloads/dist/ and validates its SHA256.
        Accepts workload names ('cpu_deterministic', 'cpu_workload') or filenames.
        """
        target_name = workload_or_binary.strip()

        # Check manifest mapping
        manifest_entry = None
        for w in self._manifest_data.get("workloads", []):
            if target_name in (w.get("workload_name"), w.get("binary")):
                manifest_entry = w
                break

        # Resolve filename
        if manifest_entry:
            binary_name = manifest_entry["binary"]
            artifact_name = manifest_entry["workload_name"]
            version = manifest_entry.get("version", "1.0.0")
            description = manifest_entry.get("description")
            params = manifest_entry.get("parameters_supported", [])
        else:
            binary_name = target_name
            artifact_name = target_name
            version = None
            description = None
            params = []

        local_binary_path = self.dist_dir / binary_name
        if not local_binary_path.exists():
            # Fallback: check if in parent workloads directory
            parent_fallback = self.dist_dir.parent / binary_name
            if parent_fallback.exists():
                local_binary_path = parent_fallback
            else:
                raise FileNotFoundError(
                    f"Canonical workload binary '{binary_name}' not found in {self.dist_dir}"
                )

        # File size and permissions
        size_bytes = local_binary_path.stat().st_size
        if size_bytes == 0:
            raise ValueError(f"Workload binary '{binary_name}' is empty (0 bytes)")

        is_executable = os.access(str(local_binary_path), os.X_OK)

        # Calculate actual hash
        actual_sha256 = self.calculate_sha256(local_binary_path)

        # Invariant check against manifest
        if manifest_entry and "sha256" in manifest_entry:
            expected_sha256 = manifest_entry["sha256"]
            if actual_sha256 != expected_sha256:
                raise ValueError(
                    f"Integrity violation for '{binary_name}': actual SHA256 {actual_sha256} "
                    f"does not match manifest SHA256 {expected_sha256}"
                )

        return WorkloadArtifact(
            name=artifact_name,
            binary_name=binary_name,
            version=version,
            local_path=local_binary_path,
            size_bytes=size_bytes,
            sha256=actual_sha256,
            is_executable=is_executable,
            description=description,
            parameters_supported=params
        )

    def deploy(
        self,
        artifact: WorkloadArtifact,
        adapter: BaseEnvironmentAdapter,
        target_dest: Optional[str] = None
    ) -> WorkloadDeploymentResult:
        """
        Deploys canonical artifact to the target environment via its adapter,
        verifies remote SHA256, and strictly refuses execution if checksum differs.
        """
        env_name = adapter.name
        destination = target_dest or f"{adapter.target_path}/{artifact.binary_name}"

        # Delegate deployment to environment adapter
        deploy_info = adapter.deploy_workload(
            local_path=artifact.local_path,
            target_dest=destination
        )

        if not deploy_info.get("deployed"):
            error_msg = deploy_info.get("error", "Adapter failed to deploy binary")
            return WorkloadDeploymentResult(
                workload_name=artifact.name,
                environment=env_name,
                local_sha256=artifact.sha256,
                target_destination=destination,
                target_sha256=None,
                verified=False,
                transferred=False,
                status="failed",
                error_message=error_msg
            )

        # Check post-deployment SHA256
        target_sha256 = deploy_info.get("sha256")
        if not target_sha256:
            # Re-query transport if adapter didn't return sha256
            try:
                target_sha256 = adapter.transport.compute_sha256(destination)
            except Exception as e:
                return WorkloadDeploymentResult(
                    workload_name=artifact.name,
                    environment=env_name,
                    local_sha256=artifact.sha256,
                    target_destination=destination,
                    target_sha256=None,
                    verified=False,
                    transferred=deploy_info.get("transferred", False),
                    status="failed",
                    error_message=f"Failed querying remote SHA256: {e}"
                )

        # Strict Verification Check
        if target_sha256 != artifact.sha256:
            return WorkloadDeploymentResult(
                workload_name=artifact.name,
                environment=env_name,
                local_sha256=artifact.sha256,
                target_destination=destination,
                target_sha256=target_sha256,
                verified=False,
                transferred=deploy_info.get("transferred", False),
                status="mismatch",
                error_message=(
                    f"Checksum mismatch: target SHA256 '{target_sha256}' != "
                    f"expected local SHA256 '{artifact.sha256}'"
                )
            )

        return WorkloadDeploymentResult(
            workload_name=artifact.name,
            environment=env_name,
            local_sha256=artifact.sha256,
            target_destination=destination,
            target_sha256=target_sha256,
            verified=True,
            transferred=deploy_info.get("transferred", False),
            status="success"
        )
