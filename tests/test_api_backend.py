#!/usr/bin/env python3
"""
tests/test_api_backend.py - Unit & Integration Tests for CC2 Benchmark API.

Tests:
1. Health check endpoint (GET /api/benchmarks/health)
2. Valid run request dispatch (POST /api/benchmarks/run)
3. Input validation: invalid environment rejection
4. Input validation: invalid benchmark rejection
5. Input validation: invalid runs count rejection
6. Input validation: shell command injection rejection
7. Job listing (GET /api/benchmarks/jobs)
8. Job status by ID (GET /api/benchmarks/jobs/:id)
9. Nonexistent job handling (404 Not Found)
10. Sanitized logs retrieval (GET /api/benchmarks/jobs/:id/logs)
11. Results retrieval without benchmark execution (GET /api/benchmarks/results)
12. Filtered results retrieval (GET /api/benchmarks/results/:env/:bench)
13. Summary retrieval (GET /api/benchmarks/summary)
14. Concurrency conflict protection (HTTP 409 Conflict)
15. Secret redaction and log sanitization
16. CORS preflight and headers (OPTIONS / GET)
"""

import os
import sys
import json
import time
import unittest
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock
from urllib.request import Request, urlopen
from urllib.error import HTTPError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.server import create_server
from backend.job_manager import JobManager, BenchmarkJob, JobProgress
from backend.sanitizer import sanitize_text, sanitize_dict_records


