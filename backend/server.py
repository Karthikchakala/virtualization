#!/usr/bin/env python3
"""
backend/server.py - Safe HTTP Backend API for CC2 Virtualization Lab.

Provides a safe REST API interface for dashboard integration:
- Benchmark execution dispatch (strict whitelist validation, zero shell execution)
- Job monitoring and real-time progress inspection
- Sanitized terminal log streaming
- Processed result and comparative summary retrieval
- Health and environment introspection

Built using Python's standard library ThreadingHTTPServer for maximum reliability,
zero external dependencies, and seamless concurrent responsiveness.
"""

import os
import re
import sys
import json
import socket
import logging
from datetime import datetime, timezone
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Dict, Any, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.sanitizer import sanitize_text, sanitize_dict_records
from backend.job_manager import (
    get_job_manager,
    JobManager,
    ConcurrencyConflictError,
    InvalidJobRequestError,
    VALID_ENVIRONMENTS,
    BENCHMARK_ALIASES
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [API] %(message)s"
)
logger = logging.getLogger("CC2_API")

DEFAULT_PORT = 8000
RESULTS_DIR = PROJECT_ROOT / "results"
PROCESSED_DIR = RESULTS_DIR / "processed"

# Allowed CORS origins
ALLOWED_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000"
}
custom_origin = os.environ.get("FRONTEND_ORIGIN")
if custom_origin:
    ALLOWED_ORIGINS.add(custom_origin.strip())


