#!/usr/bin/env python3
"""
benchmark/runner/benchmarks.py - Central Benchmark Definitions & Invariant Registry.

Defines declarative benchmark specifications for:
1. cpu_deterministic (compute)
2. memory_deterministic (memory)
3. syscall_deterministic (kernel entry)
4. scheduling_deterministic (context switches)
5. disk_fio (storage regular file I/O)
6. network_ping & network_iperf3 (network latency & bandwidth)
7. startup_lifecycle (cold boot timing)
8. isolation_audit (kernel namespaces & cgroups sharing)

STRICT INVARIANTS:
- CPU Workload MUST ALWAYS execute with:
  --size 400 --iterations 5 --warmup 1 --threads 1
  Expected FLOPs: 640,000,000
  Expected Checksum: 0x7e83d4c61ad5adb8
  Canonical SHA256: 212853035b582f238058b8d436fecf1f25bd5ff249965c7467336903a563fd9f
- Rejects any unknown benchmark name.
- Non-implemented benchmarks are marked NOT_IMPLEMENTED (never fabricate metrics).
"""

import json
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable, Union

ALLOWED_CLI_TESTS = [
    "cpu",
    "memory",
    "disk",
    "network",
    "ping",
    "iperf",
    "app",
    "app_latency",
    "startup",
    "syscall",
    "scheduling",
    "isolation",
    "all"
]


@dataclass
class BenchmarkDefinition:
    """
    Declarative benchmark specification.
    """
    name: str
    domain: str
    short_name: str
    workload_binary: Optional[str]
    default_arguments: List[str]
    timeout_sec: int = 60
    expected_output_type: str = "json"  # "json", "fio_json", "text"
    canonical_invariants: Dict[str, Any] = field(default_factory=dict)
    metric_names: List[str] = field(default_factory=list)
    is_implemented: bool = True
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)

    def format_args(self, custom_params: Optional[Dict[str, Any]] = None) -> List[str]:
        """Returns argument list, optionally overriding with custom parameters."""
        if not custom_params:
            return list(self.default_arguments)

        # For CPU, strictly forbid tampering with canonical parameters
        if self.short_name == "cpu":
            return list(self.default_arguments)

        args = list(self.default_arguments)
        # Custom parameters could be appended if needed in future
        return args

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "domain": self.domain,
            "short_name": self.short_name,
            "workload_binary": self.workload_binary,
            "default_arguments": self.default_arguments,
            "timeout_sec": self.timeout_sec,
            "expected_output_type": self.expected_output_type,
            "canonical_invariants": self.canonical_invariants,
            "metric_names": self.metric_names,
            "is_implemented": self.is_implemented,
            "description": self.description,
            "parameters": self.parameters
        }


# ==============================================================================
# Canonical Benchmark Definitions
# ==============================================================================

CPU_BENCHMARK = BenchmarkDefinition(
    name="cpu_deterministic",
    domain="compute",
    short_name="cpu",
    workload_binary="cpu_workload",
    default_arguments=["--size", "400", "--iterations", "5", "--warmup", "1", "--threads", "1"],
    timeout_sec=60,
    expected_output_type="json",
    canonical_invariants={
        "matrix_size": 400,
        "iterations": 5,
        "warmup": 1,
        "threads": 1,
        "total_flops": 640000000,
        "expected_checksum": "0x7e83d4c61ad5adb8",
        "canonical_sha256": "212853035b582f238058b8d436fecf1f25bd5ff249965c7467336903a563fd9f"
    },
    metric_names=["total_flops", "elapsed_sec", "gflops", "checksum"],
    is_implemented=True,
    description="Deterministic double-precision matrix multiplication with FNV-1a checksum",
    parameters={"size": 400, "iterations": 5, "warmup": 1, "threads": 1}
)

MEMORY_BENCHMARK = BenchmarkDefinition(
    name="memory_deterministic",
    domain="memory",
    short_name="memory",
    workload_binary="memory_workload",
    default_arguments=["--buffer-mb", "128", "--passes", "4", "--stride", "64"],
    timeout_sec=60,
    expected_output_type="json",
    canonical_invariants={
        "buffer_mb": 128,
        "passes": 4,
        "stride": 64
    },
    metric_names=["throughput_mb_s", "elapsed_sec", "passes", "checksum"],
    is_implemented=True,
    description="Deterministic sequential write, read-accumulate, and strided memory benchmark",
    parameters={"buffer_mb": 128, "passes": 4, "stride": 64}
)

