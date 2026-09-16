#!/usr/bin/env bash
# ==============================================================================
# runner.sh - CC2 Unified Experiment Runner Entry Point
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"

exec python3 "${SCRIPT_DIR}/runner.py" "$@"
