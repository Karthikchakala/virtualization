#!/usr/bin/env bash
# ==============================================================================
# env_discovery.sh - CC2 Virtualization & Host Discovery Script
# Executes safe, non-destructive host discovery commands and generates
# structured inventory artifacts.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=================================================="
echo "CC2 HOST & VIRTUALIZATION DISCOVERY"
echo "=================================================="
echo "Project Root: $PROJECT_ROOT"
echo "Timestamp:    $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo ""

echo "[1/6] Inspecting Kernel & Operating System..."
uname -a
echo -n "Virtualization layer: "
systemd-detect-virt || echo "none (bare-metal host)"
echo ""

echo "[2/6] Inspecting CPU & Memory Resources..."
lscpu | grep -E "Model name|CPU\(s\):|Thread\(s\) per core|Core\(s\) per socket|Virtualization|L3 cache" || true
free -h
echo ""

echo "[3/6] Inspecting Network & Storage Configuration..."
ip route show default || true
lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS,FSTYPE | grep -v "loop" || true
echo ""

echo "[4/6] Inspecting Virtualization Hypervisors..."
echo "--- KVM ---"
kvm-ok || true
virsh -c qemu:///system list --all || true

echo "--- VirtualBox ---"
VBoxManage -v || true
VBoxManage list vms || true
VBoxManage list runningvms || true

echo "--- Native LXC ---"
lxc-info --version || true
lxc-ls --fancy || true
echo ""

echo "[5/6] Checking Benchmark Utilities..."
for tool in fio iperf3 perf strace pidstat mpstat gcc g++ make python3 node npm; do
    if command -v "$tool" &>/dev/null; then
        echo "  [FOUND]     $tool -> $(command -v "$tool")"
    else
        echo "  [NOT FOUND] $tool"
    fi
done
echo ""

echo "[6/6] Executing Python Discovery Collector Engine..."
python3 "$PROJECT_ROOT/collector/inventory_collector.py"

echo "=================================================="
echo "Discovery complete. Inventory saved to results/host_inventory.json"
echo "=================================================="
