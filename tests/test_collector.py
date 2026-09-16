#!/usr/bin/env python3
"""
test_collector.py - Validates that the host inventory collector captures real,
traceable host data and produces valid JSON matching the system state.
"""

import sys
import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class TestCollector(unittest.TestCase):

    def setUp(self):
        self.inv_path = PROJECT_ROOT / "results" / "host_inventory.json"
        self.assertTrue(self.inv_path.exists(), "host_inventory.json must exist before test")
        with open(self.inv_path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def test_top_level_sections(self):
        required_sections = ["os", "cpu", "memory", "storage", "network", "kvm", "virtualbox", "lxc", "tools"]
        for sec in required_sections:
            self.assertIn(sec, self.data, f"Section '{sec}' missing in host_inventory.json")

    def test_cpu_data_is_real(self):
        cpu = self.data.get("cpu", {})
        self.assertIn("model_name", cpu)
        self.assertTrue("Intel" in cpu["model_name"] or "AMD" in cpu["model_name"])
        self.assertGreater(cpu.get("logical_cpus", 0), 0)
        self.assertTrue(cpu.get("hardware_virt_support", {}).get("intel_vmx"))

    def test_kvm_discovery(self):
        kvm = self.data.get("kvm", {})
        self.assertTrue(kvm.get("dev_kvm_exists"), "/dev/kvm must exist on host")
        self.assertTrue(kvm.get("virsh_available"), "virsh must be available")
        # Check domain discovered
        dom_names = [d["name"] for d in kvm.get("domains", [])]
        self.assertIn("ubuntu24.04", dom_names)

    def test_virtualbox_discovery(self):
        vbox = self.data.get("virtualbox", {})
        self.assertTrue(vbox.get("installed"), "VirtualBox must be detected as installed")
        vm_names = [v["name"] for v in vbox.get("vms", [])]
        self.assertIn("Ubuntu-Server-VBox", vm_names)

    def test_lxc_discovery(self):
        lxc = self.data.get("lxc", {})
        self.assertTrue(lxc.get("installed"), "LXC must be detected as installed")
        self.assertIsNotNone(lxc.get("version"))

if __name__ == "__main__":
    unittest.main()
