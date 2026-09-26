"""
Unit and integration tests for agent workflow & TrueForge approval checkpoint
"""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

base_dir = Path(__file__).resolve().parent.parent
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

from agent.workflow import execute_workflow


class TestAgentWorkflow(unittest.TestCase):

    def test_workflow_gating_abort(self):
        """Verify that when human rejects the prompt, no real teardown occurs."""
        result = execute_workflow(
            region="ap-south-1",
            auto_approve=False,
            interactive_prompt=lambda prompt: False,  # Simulates human saying NO
        )

        self.assertEqual(result["status"], "aborted")
        self.assertEqual(len(result["teardown_results"]), 0)
        self.assertIn("Approve deleting these", result["approval_prompt"])
        self.assertIn("saving ₹", result["approval_prompt"])
        self.assertIn("/month", result["approval_prompt"])
        self.assertGreater(result["total_inr"], 0)
        self.assertGreater(result["total_usd"], 0)

    def test_workflow_gating_approval(self):
        """Verify that when human explicitly approves, teardown executes with confirmed=True."""
        result = execute_workflow(
            region="ap-south-1",
            auto_approve=False,
            interactive_prompt=lambda prompt: True,  # Simulates human saying YES
        )

        self.assertEqual(result["status"], "approved")
        self.assertEqual(len(result["teardown_results"]), result["num_resources"])
        self.assertGreater(result["num_resources"], 0)
        self.assertGreater(result["total_inr"], 0)


if __name__ == "__main__":
    unittest.main()
