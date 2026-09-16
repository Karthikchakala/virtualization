#!/usr/bin/env python3
"""
build_package.py - Generates workloads/MANIFEST.json with reproducible SHA256 checksums,
compiler metadata, and package manifest for CC2 common workloads.
"""

import os
import sys
import json
import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

WORKLOADS_DIR = Path(__file__).resolve().parent
DIST_DIR = WORKLOADS_DIR / "dist"
MANIFEST_FILE = WORKLOADS_DIR / "MANIFEST.json"

def get_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def get_compiler_info() -> dict:
    try:
        res = subprocess.run(["gcc", "--version"], capture_output=True, text=True, check=True)
        first_line = res.stdout.splitlines()[0] if res.stdout else "gcc unknown"
        return {
            "compiler": "gcc",
            "compiler_version": first_line.strip(),
            "flags": "-O2 -Wall -Wextra -pthread -std=c99 -fno-omit-frame-pointer -static",
            "linking": "static (portable across Linux kernels without glibc dynamic dependency)"
        }
    except Exception as e:
        return {
            "compiler": "gcc",
            "compiler_version": str(e),
            "flags": "-O2",
            "linking": "unknown"
        }

def build_manifest():
    compiler_info = get_compiler_info()
    timestamp = datetime.now(timezone.utc).isoformat()

    binaries = [
        {
            "workload_name": "cpu_deterministic",
            "version": "1.0.0",
            "binary": "cpu_workload",
            "relative_path": "dist/cpu_workload",
            "description": "Deterministic double-precision matrix multiplication with FNV-1a checksum",
            "parameters_supported": ["--size", "--iterations", "--warmup", "--threads"]
        },
        {
            "workload_name": "memory_deterministic",
            "version": "1.0.0",
            "binary": "memory_workload",
            "relative_path": "dist/memory_workload",
            "description": "Deterministic sequential write, read-accumulate, and stride memory benchmark",
            "parameters_supported": ["--buffer-mb", "--passes", "--stride"]
        },
        {
            "workload_name": "workload_runner_script",
            "version": "1.0.0",
            "binary": "run_workload.sh",
            "relative_path": "dist/run_workload.sh",
            "description": "Standardized POSIX wrapper script for guest workload invocation",
            "parameters_supported": ["cpu", "memory"]
        },
        {
            "workload_name": "syscall_deterministic",
            "version": "1.0.0",
            "binary": "syscall_workload",
            "relative_path": "dist/syscall_workload",
            "description": "Deterministic raw system call latency and throughput benchmark",
            "parameters_supported": ["--iterations", "--warmup"]
        },
        {
            "workload_name": "scheduling_deterministic",
            "version": "1.0.0",
            "binary": "scheduling_workload",
            "relative_path": "dist/scheduling_workload",
            "description": "Deterministic context switch and process scheduling latency benchmark",
            "parameters_supported": ["--iterations", "--warmup"]
        },
        {
            "workload_name": "http_health_app",
            "version": "1.0.0",
            "binary": "http_health_app.py",
            "relative_path": "dist/http_health_app.py",
            "description": "Minimal identical HTTP application serving GET /health for latency benchmarking",
            "parameters_supported": ["--host", "--port"]
        }
    ]

    for item in binaries:
        bin_path = DIST_DIR / item["binary"]
        if bin_path.exists():
            item["sha256"] = get_sha256(bin_path)
            item["file_size_bytes"] = bin_path.stat().st_size
            item["status"] = "built"
        else:
            item["sha256"] = None
            item["file_size_bytes"] = None
            item["status"] = "missing"

    manifest = {
        "package_name": "cc2-common-workloads",
        "package_version": "1.0.0",
        "build_timestamp": timestamp,
        "compiler": compiler_info["compiler"],
        "compiler_version": compiler_info["compiler_version"],
        "compiler_flags": compiler_info["flags"],
        "linking_mode": compiler_info["linking"],
        "host_architecture": os.uname().machine if hasattr(os, "uname") else "x86_64",
        "workloads": binaries
    }

    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"[OK] MANIFEST.json generated at {MANIFEST_FILE}")
    for b in binaries:
        print(f"  -> {b['binary']}: SHA256={b['sha256'][:16]}... ({b['file_size_bytes']} bytes)")

if __name__ == "__main__":
    build_manifest()
