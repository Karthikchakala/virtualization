"""
benchmark/runner package initialization.

Maintains complete backward compatibility with existing code importing from
benchmark.runner (e.g. ExperimentRunner, IsolationManager, build_arg_parser)
while exposing the new configuration subsystem.
"""

import sys
import importlib.util
from pathlib import Path

# 1. Dynamically import legacy runner symbols from benchmark/runner.py if present
_legacy_runner_file = Path(__file__).resolve().parent.parent / "runner.py"
if _legacy_runner_file.exists():
    _spec = importlib.util.spec_from_file_location("benchmark._legacy_runner", str(_legacy_runner_file))
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        ExperimentRunner = getattr(_mod, "ExperimentRunner", None)
        IsolationManager = getattr(_mod, "IsolationManager", None)
        build_arg_parser = getattr(_mod, "build_arg_parser", None)


# 2. Lazy attribute loader to prevent runpy warnings when executing submodules via -m
def __getattr__(name: str):
    if name in (
        "AppConfig",
        "ConfigLoader",
        "EnvironmentConfig",
        "BenchmarkConfig",
        "GlobalSettings",
        "get_config",
        "mask_secret",
        "ConfigurationError"
    ):
        from . import config
        return getattr(config, name)
    if name in (
        "create_adapter",
        "BaseEnvironmentAdapter",
        "HostAdapter",
        "KvmAdapter",
        "VirtualBoxAdapter",
        "LxcAdapter"
    ):
        from . import environments
        return getattr(environments, name)
    if name in (
        "WorkloadDeployer",
        "WorkloadArtifact",
        "WorkloadDeploymentResult"
    ):
        from . import workload
        return getattr(workload, name)
    if name in (
        "BenchmarkExecutor",
        "ExecutionPlan"
    ):
        from . import executor
        return getattr(executor, name)
    if name in (
        "BenchmarkDefinition",
        "get_benchmark",
        "resolve_benchmarks",
        "CPU_BENCHMARK"
    ):
        from . import benchmarks
        return getattr(benchmarks, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "AppConfig",
    "ConfigLoader",
    "EnvironmentConfig",
    "BenchmarkConfig",
    "GlobalSettings",
    "get_config",
    "mask_secret",
    "ConfigurationError",
    "ExperimentRunner",
    "IsolationManager",
    "build_arg_parser",
    "create_adapter",
    "BaseEnvironmentAdapter",
    "HostAdapter",
    "KvmAdapter",
    "VirtualBoxAdapter",
    "LxcAdapter",
    "WorkloadDeployer",
    "WorkloadArtifact",
    "WorkloadDeploymentResult",
    "BenchmarkExecutor",
    "ExecutionPlan",
    "BenchmarkDefinition",
    "get_benchmark",
    "resolve_benchmarks",
    "CPU_BENCHMARK"
]
