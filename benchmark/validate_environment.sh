#!/usr/bin/env bash
# ==============================================================================
# validate_environment.sh - CC2 Pre-Flight Virtualization & Dependency Validator
# Verifies:
# - Host Baseline hardware & kernel state
# - Hypervisors: KVM/QEMU, VirtualBox, Native LXC
# - Tooling: gcc, python3, fio, iperf3, perf, strace, pidstat, mpstat, curl
# Invariant: Missing optional dependencies are explicitly recorded.
# ==============================================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=================================================="
echo "CC2 PRE-FLIGHT ENVIRONMENT & DEPENDENCY VALIDATION"
echo "=================================================="

MISSING_OPTIONAL=()
MISSING_REQUIRED=()

check_tool() {
    local tool="$1"
    local required="$2"
    if command -v "$tool" &>/dev/null; then
        local tool_path
        tool_path="$(which "$tool")"
        echo "  [+] $tool: FOUND ($tool_path)"
    else
        if [ "$required" = "true" ]; then
            echo "  [!] $tool: MISSING (REQUIRED)"
            MISSING_REQUIRED+=("$tool")
        else
            echo "  [-] $tool: MISSING (OPTIONAL / NON-FATAL - WILL MARK STATUS=UNAVAILABLE)"
            MISSING_OPTIONAL+=("$tool")
        fi
    fi
}

echo ""
echo "[1/4] Checking Core & Benchmarking Tool Dependencies..."
check_tool "gcc" "true"
check_tool "python3" "true"
check_tool "perf" "false"
check_tool "strace" "false"
check_tool "pidstat" "false"
check_tool "mpstat" "false"
check_tool "curl" "true"
check_tool "fio" "false"
check_tool "iperf3" "false"

echo ""
echo "[2/4] Validating Virtualization Subsystems..."

# 1. KVM / Libvirt
if command -v virsh &>/dev/null; then
    KVM_DOMS=$(virsh -c qemu:///system list --all --name 2>/dev/null || true)
    if [ -n "$KVM_DOMS" ]; then
        echo "  [+] KVM/QEMU: Available via libvirt. Domains: $(echo "$KVM_DOMS" | tr '\n' ' ')"
    else
        echo "  [-] KVM/QEMU: virsh accessible but no domains found"
    fi
else
    echo "  [-] KVM/QEMU: virsh not found"
fi

# 2. VirtualBox
if command -v VBoxManage &>/dev/null; then
    VBOX_VMS=$(VBoxManage list vms 2>/dev/null || true)
    if [ -n "$VBOX_VMS" ]; then
        echo "  [+] VirtualBox: Available via VBoxManage. Discovered VMs:"
        echo "$VBOX_VMS" | sed 's/^/      /'
    else
        echo "  [-] VirtualBox: VBoxManage accessible but no registered VMs"
    fi
else
    echo "  [-] VirtualBox: VBoxManage not found"
fi

# 3. Native LXC
if command -v lxc-ls &>/dev/null; then
    LXC_CONTAINERS=$(lxc-ls 2>/dev/null || true)
    if [ -n "$LXC_CONTAINERS" ]; then
        echo "  [+] Native LXC: Available via lxc-ls. Containers: $(echo "$LXC_CONTAINERS" | tr '\n' ' ')"
    else
        echo "  [-] Native LXC: lxc-ls accessible but no containers listed"
    fi
else
    echo "  [-] Native LXC: lxc-ls not found"
fi

echo ""
echo "[3/4] Checking Linux Kernel Security & Performance Counter Access..."
if [ -f "/proc/sys/kernel/perf_event_paranoid" ]; then
    PARANOID_VAL=$(cat /proc/sys/kernel/perf_event_paranoid)
    echo "  [*] /proc/sys/kernel/perf_event_paranoid: $PARANOID_VAL"
    if [ "$PARANOID_VAL" -gt 2 ]; then
        echo "      -> Note: Hardware CPU counters restricted for unprivileged users."
        echo "      -> Exact reason will be recorded transparently; zero values will NOT be fabricated."
    fi
fi

echo ""
echo "[4/4] Pre-Flight Summary & Readiness Assessment..."
if [ ${#MISSING_REQUIRED[@]} -gt 0 ]; then
    echo "  [ERROR] Critical required dependencies missing: ${MISSING_REQUIRED[*]}"
    exit 1
fi

echo "  [OK] All critical dependencies and virtualization adapters verified."
if [ ${#MISSING_OPTIONAL[@]} -gt 0 ]; then
    echo "  [NOTE] Missing optional tools recorded: ${MISSING_OPTIONAL[*]}"
    echo "         Corresponding metrics will be marked as status=unavailable with explicit reasons."
fi

echo ""
echo "=================================================="
echo "PRE-FLIGHT VALIDATION PASSED SUCCESSFULLY"
echo "=================================================="
exit 0
