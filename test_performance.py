"""Regression test for TODO 34 measured responsiveness limits."""

import unittest

from measure_performance import measure_performance


class PerformanceTests(unittest.TestCase):
    def test_measured_runtime_stays_within_declared_limits(self):
        report = measure_performance()
        self.assertTrue(report["summary"]["passed"], report["checks"])
        self.assertEqual(report["summary"]["checks_passed"], report["summary"]["checks_total"])


if __name__ == "__main__":
    unittest.main()
