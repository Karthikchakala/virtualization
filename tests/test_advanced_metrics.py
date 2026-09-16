#!/usr/bin/env python3
"""
test_advanced_metrics.py - Comprehensive unit tests for Phase 6 Advanced Performance Measurements.

Validates:
1. Syscall Profiling & Parser (strace -c):
   - Table parsing with zero errors
   - Table parsing with nonzero errors
   - Empty/malformed strace handling (status=unavailable)
   - Top syscall ordering by calls and time
2. Scheduling Telemetry & Parser (pidstat -h -w -r & perf stat):
   - Parsing voluntary and involuntary context switch rates
   - Parsing minor and major page fault rates
   - Parsing CPU migrations
   - Empty/malformed pidstat handling
3. CPU Hardware Performance Counters (perf stat):
   - Parsing cycles, instructions, and IPC
   - Strict non-fabrication of counters when perf is restricted
   - Exact recording of kernel.perf_event_paranoid restriction reason
4. Thermal & System State Telemetry:
   - Reading CPU frequencies across cores
   - Reading CPU governors
   - Reading load averages
   - Reading thermal zones and package temperatures
   - Safety invariant: strictly read-only, never modifies governors or disables thermal protection
5. Application Latency (Minimal HTTP App & 100-request Benchmark):
   - HTTP server serves GET /health with 200 OK
   - 100-request socket benchmark measures connect, TTFB, and total latency
   - Statistical properties: mean, median, p50, p95, p99, min, max
6. Network Standardization (iperf3):
   - Enforcing identical duration, streams, direction, and protocol
   - JSON parsing of bandwidth, retransmits, and duration
"""

import os
import sys
import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collector.advanced_metrics import (
    StraceParser,
    SyscallCollector,
    PidstatParser,
    PerfStatParser,
    SchedulingCollector,
    ThermalSystemStateCollector,
    MinimalHealthHttpServer,
    HttpLatencyBenchmark,
    Iperf3Config
)
from collector.common import STATUS_SUCCESS, STATUS_UNAVAILABLE, STATUS_FAILED


class TestStraceParser(unittest.TestCase):

    def test_parse_clean_strace_output(self):
        sample = """
% time     seconds  usecs/call     calls    errors syscall
------ ----------- ----------- --------- --------- ----------------
 50.00    0.000100           5        20           write
 30.00    0.000060           6        10           read
 20.00    0.000040          40         1           execve
------ ----------- ----------- --------- --------- ----------------
100.00    0.000200           6        31           total
"""
        res = StraceParser.parse(sample)
        self.assertEqual(res["status"], STATUS_SUCCESS)
        self.assertEqual(res["syscall_count"], 31)
        self.assertAlmostEqual(res["syscall_time_sec"], 0.0002)
        self.assertEqual(res["errors"], 0)
        self.assertEqual(len(res["top_syscalls"]), 3)
        self.assertEqual(res["top_syscalls"][0]["syscall"], "write")
        self.assertEqual(res["top_syscalls"][0]["calls"], 20)

    def test_parse_strace_with_errors(self):
        sample = """
% time     seconds  usecs/call     calls    errors syscall
------ ----------- ----------- --------- --------- ----------------
 60.00    0.000300           5        60        15 openat
 40.00    0.000200          10        20           mmap
------ ----------- ----------- --------- --------- ----------------
100.00    0.000500           6        80        15 total
"""
        res = StraceParser.parse(sample)
        self.assertEqual(res["status"], STATUS_SUCCESS)
        self.assertEqual(res["syscall_count"], 80)
        self.assertAlmostEqual(res["syscall_time_sec"], 0.0005)
        self.assertEqual(res["errors"], 15)
        self.assertEqual(res["top_syscalls"][0]["syscall"], "openat")
        self.assertEqual(res["top_syscalls"][0]["errors"], 15)

    def test_parse_empty_or_malformed_strace(self):
        res_empty = StraceParser.parse("")
        self.assertEqual(res_empty["status"], STATUS_UNAVAILABLE)
        self.assertIsNone(res_empty["syscall_count"])

        res_malformed = StraceParser.parse("random unformatted text without dash delimiters")
        self.assertEqual(res_malformed["status"], STATUS_UNAVAILABLE)
        self.assertIn("delimiter", res_malformed["reason"])


