#!/usr/bin/env bash
# ==============================================================================
# CC2 Benchmark API Server Runner
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

HOST="${1:-127.0.0.1}"
PORT="${2:-8000}"

echo "[*] Starting CC2 Benchmark API Server on ${HOST}:${PORT}..."
exec python3 "${PROJECT_ROOT}/backend/server.py" --host "${HOST}" --port "${PORT}"
