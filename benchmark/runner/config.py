#!/usr/bin/env python3
"""
benchmark/runner/config.py - Credential & Configuration Subsystem for CC2.

Features:
1. Safe .env loading (via python-dotenv if available, or robust zero-dependency parser).
2. PyYAML parsing of config/environments.yaml and config/benchmark.yaml.
3. Secure merging of environment variables over non-secret YAML defaults.
4. Deterministic authentication precedence (SSH key preferred over password).
5. Strict secret masking (passwords and sensitive tokens are masked as '********').
6. repr() / __str__() guarantees zero secret leakage.
7. Configuration validation separated from live connectivity validation.
8. CLI diagnostic runner (--check) invoking non-destructive connectivity probes.
"""

import os
import re
import sys
import yaml
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
ENV_FILE_DEFAULT = PROJECT_ROOT / ".env"
ENV_EXAMPLE_DEFAULT = PROJECT_ROOT / ".env.example"

VALID_ENVIRONMENTS = {"host", "kvm", "virtualbox", "lxc"}
VALID_AUTH_METHODS = {"key", "password", "local", "none"}


# ==============================================================================
# Secret Masking Utilities
# ==============================================================================

def mask_secret(value: Optional[str]) -> str:
    """
    Returns a masked string for secrets.
    Never reveals any characters of the secret value.
    """
    if value is None or value == "":
        return "(not configured)"
    return "********"


def sanitize_dict(data: Any) -> Any:
    """
    Recursively scans and sanitizes dictionary values whose keys imply secrets.
    """
    secret_key_patterns = [
        r"pass(word)?",
        r"secret",
        r"token",
        r"private_key",
        r"api_key",
        r"credential"
    ]
    regex = re.compile("|".join(secret_key_patterns), re.IGNORECASE)

    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if regex.search(str(k)):
                sanitized[k] = mask_secret(str(v)) if v else "(not configured)"
            elif isinstance(v, (dict, list)):
                sanitized[k] = sanitize_dict(v)
            else:
                sanitized[k] = v
        return sanitized
    elif isinstance(data, list):
        return [sanitize_dict(item) for item in data]
    return data


# ==============================================================================
# Safe .env Parser (Zero-dependency fallback with python-dotenv support)
# ==============================================================================

def load_env_file(filepath: Path) -> Dict[str, str]:
    """
    Safely parses a local .env file.
    Uses python-dotenv if installed, otherwise uses a robust built-in parser.
    Populates os.environ without overwriting existing environment variables
    unless explicitly intended.
    """
    loaded_vars: Dict[str, str] = {}
    if not filepath.exists() or not filepath.is_file():
        return loaded_vars

    # Try python-dotenv first if available
    try:
        import dotenv
        # Read without automatically overriding existing os.environ
        parsed = dotenv.dotenv_values(str(filepath))
        for k, v in parsed.items():
            if k and v is not None:
                loaded_vars[k] = v
                if k not in os.environ:
                    os.environ[k] = v
        return loaded_vars
    except ImportError:
        pass

    # Built-in fallback parser (handles quotes, exports, and comments)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str or line_str.startswith("#"):
                    continue
                if line_str.startswith("export "):
                    line_str = line_str[7:].strip()
                if "=" not in line_str:
                    continue

                key, _, raw_val = line_str.partition("=")
                key = key.strip()
                val = raw_val.strip()

                # Handle quotes
                if len(val) >= 2:
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]

                # Strip inline comments for unquoted values
                if "#" in val and not (raw_val.startswith('"') or raw_val.startswith("'")):
                    val = val.split("#", 1)[0].strip()

                if key:
                    loaded_vars[key] = val
                    if key not in os.environ:
                        os.environ[key] = val
    except Exception as e:
        # Never include line contents in exception message
        raise RuntimeError(f"Error parsing .env file at {filepath.name}: {e}")

    return loaded_vars


# ==============================================================================
# Configuration Data Models
# ==============================================================================

