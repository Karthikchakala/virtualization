#!/usr/bin/env python3
"""
test_safety.py - Verifies that safety guards reject destructive operations
and permit safe non-destructive inspection commands.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collector.common import SafetyValidator, SafetyViolationError

class TestSafetyValidator(unittest.TestCase):

    def test_blocks_destructive_disk_commands(self):
        dangerous_commands = [
            "mkfs.ext4 /dev/nvme0n1p6",
            "fdisk /dev/nvme0n1",
            "parted /dev/nvme0n1 mkpart primary 100 200",
            "wipefs -a /dev/nvme0n1",
            "dd if=/dev/zero of=/dev/nvme0n1 bs=1M count=10",
            "dd if=/dev/urandom of=/dev/sda1",
            "echo hello > /dev/nvme0n1p3",
            "virsh undefine ubuntu24.04",
            "virsh destroy ubuntu24.04 --remove-all-storage",
            "VBoxManage unregistervm Ubuntu-Server-VBox --delete",
            "lxc-destroy -n lxc-ubuntu",
            "rm -rf /boot/efi"
        ]
        for cmd in dangerous_commands:
            with self.subTest(cmd=cmd):
                self.assertFalse(SafetyValidator.is_safe(cmd), f"SafetyValidator failed to block dangerous command: {cmd}")
                with self.assertRaises(SafetyViolationError):
                    SafetyValidator.validate_command(cmd)

    def test_allows_safe_inspection_commands(self):
        safe_commands = [
            "uname -a",
            "lscpu",
            "free -h",
            "lsblk",
            "findmnt -J",
            "ip addr",
            "ip route",
            "virsh -c qemu:///system list --all",
            "VBoxManage list vms",
            "lxc-ls --fancy",
            "lxc-info -n lxc-ubuntu",
            "/home/karthik-chakala/Downloads/CC2/workloads/cpu_workload --size 100 --iterations 2"
        ]
        for cmd in safe_commands:
            with self.subTest(cmd=cmd):
                self.assertTrue(SafetyValidator.is_safe(cmd), f"SafetyValidator blocked safe command: {cmd}")

if __name__ == "__main__":
    unittest.main()
