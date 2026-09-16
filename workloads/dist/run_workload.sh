#!/usr/bin/env bash
# ==============================================================================
# run_workload.sh - Portable execution wrapper for CC2 Common Workloads
# Standardized execution across Host, KVM, VirtualBox, and LXC
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    echo "Usage: $0 {cpu|memory} [options]"
    echo "  cpu:    runs cpu_workload [--size <N>] [--iterations <I>] [--warmup <W>] [--threads <T>]"
    echo "  memory: runs memory_workload [--buffer-mb <MB>] [--passes <P>] [--stride <S>]"
    exit 1
}

if [ $# -lt 1 ]; then
    usage
fi

WORKLOAD="$1"
shift

case "$WORKLOAD" in
    cpu)
        exec "$SCRIPT_DIR/cpu_workload" "$@"
        ;;
    memory)
        exec "$SCRIPT_DIR/memory_workload" "$@"
        ;;
    *)
        echo "Unknown workload: $WORKLOAD" >&2
        usage
        ;;
esac