SYSCALL_BENCHMARK = BenchmarkDefinition(
    name="syscall_deterministic",
    domain="syscall",
    short_name="syscall",
    workload_binary="syscall_workload",
    default_arguments=["--iterations", "200000", "--warmup", "5000"],
    timeout_sec=60,
    expected_output_type="json",
    canonical_invariants={
        "iterations": 200000,
        "warmup": 5000
    },
    metric_names=["latency_ns", "syscalls_per_sec", "elapsed_sec", "checksum"],
    is_implemented=True,
    description="Deterministic raw getpid() system call latency and throughput benchmark",
    parameters={"iterations": 200000, "warmup": 5000}
)

SCHEDULING_BENCHMARK = BenchmarkDefinition(
    name="scheduling_deterministic",
    domain="scheduling",
    short_name="scheduling",
    workload_binary="scheduling_workload",
    default_arguments=["--iterations", "20000", "--warmup", "1000"],
    timeout_sec=60,
    expected_output_type="json",
    canonical_invariants={
        "iterations": 20000,
        "warmup": 1000,
        "expected_checksum": "0x909e926a36d3fca6"
    },
    metric_names=["context_switch_latency_us", "switches_per_sec", "elapsed_sec", "checksum"],
    is_implemented=True,
    description="Deterministic context switch and process scheduling latency benchmark",
    parameters={"iterations": 20000, "warmup": 1000}
)

DISK_BENCHMARK = BenchmarkDefinition(
    name="disk_fio",
    domain="storage",
    short_name="disk",
    workload_binary=None,  # Uses fio CLI directly
    default_arguments=[],
    timeout_sec=60,
    expected_output_type="fio_json",
    canonical_invariants={
        "file_size_mb": 16,
        "runtime_sec": 3,
        "ioengine": "sync"
    },
    metric_names=["read_iops", "write_iops", "read_throughput_mb_s", "write_throughput_mb_s", "p95_lat_ms"],
    is_implemented=True,
    description="Safe regular file FIO storage benchmark (strictly rejects block devices)",
    parameters={"file_size_mb": 16, "runtime_sec": 3}
)

NETWORK_PING_BENCHMARK = BenchmarkDefinition(
    name="network_ping",
    domain="network_latency",
    short_name="network",
    workload_binary=None,
    default_arguments=["-c", "5", "-W", "1"],
    timeout_sec=15,
    expected_output_type="ping_text",
    canonical_invariants={"count": 5},
    metric_names=["rtt_min_ms", "rtt_avg_ms", "rtt_max_ms", "rtt_mdev_ms", "packet_loss_pct"],
    is_implemented=True,
    description="ICMP echo request latency measurement against controlled local gateway",
    parameters={"count": 5}
)

NETWORK_IPERF3_BENCHMARK = BenchmarkDefinition(
    name="network_iperf3",
    domain="network_bandwidth",
    short_name="iperf",
    workload_binary=None,
    default_arguments=["-t", "5", "-P", "1", "-J"],
    timeout_sec=30,
    expected_output_type="iperf3_json",
    canonical_invariants={"duration_sec": 5, "streams": 1, "protocol": "TCP"},
    metric_names=["sender_bandwidth_mbps", "receiver_bandwidth_mbps", "retransmits"],
    is_implemented=True,
    description="Standardized TCP throughput evaluation via local iperf3 endpoint",
    parameters={"duration_sec": 5, "streams": 1}
)

APP_LATENCY_BENCHMARK = BenchmarkDefinition(
    name="app_latency",
    domain="application_latency",
    short_name="app",
    workload_binary="http_health_app.py",
    default_arguments=["--host", "0.0.0.0", "--port", "8080"],
    timeout_sec=60,
    expected_output_type="json",
    canonical_invariants={"requests": 100, "endpoint": "/health"},
    metric_names=["connect_ms", "ttfb_ms", "total_ms", "requests_completed", "http_200_count", "p50_ms", "p95_ms", "p99_ms"],
    is_implemented=True,
    description="100 HTTP GET /health requests measuring connect, TTFB, and total response latency percentiles",
    parameters={"requests": 100, "endpoint": "/health"}
)