@dataclass
class EnvironmentConfig:
    name: str
    display_name: str
    classification: str
    virtualization_type: str
    transport: str
    target_path: str = "/tmp/cc2_workloads"
    vm_name: Optional[str] = None
    container_name: Optional[str] = None
    ssh_host: Optional[str] = None
    ssh_port: int = 22
    ssh_user: Optional[str] = None
    ssh_password: Optional[str] = field(default=None, repr=False)
    ssh_key_path: Optional[str] = None
    specs: Dict[str, Any] = field(default_factory=dict)
    management_cmd: str = "none"
    readiness_timeout_sec: int = 60
    shutdown_timeout_sec: int = 30

    @property
    def auth_method(self) -> str:
        """
        Determines the effective authentication mechanism.
        Precedence:
        1. Local transport (e.g. Host, LXC attach) -> 'local'
        2. SSH key if key_path configured -> 'key'
        3. SSH password if password configured -> 'password'
        4. None -> 'none' (will rely on default SSH agent / known keys)
        """
        if self.transport in ("local", "lxc-attach"):
            return "local"
        if self.ssh_key_path and self.ssh_key_path.strip():
            return "key"
        if self.ssh_password and self.ssh_password.strip():
            return "password"
        return "none"

    def __repr__(self) -> str:
        """Guarantees zero secret leakage in object string representation."""
        return (
            f"EnvironmentConfig(name='{self.name}', display_name='{self.display_name}', "
            f"transport='{self.transport}', auth_method='{self.auth_method}', "
            f"ssh_host='{self.ssh_host}', ssh_port={self.ssh_port}, ssh_user='{self.ssh_user}', "
            f"ssh_password='{mask_secret(self.ssh_password)}', ssh_key_path='{self.ssh_key_path}')"
        )

    def to_sanitized_dict(self) -> Dict[str, Any]:
        """Returns a copy of the configuration with passwords masked."""
        d = asdict(self)
        d["ssh_password"] = mask_secret(self.ssh_password)
        d["auth_method"] = self.auth_method
        return d


@dataclass
class BenchmarkConfig:
    name: str
    domain: str
    workload_name: str
    description: str
    enabled: bool = True
    command_template: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    canonical_invariants: Dict[str, Any] = field(default_factory=dict)
    warmup_runs: int = 1
    measured_runs: int = 5
    timeout_sec: int = 60
    stabilization_sec: int = 2

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GlobalSettings:
    stabilization_sec: int = 2
    timeout_sec: int = 120
    ssh_connect_timeout_sec: int = 5
    storage_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "results")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stabilization_sec": self.stabilization_sec,
            "timeout_sec": self.timeout_sec,
            "ssh_connect_timeout_sec": self.ssh_connect_timeout_sec,
            "storage_dir": str(self.storage_dir)
        }


@dataclass
class AppConfig:
    environments: Dict[str, EnvironmentConfig]
    benchmarks: Dict[str, BenchmarkConfig]
    settings: GlobalSettings
    env_file_loaded: bool = False
    env_file_path: Optional[Path] = None

    def get_env(self, name: str) -> EnvironmentConfig:
        if name not in self.environments:
            raise KeyError(f"Environment '{name}' not defined. Valid choices: {list(self.environments.keys())}")
        return self.environments[name]

    def get_benchmark(self, name: str) -> BenchmarkConfig:
        if name not in self.benchmarks:
            raise KeyError(f"Benchmark '{name}' not defined. Valid choices: {list(self.benchmarks.keys())}")
        return self.benchmarks[name]

    def list_environments(self) -> List[str]:
        return sorted(list(self.environments.keys()))

    def list_benchmarks(self) -> List[str]:
        return sorted(list(self.benchmarks.keys()))

    def __repr__(self) -> str:
        return (
            f"AppConfig(environments={list(self.environments.keys())}, "
            f"benchmarks={list(self.benchmarks.keys())}, env_loaded={self.env_file_loaded})"
        )

    def to_sanitized_dict(self) -> Dict[str, Any]:
        return {
            "env_file_loaded": self.env_file_loaded,
            "env_file_path": str(self.env_file_path) if self.env_file_path else None,
            "settings": self.settings.to_dict(),
            "environments": {k: v.to_sanitized_dict() for k, v in self.environments.items()},
            "benchmarks": {k: v.to_dict() for k, v in self.benchmarks.items()}
        }


