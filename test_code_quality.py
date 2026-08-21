"""Regression tests for the final static code-quality audit."""

import unittest

from review_code_quality import audit_code_quality


class CodeQualityTests(unittest.TestCase):
    def test_static_project_audit_passes(self):
        report = audit_code_quality(write_report=False)
        self.assertEqual(report["status"], "pass", report["details"])
        self.assertTrue(all(report["checks"].values()))


if __name__ == "__main__":
    unittest.main()