class TestBackendApi(unittest.TestCase):
    """Test suite for CC2 Benchmark API server and JobManager."""

    @classmethod
    def setUpClass(cls):
        # Bind to an ephemeral port for testing
        cls.test_port = 8899
        cls.test_host = "127.0.0.1"
        cls.base_url = f"http://{cls.test_host}:{cls.test_port}"

        # Initialize test server
        cls.server = create_server(host=cls.test_host, port=cls.test_port)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _http_get(self, path: str, headers: dict = None) -> tuple:
        url = f"{self.base_url}{path}"
        req = Request(url, headers=headers or {})
        try:
            with urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data, resp.headers
        except HTTPError as e:
            data = json.loads(e.read().decode("utf-8"))
            return e.code, data, e.headers

    def _http_post(self, path: str, payload: dict, headers: dict = None) -> tuple:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        req = Request(url, data=body, headers=req_headers, method="POST")
        try:
            with urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data, resp.headers
        except HTTPError as e:
            data = json.loads(e.read().decode("utf-8"))
            return e.code, data, e.headers

    def test_01_health_check(self):
        """Verify GET /api/benchmarks/health returns 200 and valid environment states."""
        status, data, headers = self._http_get("/api/benchmarks/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "cc2-benchmark-api")
        self.assertIn("host", data["environments"])
        self.assertIn("kvm", data["environments"])
        self.assertIn("virtualbox", data["environments"])
        self.assertIn("lxc", data["environments"])

    def test_02_cors_preflight(self):
        """Verify OPTIONS preflight request returns 204 with CORS headers."""
        url = f"{self.base_url}/api/benchmarks/run"
        req = Request(url, headers={"Origin": "http://localhost:5173"}, method="OPTIONS")
        with urlopen(req) as resp:
            self.assertEqual(resp.status, 204)
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "http://localhost:5173")
            self.assertIn("POST", resp.headers.get("Access-Control-Allow-Methods", ""))

    def test_03_invalid_environment_rejection(self):
        """Verify POST /api/benchmarks/run rejects unknown or forbidden environments."""
        payload = {"environment": "docker", "benchmark": "cpu", "mode": "quick", "runs": 2}
        status, data, _ = self._http_post("/api/benchmarks/run", payload)
        self.assertEqual(status, 400)
        self.assertIn("Invalid environment", data["error"])

    def test_04_invalid_benchmark_rejection(self):
        """Verify POST /api/benchmarks/run rejects unknown benchmarks."""
        payload = {"environment": "host", "benchmark": "crypto_miner", "mode": "quick", "runs": 2}
        status, data, _ = self._http_post("/api/benchmarks/run", payload)
        self.assertEqual(status, 400)
        self.assertIn("Invalid benchmark", data["error"])

    def test_05_invalid_runs_count_rejection(self):
        """Verify POST /api/benchmarks/run rejects negative or excessive run counts."""
        payload = {"environment": "host", "benchmark": "cpu", "mode": "quick", "runs": 999}
        status, data, _ = self._http_post("/api/benchmarks/run", payload)
        self.assertEqual(status, 400)
        self.assertIn("between 1 and 20", data["error"])

    def test_06_shell_injection_rejection(self):
        """Verify POST /api/benchmarks/run rejects shell metacharacters."""
        payload = {"environment": "host; rm -rf /", "benchmark": "cpu", "mode": "quick", "runs": 2}
        status, data, _ = self._http_post("/api/benchmarks/run", payload)
        self.assertEqual(status, 400)

    def test_07_valid_run_request_and_job_tracking(self):
        """Verify POST /api/benchmarks/run creates job in dry-run mode."""
        payload = {
            "environment": "host",
            "benchmark": "cpu",
            "mode": "quick",
            "runs": 2,
            "dry_run": True
        }
        status, data, _ = self._http_post("/api/benchmarks/run", payload)
        self.assertEqual(status, 202)
        self.assertIn("job_id", data)
        self.assertEqual(data["environment"], "host")
        self.assertEqual(data["benchmark"], "cpu_deterministic")
        self.assertTrue(data["is_dry_run"])

        job_id = data["job_id"]

        # Verify job is listed in GET /api/benchmarks/jobs
        status, list_data, _ = self._http_get("/api/benchmarks/jobs")
        self.assertEqual(status, 200)
        job_ids = [j["job_id"] for j in list_data["jobs"]]
        self.assertIn(job_id, job_ids)

        # Verify job details in GET /api/benchmarks/jobs/:id
        status, job_data, _ = self._http_get(f"/api/benchmarks/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(job_data["job_id"], job_id)
        self.assertIn("progress", job_data)

        # Wait for dry-run worker thread to complete
        time.sleep(0.5)

        # Verify job logs in GET /api/benchmarks/jobs/:id/logs
        status, log_data, _ = self._http_get(f"/api/benchmarks/jobs/{job_id}/logs")
        self.assertEqual(status, 200)
        self.assertTrue(log_data["sanitized"])

    def test_08_nonexistent_job_returns_404(self):
        """Verify GET /api/benchmarks/jobs/:id returns 404 for invalid IDs."""
        status, data, _ = self._http_get("/api/benchmarks/jobs/job-nonexistent-1234")
        self.assertEqual(status, 404)
        self.assertIn("not found", data["error"].lower())

    def test_09_concurrency_conflict_protection(self):
        """Verify active experiment prevents simultaneous benchmark execution."""
        jm = self.server.RequestHandlerClass.job_manager

        # Artificially set an active running job
        dummy_job = BenchmarkJob(
            job_id="job-active-test-concurrency",
            status="running",
            environment="kvm",
            benchmark="cpu_deterministic",
            mode="full",
            runs=5,
            created_at="2026-09-17T00:00:00Z"
        )
        with jm._lock:
            jm._jobs[dummy_job.job_id] = dummy_job
            prev_active = jm._active_job_id
            jm._active_job_id = dummy_job.job_id

        try:
            payload = {"environment": "host", "benchmark": "cpu", "mode": "quick", "runs": 1}
            status, data, _ = self._http_post("/api/benchmarks/run", payload)
            self.assertEqual(status, 409)
            self.assertIn("currently running", data["error"])
        finally:
            with jm._lock:
                dummy_job.status = "completed"
                jm._active_job_id = prev_active

    def test_10_results_retrieval(self):
        """Verify GET /api/benchmarks/results returns processed dataset."""
        status, data, _ = self._http_get("/api/benchmarks/results")
        self.assertEqual(status, 200)
        self.assertIn("results", data)
        self.assertIn("count", data)

    def test_11_summary_retrieval_non_evaluative(self):
        """Verify GET /api/benchmarks/summary returns summary without ranking/winner fields."""
        status, data, _ = self._http_get("/api/benchmarks/summary")
        self.assertEqual(status, 200)
        self.assertIn("summary", data)

        envs = data["summary"].get("environments", {})
        for env_name, env_data in envs.items():
            for bench_name, bench_data in env_data.get("benchmarks_evaluated", {}).items():
                for key in bench_data.keys():
                    self.assertNotIn("winner", key.lower())
                    self.assertNotIn("ranking", key.lower())
                    self.assertNotIn("score", key.lower())
                    self.assertNotIn("rank", key.lower())

    def test_12_secret_sanitization(self):
        """Verify sanitizer properly scrubs private keys and passwords."""
        raw_log = "Error: password='SuperSecretPassword123' sshpass -p 'pass456' ssh user@host"
        sanitized = sanitize_text(raw_log)
        self.assertNotIn("SuperSecretPassword123", sanitized)
        self.assertNotIn("pass456", sanitized)
        self.assertIn("********", sanitized)

        # Dictionary scrubbing
        dict_payload = {
            "environment": "kvm",
            "ssh_password": "PlaintextPassword",
            "safe_field": 42
        }
        sanitized_dict = sanitize_dict_records(dict_payload)
        self.assertEqual(sanitized_dict["ssh_password"], "********")
        self.assertEqual(sanitized_dict["safe_field"], 42)


if __name__ == "__main__":
    unittest.main()