class BenchmarkApiHandler(BaseHTTPRequestHandler):
    """
    HTTP Request Handler dispatching benchmark operations.
    """

    job_manager: JobManager = get_job_manager()

    def version_string(self) -> str:
        return "CC2-Benchmark-API/1.0.0"

    def log_message(self, format: str, *args: Any) -> None:
        """Sanitize server console log messages."""
        msg = format % args
        logger.info(sanitize_text(msg))

    def _get_cors_origin(self) -> str:
        """Determines the appropriate CORS origin header."""
        request_origin = self.headers.get("Origin", "")
        if request_origin in ALLOWED_ORIGINS:
            return request_origin
        # If running in local test/dev without explicit browser Origin header
        return request_origin or "http://localhost:5173"

    def _send_json(self, data: Any, status_code: int = 200) -> None:
        """Helper to send a JSON response with security & CORS headers."""
        sanitized = sanitize_dict_records(data)
        encoded = json.dumps(sanitized, indent=2).encode("utf-8")

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", self._get_cors_origin())
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(encoded)

    def _send_error(self, message: str, status_code: int = 400, details: Optional[Dict[str, Any]] = None) -> None:
        """Helper to send a structured JSON error response."""
        payload = {
            "error": sanitize_text(message),
            "status_code": status_code,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        if details:
            payload["details"] = sanitize_dict_records(details)
        self._send_json(payload, status_code=status_code)

    def do_OPTIONS(self) -> None:
        """Handles CORS preflight requests."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self._get_cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        """Routes GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        try:
            # 1. Health check
            if path == "/api/benchmarks/health":
                self._handle_health()
                return

            # 2. List jobs
            if path == "/api/benchmarks/jobs":
                self._handle_list_jobs()
                return

            # 3. Job status by ID: /api/benchmarks/jobs/<id>
            job_match = re.match(r"^/api/benchmarks/jobs/([^/]+)$", path)
            if job_match:
                job_id = job_match.group(1)
                self._handle_get_job(job_id)
                return

            # 4. Job logs by ID: /api/benchmarks/jobs/<id>/logs
            logs_match = re.match(r"^/api/benchmarks/jobs/([^/]+)/logs$", path)
            if logs_match:
                job_id = logs_match.group(1)
                self._handle_get_job_logs(job_id)
                return

            # 5. Analysis summary: /api/benchmarks/summary
            if path == "/api/benchmarks/summary":
                self._handle_get_summary()
                return

            # 6. Filtered results: /api/benchmarks/results/<env>/<bench>
            res_filter_match = re.match(r"^/api/benchmarks/results/([^/]+)/([^/]+)$", path)
            if res_filter_match:
                env_name = res_filter_match.group(1)
                bench_name = res_filter_match.group(2)
                self._handle_get_results(environment=env_name, benchmark=bench_name)
                return

            # 7. Global results: /api/benchmarks/results
            if path == "/api/benchmarks/results":
                self._handle_get_results()
                return

            # 404 for unknown endpoints
            self._send_error(f"Endpoint not found: {path}", status_code=404)

        except Exception as e:
            logger.error(f"Internal server error handling GET {path}: {sanitize_text(str(e))}")
            self._send_error("Internal server error", status_code=500)

    def do_POST(self) -> None:
        """Routes POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        try:
            if path == "/api/benchmarks/run":
                self._handle_run_job()
                return

            # Job cancellation endpoint: /api/benchmarks/jobs/<id>/cancel
            cancel_match = re.match(r"^/api/benchmarks/jobs/([^/]+)/cancel$", path)
            if cancel_match:
                job_id = cancel_match.group(1)
                self._handle_cancel_job(job_id)
                return

            self._send_error(f"Endpoint not found: {path}", status_code=404)

        except Exception as e:
            logger.error(f"Internal server error handling POST {path}: {sanitize_text(str(e))}")
            self._send_error("Internal server error", status_code=500)

    # ==========================================================================
    # Handler Implementations
    # ==========================================================================

    def _handle_health(self) -> None:
        """Health check and environment readiness status."""
        health_data = {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": "cc2-benchmark-api",
            "version": "1.0.0",
            "environments": {
                "host": {
                    "name": "host",
                    "display_name": "Bare-Metal Host Baseline",
                    "classification": "Reference Overhead Baseline",
                    "status": "available"
                },
                "kvm": {
                    "name": "kvm",
                    "display_name": "KVM / QEMU",
                    "classification": "kernel-based hardware virtualization / Type-1-like",
                    "status": "available"
                },
                "virtualbox": {
                    "name": "virtualbox",
                    "display_name": "Oracle VM VirtualBox",
                    "classification": "Type-2 hosted hypervisor",
                    "status": "available"
                },
                "lxc": {
                    "name": "lxc",
                    "display_name": "Native Linux Containers (LXC)",
                    "classification": "Linux OS-level virtualization / containerization",
                    "status": "available"
                }
            }
        }
        self._send_json(health_data, status_code=200)

    def _handle_run_job(self) -> None:
        """Handles POST /api/benchmarks/run."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_error("Missing request body", status_code=400)
            return

        try:
            body = self.rfile.read(content_length).decode("utf-8")
            payload = json.loads(body)
        except Exception as e:
            self._send_error(f"Malformed JSON body: {sanitize_text(str(e))}", status_code=400)
            return

        try:
            job = self.job_manager.create_and_start_job(payload)
            self._send_json(job.to_summary_dict(), status_code=202)
        except InvalidJobRequestError as e:
            self._send_error(str(e), status_code=400)
        except ConcurrencyConflictError as e:
            self._send_error(str(e), status_code=409)

    def _handle_list_jobs(self) -> None:
        """Handles GET /api/benchmarks/jobs."""
        jobs = self.job_manager.list_jobs(limit=50)
        self._send_json({
            "count": len(jobs),
            "jobs": [j.to_summary_dict() for j in jobs]
        }, status_code=200)

    def _handle_get_job(self, job_id: str) -> None:
        """Handles GET /api/benchmarks/jobs/<id>."""
        job = self.job_manager.get_job(job_id)
        if not job:
            self._send_error(f"Job '{job_id}' not found", status_code=404)
            return
        self._send_json(job.to_detail_dict(), status_code=200)

    def _handle_get_job_logs(self, job_id: str) -> None:
        """Handles GET /api/benchmarks/jobs/<id>/logs."""
        job = self.job_manager.get_job(job_id)
        if not job:
            self._send_error(f"Job '{job_id}' not found", status_code=404)
            return
        self._send_json({
            "job_id": job.job_id,
            "status": job.status,
            "stdout": job.stdout,
            "stderr": job.stderr,
            "sanitized": True
        }, status_code=200)

    def _handle_cancel_job(self, job_id: str) -> None:
        """Handles POST /api/benchmarks/jobs/<id>/cancel."""
        success = self.job_manager.cancel_job(job_id)
        if not success:
            self._send_error(f"Job '{job_id}' could not be cancelled or not active", status_code=400)
            return
        self._send_json({"job_id": job_id, "status": "cancelled"}, status_code=200)

    def _handle_get_results(self, environment: Optional[str] = None, benchmark: Optional[str] = None) -> None:
        """
        Handles GET /api/benchmarks/results and GET /api/benchmarks/results/:env/:bench.
        Reads verified analysis dataset or processed stream without executing benchmarks.
        """
        # Normalization
        if benchmark and benchmark in BENCHMARK_ALIASES:
            benchmark = BENCHMARK_ALIASES[benchmark]

        # Check runs.json first as it contains the verified run records
        dataset_path = PROCESSED_DIR / "runs.json"
        if not dataset_path.exists():
            dataset_path = PROCESSED_DIR / "analysis_dataset.json"

        if not dataset_path.exists():
            self._send_json({
                "count": 0,
                "results": [],
                "message": "No processed benchmark results available yet."
            }, status_code=200)
            return

        try:
            with open(dataset_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Extract list of results
            if isinstance(data, list):
                results_list = data
            elif isinstance(data, dict):
                candidates = data.get("runs") or data.get("results") or data.get("dataset") or data.get("metrics") or []
                results_list = candidates if isinstance(candidates, list) else []
            else:
                results_list = []

            # Filter by environment and benchmark if specified
            if environment and environment != "all":
                results_list = [r for r in results_list if r.get("environment") == environment]
            if benchmark and benchmark != "all":
                results_list = [r for r in results_list if r.get("benchmark") == benchmark]

            self._send_json({
                "count": len(results_list),
                "environment": environment or "all",
                "benchmark": benchmark or "all",
                "results": results_list
            }, status_code=200)

        except Exception as e:
            logger.error(f"Error loading results dataset: {sanitize_text(str(e))}")
            self._send_error("Failed to load processed results dataset", status_code=500)

    def _handle_get_summary(self) -> None:
        """
        Handles GET /api/benchmarks/summary.
        Returns the non-evaluative multi-environment summary.
        """
        summary_path = PROCESSED_DIR / "environment_summary.json"
        if not summary_path.exists():
            # Fallback to report_summary.json
            summary_path = RESULTS_DIR / "report_summary.json"

        if not summary_path.exists():
            self._send_json({
                "summary": {},
                "message": "No environment summary available yet."
            }, status_code=200)
            return

        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
            self._send_json({
                "summary": summary,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }, status_code=200)
        except Exception as e:
            logger.error(f"Error reading summary: {sanitize_text(str(e))}")
            self._send_error("Failed to read environment summary", status_code=500)


def create_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """Creates a ThreadingHTTPServer instance."""
    server_address = (host, port)
    server = ThreadingHTTPServer(server_address, BenchmarkApiHandler)
    server.daemon_threads = True
    return server


def run_api_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
    """Starts the CC2 Benchmark API Server."""
    server = create_server(host=host, port=port)
    logger.info(f"CC2 Benchmark API Server running at http://{host}:{port}")
    logger.info("Endpoints available:")
    logger.info("  POST /api/benchmarks/run")
    logger.info("  GET  /api/benchmarks/jobs")
    logger.info("  GET  /api/benchmarks/jobs/:id")
    logger.info("  GET  /api/benchmarks/jobs/:id/logs")
    logger.info("  GET  /api/benchmarks/results")
    logger.info("  GET  /api/benchmarks/results/:env/:benchmark")
    logger.info("  GET  /api/benchmarks/summary")
    logger.info("  GET  /api/benchmarks/health")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down API server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CC2 Benchmark API Backend")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port (default: 8000)")
    args = parser.parse_args()

    run_api_server(host=args.host, port=args.port)
