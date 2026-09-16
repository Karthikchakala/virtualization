#!/usr/bin/env python3
"""
tests/test_configuration.py - Comprehensive Unit Tests for CC2 Configuration Subsystem.

Verifies:
1. .env parsing (quoted, unquoted, comments, export prefixes)
2. Required value validation (missing VM/container names)
3. Optional value handling (defaults, dynamic IP discovery allowance)
4. Integer validation (port ranges, timeouts, run counts)
5. Environment name validation (rejection of unapproved environments)
6. Secret masking ('********' for non-empty secrets)
7. repr() does not leak secrets across configuration objects
8. .env.example exists and contains template variables
9. .env is ignored by Git (.gitignore verification)
10. YAML loading for environments.yaml and benchmark.yaml
11. Benchmark configuration loading across all 10 domains
12. CPU canonical parameters remain correct (400 size, 5 iters, 640M FLOPs, 0x7e83d4c61ad5adb8)
13. Malformed configuration rejection
14. Connectivity probe command construction does not leak secrets
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmark.runner.config import (
    AppConfig,
    ConfigLoader,
    ConfigurationError,
    EnvironmentConfig,
    BenchmarkConfig,
    GlobalSettings,
    load_env_file,
    mask_secret,
    sanitize_dict,
    get_config
)
from benchmark.runner.connectivity import (
    run_safe_ssh_probe,
    check_host_connectivity,
    check_kvm_connectivity,
    check_vbox_connectivity,
    check_lxc_connectivity
)


class TestConfigurationSubsystem(unittest.TestCase):

    def setUp(self):
        self.loader = ConfigLoader()
        self.config = self.loader.load_config()

    # 1. .env parsing
    def test_env_file_parsing(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".env") as f:
            f.write("# Sample comment\n")
            f.write("KVM_VM_NAME=custom-kvm\n")
            f.write("export VBOX_SSH_PORT=2223\n")
            f.write('SECRET_KEY="my_secret_token"\n')
            f.write("SINGLE_QUOTED='single_value'\n")
            f.write("INLINE_COMMENT=value # inline comment\n")
            temp_path = Path(f.name)

        try:
            parsed = load_env_file(temp_path)
            self.assertEqual(parsed.get("KVM_VM_NAME"), "custom-kvm")
            self.assertEqual(parsed.get("VBOX_SSH_PORT"), "2223")
            self.assertEqual(parsed.get("SECRET_KEY"), "my_secret_token")
            self.assertEqual(parsed.get("SINGLE_QUOTED"), "single_value")
            self.assertEqual(parsed.get("INLINE_COMMENT"), "value")
        finally:
            if temp_path.exists():
                temp_path.unlink()

    # 2. Required value validation
    def test_required_vm_names_validation(self):
        envs = self.config.environments.copy()
        
        # Test KVM missing VM name
        bad_kvm = EnvironmentConfig(
            name="kvm",
            display_name="KVM",
            classification="Type-1",
            virtualization_type="type1",
            transport="ssh",
            vm_name=None
        )
        envs_bad = {"kvm": bad_kvm}
        with self.assertRaises(ConfigurationError):
            self.loader._validate_config(envs_bad, self.config.benchmarks, self.config.settings)

    # 3. Optional value handling
    def test_optional_ssh_host_handling(self):
        # KVM SSH host can be None initially (dynamic discovery)
        kvm_cfg = self.config.get_env("kvm")
        self.assertIsNotNone(kvm_cfg.vm_name)
        # Port should default to 22
        self.assertEqual(kvm_cfg.ssh_port, 22)

    # 4. Integer validation
    def test_integer_validation(self):
        # Invalid SSH port
        bad_vbox = EnvironmentConfig(
            name="virtualbox",
            display_name="VBox",
            classification="Type-2",
            virtualization_type="type2",
            transport="ssh",
            vm_name="Ubuntu-Server-VBox",
            ssh_port=99999  # Invalid port
        )
        with self.assertRaises(ConfigurationError):
            self.loader._validate_config({"virtualbox": bad_vbox}, self.config.benchmarks, self.config.settings)

        # Invalid benchmark measured_runs
        bad_bench = BenchmarkConfig(
            name="test_bench",
            domain="test",
            workload_name="test",
            description="test",
            measured_runs=0  # Invalid
        )
        with self.assertRaises(ConfigurationError):
            self.loader._validate_config(self.config.environments, {"test_bench": bad_bench}, self.config.settings)

    # 5. Environment name validation
    def test_environment_name_validation(self):
        bad_env = EnvironmentConfig(
            name="docker_invalid",  # Prohibited environment
            display_name="Docker",
            classification="Container",
            virtualization_type="container",
            transport="docker"
        )
        with self.assertRaises(ConfigurationError):
            self.loader._validate_config({"docker_invalid": bad_env}, self.config.benchmarks, self.config.settings)

    # 6. Secret masking
    def test_secret_masking(self):
        self.assertEqual(mask_secret("super_secret_password_123"), "********")
        self.assertEqual(mask_secret(""), "(not configured)")
        self.assertEqual(mask_secret(None), "(not configured)")

        # Test dictionary sanitizer
        test_data = {
            "user": "karthik",
            "ssh_password": "real_password",
            "nested": {
                "api_key": "12345-secret",
                "normal": "visible"
            }
        }
        sanitized = sanitize_dict(test_data)
        self.assertEqual(sanitized["ssh_password"], "********")
        self.assertEqual(sanitized["nested"]["api_key"], "********")
        self.assertEqual(sanitized["user"], "karthik")
        self.assertEqual(sanitized["nested"]["normal"], "visible")

    # 7. repr() does not leak secrets
    def test_repr_does_not_leak_secrets(self):
        env_with_secret = EnvironmentConfig(
            name="kvm",
            display_name="KVM",
            classification="Type-1",
            virtualization_type="type1",
            transport="ssh",
            vm_name="ubuntu24.04",
            ssh_password="extremely_secret_password_abc"
        )
        repr_str = repr(env_with_secret)
        self.assertNotIn("extremely_secret_password_abc", repr_str)
        self.assertIn("********", repr_str)

        sanitized_dict = env_with_secret.to_sanitized_dict()
        self.assertEqual(sanitized_dict["ssh_password"], "********")

    # 8. .env.example exists
    def test_env_example_exists(self):
        env_example = PROJECT_ROOT / ".env.example"
        self.assertTrue(env_example.exists(), ".env.example must exist in project root")
        content = env_example.read_text()
        self.assertIn("KVM_VM_NAME", content)
        self.assertIn("VBOX_VM_NAME", content)
        self.assertIn("LXC_CONTAINER_NAME", content)
        self.assertIn("BENCHMARK_STABILIZATION_SEC", content)

    # 9. .env is ignored by Git (.gitignore verification)
    def test_env_is_ignored_in_gitignore(self):
        gitignore = PROJECT_ROOT / ".gitignore"
        self.assertTrue(gitignore.exists(), ".gitignore must exist in project root")
        content = gitignore.read_text()
        self.assertTrue(any(line.strip() == ".env" for line in content.splitlines()), ".env must be ignored")
        self.assertTrue(any(".env.*" in line for line in content.splitlines()), ".env.* must be ignored")
        self.assertTrue(any("!.env.example" in line for line in content.splitlines()), "!.env.example must NOT be ignored")

    # 10. YAML loading
    def test_yaml_files_load_valid(self):
        self.assertGreaterEqual(len(self.config.environments), 4)
        for expected in ["host", "kvm", "virtualbox", "lxc"]:
            self.assertIn(expected, self.config.environments)

    # 11. Benchmark configuration loading
    def test_all_ten_benchmarks_loaded(self):
        expected_benchmarks = [
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
        for bench in expected_benchmarks:
            self.assertIn(bench, self.config.benchmarks, f"Missing benchmark configuration for '{bench}'")
            cfg = self.config.get_benchmark(bench)
            self.assertTrue(cfg.enabled)
            self.assertGreater(cfg.timeout_sec, 0)
            self.assertGreater(cfg.measured_runs, 0)

    # 12. CPU canonical parameters remain correct
    def test_cpu_canonical_parameters_integrity(self):
        cpu_cfg = self.config.get_benchmark("cpu_deterministic")
        p = cpu_cfg.parameters
        self.assertEqual(p.get("size"), 400)
        self.assertEqual(p.get("iterations"), 5)
        self.assertEqual(p.get("warmup"), 1)
        self.assertEqual(p.get("threads"), 1)

        invar = cpu_cfg.canonical_invariants
        self.assertEqual(invar.get("total_flops"), 640000000)
        self.assertEqual(invar.get("expected_checksum"), "0x7e83d4c61ad5adb8")

    # 13. Malformed configuration rejection
    def test_malformed_config_rejection(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            bad_yaml = td_path / "environments.yaml"
            bad_yaml.write_text("invalid: [unclosed list")

            loader = ConfigLoader(config_dir=td_path)
            with self.assertRaises(ConfigurationError):
                loader.load_config()

    # 14. Connectivity command construction does not leak secrets
    @patch("subprocess.run")
    def test_ssh_probe_does_not_leak_password_on_cli(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="6.8.0-generic\n", stderr="")
        
        # When key_path is used, verify command arguments
        res = run_safe_ssh_probe(
            host="192.168.122.179",
            port=22,
            user="testuser",
            command="uname -r",
            key_path=str(PROJECT_ROOT / ".env.example"), # dummy existing file
            password="secret_pass_not_used"
        )
        self.assertEqual(res["status"], "success")
        args, _ = mock_run.call_args
        cmd_called = args[0]
        # Password must NEVER appear in the command line list
        for token in cmd_called:
            self.assertNotIn("secret_pass_not_used", token)


if __name__ == "__main__":
    unittest.main()
