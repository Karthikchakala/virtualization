#!/usr/bin/env python3
"""
benchmark/runner/environments/__init__.py - Unified Environment Adapters Subsystem.

Provides standardized adapter abstractions and factory initialization for:
1. Host: Bare-metal reference baseline (LocalTransport).
2. KVM: Hardware-assisted virtualization (virsh + SSHTransport).
3. VirtualBox: Hosted hypervisor (VBoxManage + SSHTransport).
4. Native LXC: OS-level containers (LxcAttachTransport).

Also exposes a non-destructive diagnostic CLI runner:
  python3 -m benchmark.runner.environments --check
"""

import sys
import argparse
from typing import Dict, Any, Optional, Union, List

from .base import (
    BaseEnvironmentAdapter,
    NormalizedState,
    ExecutionResult,
    IdentityResult
)
from .transport import (
    BaseTransport,
    LocalTransport,
    SSHTransport,
    LxcAttachTransport
)
from .host import HostAdapter
from .kvm import KvmAdapter
from .virtualbox import VirtualBoxAdapter
from .lxc import LxcAdapter

from ..config import AppConfig, EnvironmentConfig, ConfigLoader

__all__ = [
    "BaseEnvironmentAdapter",
    "NormalizedState",
    "ExecutionResult",
    "IdentityResult",
    "BaseTransport",
    "LocalTransport",
    "SSHTransport",
    "LxcAttachTransport",
    "HostAdapter",
    "KvmAdapter",
    "VirtualBoxAdapter",
    "LxcAdapter",
    "create_adapter",
    "list_registered_adapters"
]

ADAPTER_REGISTRY = {
    "host": HostAdapter,
    "kvm": KvmAdapter,
    "virtualbox": VirtualBoxAdapter,
    "lxc": LxcAdapter
}


def list_registered_adapters() -> List[str]:
    """Returns list of registered adapter environment names."""
    return list(ADAPTER_REGISTRY.keys())


def create_adapter(
    name_or_config: Union[str, EnvironmentConfig],
    app_config: Optional[AppConfig] = None
) -> BaseEnvironmentAdapter:
    """
    Factory creating concrete BaseEnvironmentAdapter instances.
    Accepts either an environment name string ("host", "kvm", "virtualbox", "lxc")
    or an instantiated EnvironmentConfig dataclass.
    """
    if isinstance(name_or_config, EnvironmentConfig):
        env_config = name_or_config
        env_name = env_config.name.lower()
    elif isinstance(name_or_config, str):
        env_name = name_or_config.lower()
        if app_config:
            env_config = app_config.get_env(env_name)
        else:
            try:
                loaded_app = ConfigLoader().load_config()
                env_config = loaded_app.get_env(env_name)
            except Exception:
                env_config = None
    else:
        raise TypeError(f"Expected str or EnvironmentConfig, got {type(name_or_config)}")

    if env_name not in ADAPTER_REGISTRY:
        raise ValueError(
            f"Unknown environment '{env_name}'. Available environments: {list(ADAPTER_REGISTRY.keys())}"
        )

    adapter_cls = ADAPTER_REGISTRY[env_name]
    return adapter_cls(env_config)


def run_diagnostics() -> int:
    """
    Non-destructive diagnostic runner (--check).
    Inspects all registered adapters without running any benchmark workloads.
    """
    print("=" * 78)
    print("CC2 UNIFIED ENVIRONMENT ADAPTER DIAGNOSTIC PROBE (--check)")
    print("=" * 78)

    try:
        app_cfg = ConfigLoader().load_config()
        print(f"Loaded configuration from: {app_cfg.env_file_path or 'defaults'}")
    except Exception as e:
        print(f"Warning: Could not load full AppConfig: {e}. Using fallback defaults.")
        app_cfg = None

    print("-" * 78)
    print(f"{'Environment':<12} | {'State':<12} | {'Verified':<10} | {'Transport':<12} | {'IP / Endpoint'}")
    print("-" * 78)

    results = []
    for env_name in ["host", "kvm", "virtualbox", "lxc"]:
        try:
            adapter = create_adapter(env_name, app_config=app_cfg)
            status = adapter.get_status()
            verified = adapter.verify()
            ident = adapter.get_identity()

            endpoint = ident.ip_address or "-"
            if env_name == "virtualbox":
                endpoint = f"{ident.ip_address or '127.0.0.1'}:{adapter.config.ssh_port}"

            print(f"{adapter.name:<12} | {status:<12} | {str(verified):<10} | {adapter.transport_name:<12} | {endpoint}")
            results.append((adapter, status, verified, ident))
        except Exception as e:
            print(f"{env_name:<12} | {'error':<12} | {'False':<10} | {'unknown':<12} | Error: {e}")

    print("=" * 78)
    print("ENVIRONMENT SPECIFICATION DETAILS:")
    for adapter, status, verified, ident in results:
        print(f"\n[{adapter.display_name}]")
        print(f"  Classification  : {adapter.classification}")
        print(f"  Virtualization  : {adapter.virtualization_type}")
        print(f"  Current Status  : {status}")
        print(f"  Kernel Release  : {ident.kernel_release or 'unknown (offline)'}")
        print(f"  vCPUs / RAM     : {ident.vcpus} vCPUs / {ident.memory_mb} MB")
        print(f"  Virt Detect     : {ident.systemd_detect_virt or 'none'}")
        print(f"  Shared Kernel   : {ident.is_shared_kernel}")
        if ident.raw_details:
            for k, v in ident.raw_details.items():
                print(f"  {k:<16}: {v}")

    print("\n" + "=" * 78)
    print("DIAGNOSTIC COMPLETED: Strictly non-destructive. Zero benchmarks executed.")
    print("=" * 78)
    return 0


def main():
    parser = argparse.ArgumentParser(description="CC2 Unified Environment Adapters Subsystem")
    parser.add_argument("--check", action="store_true", help="Run non-destructive adapter diagnostics")
    args = parser.parse_args()

    if args.check:
        sys.exit(run_diagnostics())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
