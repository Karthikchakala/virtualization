#!/usr/bin/env python3
"""
test_statistics.py - Unit tests for statistical engine.
Verifies:
- mean, median, min, max
- sample standard deviation
- coefficient of variation
- percentiles p50, p95, p99
- missing values handling (strictly preserving None, never converting to 0)
- empty / all-null inputs
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from analysis.statistics_engine import (
    compute_statistics,
    calculate_percentile,
    aggregate_benchmark_results
)

class TestStatisticsEngine(unittest.TestCase):

    def test_basic_statistics(self):
        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        stats = compute_statistics(vals)

        self.assertEqual(stats["total_count"], 5)
        self.assertEqual(stats["valid_count"], 5)
        self.assertEqual(stats["missing_count"], 0)
        self.assertEqual(stats["mean"], 30.0)
        self.assertEqual(stats["median"], 30.0)
        self.assertEqual(stats["min"], 10.0)
        self.assertEqual(stats["max"], 50.0)
        self.assertAlmostEqual(stats["stdev"], 15.811388, places=4)
        self.assertAlmostEqual(stats["cv_percent"], 52.7046, places=2)
        self.assertEqual(stats["p50"], 30.0)

    def test_percentiles(self):
        # 100 values: 1..100
        vals = list(range(1, 101))
        self.assertEqual(calculate_percentile(vals, 50.0), 50.5)
        self.assertAlmostEqual(calculate_percentile(vals, 95.0), 95.05)
        self.assertAlmostEqual(calculate_percentile(vals, 99.0), 99.01)

    def test_missing_values_never_converted_to_zero(self):
        # List containing missing / None values
        vals = [10.0, None, 20.0, None, 30.0]
        stats = compute_statistics(vals)

        self.assertEqual(stats["total_count"], 5)
        self.assertEqual(stats["valid_count"], 3)
        self.assertEqual(stats["missing_count"], 2)
        self.assertEqual(stats["mean"], 20.0)  # (10+20+30)/3 = 20.0. NOT (10+0+20+0+30)/5 = 12.0!
        self.assertEqual(stats["min"], 10.0)   # NOT 0.0!
        self.assertEqual(stats["max"], 30.0)

    def test_all_missing_values(self):
        vals = [None, None, None]
        stats = compute_statistics(vals)

        self.assertEqual(stats["total_count"], 3)
        self.assertEqual(stats["valid_count"], 0)
        self.assertEqual(stats["missing_count"], 3)
        self.assertIsNone(stats["mean"])
        self.assertIsNone(stats["median"])
        self.assertIsNone(stats["min"])
        self.assertIsNone(stats["max"])
        self.assertIsNone(stats["stdev"])
        self.assertIsNone(stats["cv_percent"])
        self.assertIsNone(stats["p50"])
        self.assertIsNone(stats["p95"])
        self.assertIsNone(stats["p99"])

    def test_single_value(self):
        vals = [42.0]
        stats = compute_statistics(vals)
        self.assertEqual(stats["valid_count"], 1)
        self.assertEqual(stats["mean"], 42.0)
        self.assertEqual(stats["stdev"], 0.0)
        self.assertEqual(stats["cv_percent"], 0.0)
        self.assertEqual(stats["p50"], 42.0)

if __name__ == "__main__":
    unittest.main()