# ==============================================================================
# Configuration Loader
# ==============================================================================

class ConfigurationError(Exception):
    """Raised when configuration values are missing, invalid, or malformed."""
    pass


class ConfigLoader:
    """
    Central configuration loader for CC2.
    Coordinates .env, environments.yaml, and benchmark.yaml into an AppConfig instance.
    """

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        env_file: Optional[Path] = None
    ):
        self.config_dir = config_dir or CONFIG_DIR
        self.env_file = env_file or ENV_FILE_DEFAULT
        self.env_example_file = ENV_EXAMPLE_DEFAULT

    def load_config(self) -> AppConfig:
        """Loads, merges, and validates configuration."""
        # 1. Load local .env if present
        env_loaded = False
        if self.env_file.exists():
            load_env_file(self.env_file)
            env_loaded = True

        # 2. Load environments.yaml
        env_yaml_path = self.config_dir / "environments.yaml"
        if not env_yaml_path.exists():
            raise ConfigurationError(f"Required configuration file missing: {env_yaml_path}")

        try:
            with open(env_yaml_path, "r", encoding="utf-8") as f:
                env_raw = yaml.safe_load(f) or {}
        except Exception as e:
            raise ConfigurationError(f"Failed to parse YAML file {env_yaml_path.name}: {e}")

        # 3. Load benchmark.yaml
        bench_yaml_path = self.config_dir / "benchmark.yaml"
        if not bench_yaml_path.exists():
            raise ConfigurationError(f"Required configuration file missing: {bench_yaml_path}")

        try:
            with open(bench_yaml_path, "r", encoding="utf-8") as f:
                bench_raw = yaml.safe_load(f) or {}
        except Exception as e:
            raise ConfigurationError(f"Failed to parse YAML file {bench_yaml_path.name}: {e}")

        # 4. Parse global settings
        settings = self._parse_global_settings()

        # 5. Build EnvironmentConfig objects
        environments = self._build_environments(env_raw.get("environments", {}))

        # 6. Build BenchmarkConfig objects
        benchmarks = self._build_benchmarks(bench_raw.get("benchmarks", {}))

        # 7. Validate configuration invariants
        self._validate_config(environments, benchmarks, settings)

        return AppConfig(
            environments=environments,
            benchmarks=benchmarks,
            settings=settings,
            env_file_loaded=env_loaded,
            env_file_path=self.env_file if env_loaded else None
        )

    def _parse_global_settings(self) -> GlobalSettings:
        def get_int_env(key: str, default: int) -> int:
            val = os.environ.get(key)
            if val is not None and val.strip():
                try:
                    return int(val.strip())
                except ValueError:
                    raise ConfigurationError(f"Invalid integer for environment variable '{key}': '{val}'")
            return default

        return GlobalSettings(
            stabilization_sec=get_int_env("BENCHMARK_STABILIZATION_SEC", 2),
            timeout_sec=get_int_env("BENCHMARK_TIMEOUT_SEC", 120),
            ssh_connect_timeout_sec=get_int_env("BENCHMARK_SSH_CONNECT_TIMEOUT_SEC", 5)
        )

    def _build_environments(self, raw_envs: Dict[str, Any]) -> Dict[str, EnvironmentConfig]:
        env_map: Dict[str, EnvironmentConfig] = {}

        for env_id, data in raw_envs.items():
            name = data.get("name", env_id)
            disp_name = data.get("display_name", name.upper())
            classification = data.get("classification", "")
            virt_type = data.get("virtualization_type", "none")
            transport = data.get("transport", "local")
            target_path = data.get("target_path", "/tmp/cc2_workloads")
            mgmt_cmd = data.get("management", {}).get("command", "none")
            timeouts = data.get("timeouts", {})
            specs = data.get("specs", {})

            # Environment-specific overrides from environment variables
            vm_name = data.get("vm_name")
            container_name = data.get("container_name")
            ssh_host = data.get("default_ssh_host")
            ssh_port = data.get("default_ssh_port", 22)
            ssh_user = None
            ssh_password = None
            ssh_key_path = None

            if name == "kvm":
                vm_name = os.environ.get("KVM_VM_NAME") or vm_name or "ubuntu24.04"
                ssh_host = os.environ.get("KVM_SSH_HOST") or ssh_host
                ssh_user = os.environ.get("KVM_SSH_USER")
                ssh_password = os.environ.get("KVM_SSH_PASSWORD")
                ssh_key_path = os.environ.get("KVM_SSH_KEY_PATH")
                port_str = os.environ.get("KVM_SSH_PORT")
                if port_str and port_str.strip():
                    try:
                        ssh_port = int(port_str.strip())
                    except ValueError:
                        raise ConfigurationError(f"Invalid KVM_SSH_PORT '{port_str}'. Must be integer.")

            elif name == "virtualbox":
                vm_name = os.environ.get("VBOX_VM_NAME") or vm_name or "Ubuntu-Server-VBox"
                ssh_host = os.environ.get("VBOX_SSH_HOST") or ssh_host or "127.0.0.1"
                ssh_user = os.environ.get("VBOX_SSH_USER")
                ssh_password = os.environ.get("VBOX_SSH_PASSWORD")
                ssh_key_path = os.environ.get("VBOX_SSH_KEY_PATH")
                port_str = os.environ.get("VBOX_SSH_PORT")
                if port_str and port_str.strip():
                    try:
                        ssh_port = int(port_str.strip())
                    except ValueError:
                        raise ConfigurationError(f"Invalid VBOX_SSH_PORT '{port_str}'. Must be integer.")

            elif name == "lxc":
                container_name = os.environ.get("LXC_CONTAINER_NAME") or container_name or "lxc-ubuntu"

            env_map[name] = EnvironmentConfig(
                name=name,
                display_name=disp_name,
                classification=classification,
                virtualization_type=virt_type,
                transport=transport,
                target_path=target_path,
                vm_name=vm_name,
                container_name=container_name,
                ssh_host=ssh_host,
                ssh_port=ssh_port,
                ssh_user=ssh_user,
                ssh_password=ssh_password,
                ssh_key_path=ssh_key_path,
                specs=specs,
                management_cmd=mgmt_cmd,
                readiness_timeout_sec=int(timeouts.get("readiness_sec", 60)),
                shutdown_timeout_sec=int(timeouts.get("shutdown_sec", 30))
            )

        return env_map

    def _build_benchmarks(self, raw_benchmarks: Dict[str, Any]) -> Dict[str, BenchmarkConfig]:
        bench_map: Dict[str, BenchmarkConfig] = {}

        for b_name, b_data in raw_benchmarks.items():
            runs_data = b_data.get("runs", {})
            warmup = int(runs_data.get("warmup", 1))
            measured = int(runs_data.get("measured", 5))

            bench_map[b_name] = BenchmarkConfig(
                name=b_name,
                domain=b_data.get("domain", "compute"),
                workload_name=b_data.get("workload_name", b_name),
                description=b_data.get("description", ""),
                enabled=bool(b_data.get("enabled", True)),
                command_template=b_data.get("command_template"),
                parameters=b_data.get("parameters", {}),
                canonical_invariants=b_data.get("canonical_invariants", {}),
                warmup_runs=warmup,
                measured_runs=measured,
                timeout_sec=int(b_data.get("timeout_sec", 60)),
                stabilization_sec=int(b_data.get("stabilization_sec", 2))
            )

        return bench_map

    def _validate_config(
        self,
        envs: Dict[str, EnvironmentConfig],
        benchmarks: Dict[str, BenchmarkConfig],
        settings: GlobalSettings
    ) -> None:
        """Validates configuration sanity without requiring live targets to be online."""
        # 1. Environment validations
        for name, ec in envs.items():
            if name not in VALID_ENVIRONMENTS:
                raise ConfigurationError(f"Invalid environment name '{name}'. Must be one of {VALID_ENVIRONMENTS}")

            if name == "kvm" and not ec.vm_name:
                raise ConfigurationError("KVM environment missing required 'vm_name'.")
            if name == "virtualbox" and not ec.vm_name:
                raise ConfigurationError("VirtualBox environment missing required 'vm_name'.")
            if name == "lxc" and not ec.container_name:
                raise ConfigurationError("LXC environment missing required 'container_name'.")

            if ec.transport == "ssh":
                if not (1 <= ec.ssh_port <= 65535):
                    raise ConfigurationError(f"Invalid SSH port {ec.ssh_port} for environment '{name}'. Must be 1..65535.")

            if ec.readiness_timeout_sec <= 0:
                raise ConfigurationError(f"Invalid readiness timeout {ec.readiness_timeout_sec} for '{name}'. Must be > 0.")
            if ec.shutdown_timeout_sec < 0:
                raise ConfigurationError(f"Invalid shutdown timeout {ec.shutdown_timeout_sec} for '{name}'. Must be >= 0.")

        # 2. Benchmark validations
        for b_name, bc in benchmarks.items():
            if bc.measured_runs <= 0:
                raise ConfigurationError(f"Benchmark '{b_name}' has invalid measured_runs={bc.measured_runs}. Must be >= 1.")
            if bc.timeout_sec <= 0:
                raise ConfigurationError(f"Benchmark '{b_name}' has invalid timeout_sec={bc.timeout_sec}. Must be > 0.")

        # 3. Canonical CPU verification
        if "cpu_deterministic" in benchmarks:
            cpu_cfg = benchmarks["cpu_deterministic"]
            p = cpu_cfg.parameters
            if p.get("size") != 400 or p.get("iterations") != 5 or p.get("warmup") != 1 or p.get("threads") != 1:
                raise ConfigurationError(
                    f"Canonical CPU parameters corrupted! Expected size=400, iterations=5, warmup=1, threads=1. Found: {p}"
                )
            invar = cpu_cfg.canonical_invariants
            if invar.get("total_flops") != 640000000 or invar.get("expected_checksum") != "0x7e83d4c61ad5adb8":
                raise ConfigurationError(
                    f"Canonical CPU invariants corrupted! Expected 640000000 FLOPs, 0x7e83d4c61ad5adb8 checksum. Found: {invar}"
                )

        # 4. Global settings validations
        if settings.stabilization_sec < 0:
            raise ConfigurationError(f"Invalid stabilization_sec={settings.stabilization_sec}. Must be >= 0.")
        if settings.timeout_sec <= 0:
            raise ConfigurationError(f"Invalid timeout_sec={settings.timeout_sec}. Must be > 0.")