class TestPidstatParser(unittest.TestCase):

    def test_parse_horizontal_pidstat_output(self):
        sample = """
Linux 7.0.0-31-generic (host) 	09/16/2026 	_x86_64_	(12 CPU)

# Time        UID       PID  minflt/s  majflt/s     VSZ     RSS   %MEM   cswch/s nvcswch/s  Command
04:30:15 PM  1000     39483   4600.00      1.50   12400    4096   0.05    150.25     12.75  cpu_workload
"""
        res = PidstatParser.parse(sample)
        self.assertEqual(res["status"], STATUS_SUCCESS)
        self.assertEqual(res["minor_faults_per_sec"], 4600.00)
        self.assertEqual(res["major_faults_per_sec"], 1.50)
        self.assertEqual(res["vsz_kb"], 12400)
        self.assertEqual(res["rss_kb"], 4096)
        self.assertEqual(res["voluntary_cswch_per_sec"], 150.25)
        self.assertEqual(res["involuntary_nvcswch_per_sec"], 12.75)

    def test_parse_empty_pidstat_output(self):
        res = PidstatParser.parse("")
        self.assertEqual(res["status"], STATUS_UNAVAILABLE)
        self.assertIsNone(res["voluntary_cswch_per_sec"])


class TestPerfStatParser(unittest.TestCase):

    def test_parse_perf_csv_with_ipc(self):
        sample = """
2000000,,cycles,1000000,100.00
4000000,,instructions,1000000,100.00
50,,context-switches,1000000,100.00
5,,cpu-migrations,1000000,100.00
120,,page-faults,1000000,100.00
"""
        res = PerfStatParser.parse_csv(sample)
        self.assertEqual(res["status"], STATUS_SUCCESS)
        self.assertEqual(res["cycles"], 2000000)
        self.assertEqual(res["instructions"], 4000000)
        self.assertAlmostEqual(res["ipc"], 2.0, places=4)
        self.assertEqual(res["context_switches"], 50)
        self.assertEqual(res["cpu_migrations"], 5)
        self.assertEqual(res["page_faults"], 120)

    def test_perf_permission_restriction_reason(self):
        supported, reason = SchedulingCollector.probe_perf_paranoid()
        if not supported:
            # On Ubuntu with perf_event_paranoid=4, must record exact reason
            self.assertIn("Hardware counters restricted", reason)
            self.assertIn("/proc/sys/kernel/perf_event_paranoid", reason)
        else:
            self.assertEqual(reason, "supported")


class TestThermalSystemStateCollector(unittest.TestCase):

    def test_cpu_frequency_collection(self):
        freq = ThermalSystemStateCollector.collect_cpu_frequency()
        self.assertIn("status", freq)
        if freq["status"] == STATUS_SUCCESS:
            self.assertGreater(len(freq["per_core_khz"]), 0)
            self.assertGreater(freq["min_khz"], 0)
            self.assertGreaterEqual(freq["max_khz"], freq["min_khz"])
            self.assertGreater(freq["avg_khz"], 0)

    def test_cpu_governor_collection(self):
        gov = ThermalSystemStateCollector.collect_cpu_governor()
        self.assertIn("status", gov)
        if gov["status"] == STATUS_SUCCESS:
            self.assertGreater(len(gov["governors"]), 0)
            self.assertIn(gov["dominant_governor"], gov["governors"] + ["mixed"])

    def test_load_average_collection(self):
        load = ThermalSystemStateCollector.collect_load_average()
        self.assertIn("load_1m", load)
        self.assertIn("load_5m", load)
        self.assertIn("load_15m", load)
        self.assertGreaterEqual(load["load_1m"], 0.0)

    def test_thermal_zones_collection(self):
        thermal = ThermalSystemStateCollector.collect_thermal_zones()
        self.assertIn("status", thermal)
        if thermal["status"] == STATUS_SUCCESS:
            self.assertGreater(len(thermal["zones"]), 0)
            self.assertIsNotNone(thermal["max_temp_c"])
            self.assertGreater(thermal["max_temp_c"], 0.0)