STARTUP_BENCHMARK = BenchmarkDefinition(
    name="startup_lifecycle",
    domain="virtualization",
    short_name="startup",
    workload_binary=None,
    default_arguments=[],
    timeout_sec=120,
    expected_output_type="lifecycle_dict",
    canonical_invariants={},
    metric_names=["hypervisor_start_sec", "os_ready_sec", "network_ready_sec", "app_ready_sec", "total_boot_sec"],
    is_implemented=True,
    description="Cold boot and guest readiness multi-phase timing probe",
    parameters={}
)

ISOLATION_BENCHMARK = BenchmarkDefinition(
    name="isolation_audit",
    domain="isolation",
    short_name="isolation",
    workload_binary=None,
    default_arguments=[],
    timeout_sec=15,
    expected_output_type="isolation_dict",
    canonical_invariants={},
    metric_names=["is_shared_kernel", "systemd_detect_virt", "kernel_release", "namespaces_isolated"],
    is_implemented=True,
    description="Kernel namespaces, cgroups, and direct kernel sharing audit",
    parameters={}
)


# ==============================================================================
# Central Benchmark Registry
# ==============================================================================

BENCHMARK_REGISTRY: Dict[str, BenchmarkDefinition] = {
    "cpu_deterministic": CPU_BENCHMARK,
    "cpu": CPU_BENCHMARK,

    "memory_deterministic": MEMORY_BENCHMARK,
    "memory": MEMORY_BENCHMARK,

    "syscall_deterministic": SYSCALL_BENCHMARK,
    "syscall": SYSCALL_BENCHMARK,

    "scheduling_deterministic": SCHEDULING_BENCHMARK,
    "scheduling": SCHEDULING_BENCHMARK,

    "disk_fio": DISK_BENCHMARK,
    "disk": DISK_BENCHMARK,

    "network_ping": NETWORK_PING_BENCHMARK,
    "network": NETWORK_PING_BENCHMARK,
    "ping": NETWORK_PING_BENCHMARK,

    "network_iperf3": NETWORK_IPERF3_BENCHMARK,
    "iperf": NETWORK_IPERF3_BENCHMARK,
    "iperf3": NETWORK_IPERF3_BENCHMARK,

    "app_latency": APP_LATENCY_BENCHMARK,
    "app": APP_LATENCY_BENCHMARK,

    "startup_lifecycle": STARTUP_BENCHMARK,
    "startup": STARTUP_BENCHMARK,

    "isolation_audit": ISOLATION_BENCHMARK,
    "isolation": ISOLATION_BENCHMARK,
}


def get_benchmark(name: str) -> BenchmarkDefinition:
    """
    Retrieves a benchmark definition by canonical name or short alias.
    Raises ValueError if benchmark name is unknown.
    """
    clean_name = name.strip().lower()
    if clean_name not in BENCHMARK_REGISTRY:
        raise ValueError(
            f"Unknown benchmark '{name}'. Allowed choices: {ALLOWED_CLI_TESTS}"
        )
    return BENCHMARK_REGISTRY[clean_name]


def resolve_benchmarks(names: Optional[List[str]]) -> List[BenchmarkDefinition]:
    """
    Resolves a list of CLI test options to unique canonical BenchmarkDefinitions.
    If 'all' or None is specified, returns all canonical benchmarks.
    """
    if not names or "all" in [n.lower() for n in names]:
        # Return all unique benchmark definitions in deterministic canonical order
        canonical_keys = [
            "cpu_deterministic",
            "memory_deterministic",
            "syscall_deterministic",
            "scheduling_deterministic",
            "disk_fio",
            "network_ping",
            "network_iperf3",
            "app_latency",
            "startup_lifecycle",
            "isolation_audit"
        ]
        return [BENCHMARK_REGISTRY[k] for k in canonical_keys]

    resolved: List[BenchmarkDefinition] = []
    seen = set()
    for name in names:
        defn = get_benchmark(name)
        if defn.name not in seen:
            resolved.append(defn)
            seen.add(defn.name)

    return resolved