# ==============================================================================
# Global Configuration Accessor
# ==============================================================================

_CACHED_CONFIG: Optional[AppConfig] = None

def get_config(reload: bool = False) -> AppConfig:
    """Returns the singleton application configuration."""
    global _CACHED_CONFIG
    if _CACHED_CONFIG is None or reload:
        loader = ConfigLoader()
        _CACHED_CONFIG = loader.load_config()
    return _CACHED_CONFIG


# ==============================================================================
# CLI Entrypoint & Connectivity Diagnostic
# ==============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="CC2 Configuration Subsystem & Non-Destructive Connectivity Probe"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Perform non-destructive connectivity check across Host, KVM, VirtualBox, and LXC"
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        help="Dump sanitized configuration in JSON format"
    )
    args = parser.parse_args()

    try:
        cfg = get_config(reload=True)
    except Exception as e:
        print(f"[!] Configuration Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.dump:
        import json
        print(json.dumps(cfg.to_sanitized_dict(), indent=2))
        return

    if args.check:
        from .connectivity import run_connectivity_check
        run_connectivity_check(cfg)
        return

    # Default overview
    print("CC2 Configuration Summary")
    print("=========================")
    print(f".env loaded:          {'YES (' + str(cfg.env_file_path) + ')' if cfg.env_file_loaded else 'NO (using defaults/example)'}")
    print(f"Environments defined: {', '.join(cfg.list_environments())}")
    print(f"Benchmarks defined:   {', '.join(cfg.list_benchmarks())}")
    print("\nRun with --check to perform non-destructive connectivity probes.")


if __name__ == "__main__":
    main()
