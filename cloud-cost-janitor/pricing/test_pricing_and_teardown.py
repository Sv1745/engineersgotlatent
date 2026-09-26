"""
Unit tests for pricer.py and teardown.py
"""

import json
import sys
import unittest
from pathlib import Path

# Ensure cloud-cost-janitor root directory is on sys.path
cloud_cost_janitor_dir = Path(__file__).resolve().parent.parent
if str(cloud_cost_janitor_dir) not in sys.path:
    sys.path.insert(0, str(cloud_cost_janitor_dir))

from pricing.pricer import prioritize_findings, generate_report, run_pricer
from pricing.teardown import (
    delete_ebs_volume,
    release_eip,
    stop_ec2_instance,
    delete_snapshot,
    verify_safety_tags
)


class TestPricingAndTeardown(unittest.TestCase):

    def setUp(self):
        self.sample_findings_path = cloud_cost_janitor_dir / "shared" / "sample_findings.json"
        self.valid_tags = {"Environment": "hackathon-demo"}
        self.invalid_tags = {"Environment": "production"}

    def test_pricer_prioritize_and_sort(self):
        with open(self.sample_findings_path, "r", encoding="utf-8") as f:
            findings = json.load(f)

        prioritized = prioritize_findings(findings, inr_per_usd=95.83)
        self.assertEqual(len(prioritized), len(findings))

        # Check descending order by monthly_cost_inr
        costs = [item["monthly_cost_inr"] for item in prioritized]
        self.assertEqual(costs, sorted(costs, reverse=True))

        # Check required fields present
        for item in prioritized:
            self.assertIn("monthly_cost_usd", item)
            self.assertIn("monthly_cost_inr", item)
            self.assertGreater(item["monthly_cost_usd"], 0)
            self.assertGreater(item["monthly_cost_inr"], 0)

    def test_generate_report(self):
        with open(self.sample_findings_path, "r", encoding="utf-8") as f:
            findings = json.load(f)
        report = generate_report(findings)
        self.assertIn("CLOUD COST JANITOR", report)
        self.assertIn("MONTHLY WASTE HIT-LIST", report)
        self.assertIn("TOTAL ESTIMATED MONTHLY WASTE", report)

    def test_teardown_safety_tag_check(self):
        # Valid tag should pass
        self.assertTrue(verify_safety_tags("vol-123", self.valid_tags))

        # Invalid or missing tags should raise PermissionError
        with self.assertRaises(PermissionError):
            delete_ebs_volume("vol-123", tags=self.invalid_tags, dry_run=True)

        with self.assertRaises(PermissionError):
            release_eip("eipalloc-123", tags={}, dry_run=True)

    def test_teardown_confirmation_flag(self):
        # dry_run=False without confirmed=True should raise ValueError
        with self.assertRaises(ValueError):
            delete_ebs_volume("vol-123", tags=self.valid_tags, dry_run=False, confirmed=False)

        with self.assertRaises(ValueError):
            stop_ec2_instance("i-123", tags=self.valid_tags, dry_run=False, confirmed=False)

    def test_teardown_dry_run_default(self):
        res_ebs = delete_ebs_volume("vol-0f123456789abcdef", tags=self.valid_tags)
        self.assertTrue(res_ebs.get("dry_run"))

        res_eip = release_eip("eipalloc-0a1b2c3d4e5f67890", tags=self.valid_tags)
        self.assertTrue(res_eip.get("dry_run"))

        res_ec2 = stop_ec2_instance("i-0987654321fedcba0", tags=self.valid_tags)
        self.assertTrue(res_ec2.get("dry_run"))

        res_snap = delete_snapshot("snap-01234567898765432", tags=self.valid_tags)
        self.assertTrue(res_snap.get("dry_run"))

    def test_teardown_confirmed_execution(self):
        res_ebs = delete_ebs_volume("vol-0f123456789abcdef", tags=self.valid_tags, dry_run=False, confirmed=True)
        self.assertFalse(res_ebs.get("dry_run"))
        self.assertTrue(res_ebs.get("confirmed"))


if __name__ == "__main__":
    unittest.main()