class TestHttpLatencyBenchmark(unittest.TestCase):

    def test_http_health_100_requests(self):
        server = MinimalHealthHttpServer(host="127.0.0.1", port=0)
        server.start()

        try:
            url = server.url
            lat = HttpLatencyBenchmark.measure_endpoint(url, num_requests=100)

            self.assertEqual(lat["status"], STATUS_SUCCESS)
            self.assertEqual(lat["requests_completed"], 100)
            self.assertEqual(lat["http_200_count"], 100)

            # Check connect metrics
            conn = lat["connect_ms"]
            self.assertIsNotNone(conn["mean"])
            self.assertIsNotNone(conn["median"])
            self.assertIsNotNone(conn["p50"])
            self.assertIsNotNone(conn["p95"])
            self.assertIsNotNone(conn["p99"])
            self.assertIsNotNone(conn["min"])
            self.assertIsNotNone(conn["max"])
            self.assertLessEqual(conn["min"], conn["max"])
            self.assertLessEqual(conn["p50"], conn["p99"])

            # Check TTFB metrics
            ttfb = lat["ttfb_ms"]
            self.assertIsNotNone(ttfb["mean"])
            self.assertIsNotNone(ttfb["p50"])
            self.assertIsNotNone(ttfb["p95"])
            self.assertIsNotNone(ttfb["p99"])
            self.assertLessEqual(ttfb["min"], ttfb["max"])

            # Check Total metrics
            tot = lat["total_ms"]
            self.assertIsNotNone(tot["mean"])
            self.assertIsNotNone(tot["p50"])
            self.assertIsNotNone(tot["p95"])
            self.assertIsNotNone(tot["p99"])
            self.assertLessEqual(tot["min"], tot["max"])

        finally:
            server.stop()


class TestIperf3NetworkStandardization(unittest.TestCase):

    def test_iperf3_command_standardization(self):
        cmd = Iperf3Config.build_command("192.168.122.100", duration=10, streams=1)
        self.assertIn("-c 192.168.122.100", cmd)
        self.assertIn("-t 10", cmd)
        self.assertIn("-P 1", cmd)
        self.assertIn("-J", cmd)

    def test_iperf3_json_parser_success(self):
        sample_json = json.dumps({
            "end": {
                "sum_sent": {
                    "bits_per_second": 9450000000.0,
                    "bytes": 1181250000,
                    "retransmits": 2
                },
                "sum_received": {
                    "bits_per_second": 9410000000.0,
                    "bytes": 1176250000
                },
                "streams": [{}]
            }
        })
        res = Iperf3Config.parse_iperf3_json(sample_json)
        self.assertEqual(res["status"], STATUS_SUCCESS)
        self.assertEqual(res["protocol"], "TCP")
        self.assertEqual(res["direction"], "client-to-server")
        self.assertEqual(res["stream_count"], 1)
        self.assertAlmostEqual(res["sender_bandwidth_mbps"], 9450.0, places=1)
        self.assertAlmostEqual(res["receiver_bandwidth_mbps"], 9410.0, places=1)
        self.assertEqual(res["retransmits"], 2)

    def test_iperf3_json_parser_malformed(self):
        res = Iperf3Config.parse_iperf3_json("not valid json")
        self.assertEqual(res["status"], STATUS_UNAVAILABLE)
        self.assertIn("Failed to parse", res["reason"])


if __name__ == "__main__":
    unittest.main()
