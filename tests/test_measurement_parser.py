#!/usr/bin/env python3
"""
test_measurement_parser.py - Unit tests for measurement engine telemetry parsing.
Verifies:
- /usr/bin/time -v output parsing
- wall clock format parsing (s.ss, m:ss.ss, h:mm:ss.ss)
- perf CSV parsing
- handling of missing or restricted perf (status=unavailable, no fabricated values)
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from collector.measurement import (
    parse_time_v_output,
    parse_wall_clock_time,
    parse_perf_csv_output,
    MeasurementEngine
)

class TestMeasurementParser(unittest.TestCase):

    def test_parse_wall_clock_time(self):
        self.assertAlmostEqual(parse_wall_clock_time("0:00.05"), 0.05)
        self.assertAlmostEqual(parse_wall_clock_time("1:23.45"), 83.45)
        self.assertAlmostEqual(parse_wall_clock_time("1:02:03.45"), 3723.45)
        self.assertAlmostEqual(parse_wall_clock_time("45.67"), 45.67)
        self.assertIsNone(parse_wall_clock_time(""))
        self.assertIsNone(parse_wall_clock_time(None))

    def test_parse_time_v_output(self):
        sample_time_v = """
\tCommand being timed: "cpu_workload"
\tUser time (seconds): 1.25
\tSystem time (seconds): 0.15
\tPercent of CPU this job got: 98%
\tElapsed (wall clock) time (h:mm:ss or m:ss): 0:01.43
\tMaximum resident set size (kbytes): 4096
\tAverage total size (kbytes): 12000
\tMinor (reclaiming a frame) page faults: 312
\tMajor (requiring I/O) page faults: 2
\tVoluntary context switches: 15
\tInvoluntary context switches: 4
\tExit status: 0
"""
        res = parse_time_v_output(sample_time_v)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["user_time_sec"], 1.25)
        self.assertEqual(res["system_time_sec"], 0.15)
        self.assertEqual(res["cpu_percentage"], 98.0)
        self.assertAlmostEqual(res["wall_time_sec"], 1.43)
        self.assertEqual(res["max_rss_kb"], 4096)
        self.assertEqual(res["vsz_kb"], 12000)
        self.assertEqual(res["minor_page_faults"], 312)
        self.assertEqual(res["major_page_faults"], 2)
        self.assertEqual(res["total_page_faults"], 314)
        self.assertEqual(res["voluntary_context_switches"], 15)
        self.assertEqual(res["involuntary_context_switches"], 4)
        self.assertEqual(res["total_context_switches"], 19)
        self.assertEqual(res["exit_code"], 0)

    def test_perf_unavailable_never_fabricates_zeros(self):
        """When perf is unavailable, counters must be None and status unavailable."""
        res = parse_perf_csv_output("")
        self.assertEqual(res["status"], "unavailable")
        self.assertIsNone(res["cycles"])
        self.assertIsNone(res["instructions"])
        self.assertIsNone(res["context_switches"])

    def test_parse_perf_csv_output(self):
        sample_perf = """
1234567,,cycles,1000000,100.00
543210,,instructions,1000000,100.00
42,,context-switches,1000000,100.00
3,,cpu-migrations,1000000,100.00
15,,page-faults,1000000,100.00
"""
        res = parse_perf_csv_output(sample_perf)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["cycles"], 1234567)
        self.assertEqual(res["instructions"], 543210)
        self.assertEqual(res["context_switches"], 42)
        self.assertEqual(res["cpu_migrations"], 3)
        self.assertEqual(res["page_faults"], 15)

if __name__ == "__main__":
    unittest.main()
