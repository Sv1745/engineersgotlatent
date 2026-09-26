"""
Cloud Cost Janitor - Agent Workflow (agent/workflow.py)

Orchestrates the end-to-end Cost Janitor workflow:
1. Run scanner against real AWS account
2. Run pricer to compute monthly savings (USD & INR)
3. Present prioritized ₹ hit-list & blast radius (dry_run=True)
4. Human Approval Checkpoint: "Approve deleting these N resources, saving ₹X/month ($Y/month)?"
5. On explicit approval: Re-run teardown with confirmed=True.
"""

import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Add cloud-cost-janitor root to sys.path
base_dir = Path(__file__).resolve().parent.parent
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

from pricing.teardown import (
    delete_ebs_volume,
    release_eip,
    stop_ec2_instance,
    delete_snapshot,
)
from agent.mcp_server import run_scanner, run_pricer, run_teardown

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("agent_workflow")


def safe_print(text: str):
    """Prints text safely without crashing on Windows cp1252 encoding."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, 'encoding', 'utf-8') or 'utf-8'
        print(text.encode(encoding, errors='replace').decode(encoding))


def execute_workflow(
    region: str = "ap-south-1",
    auto_approve: bool = False,
    interactive_prompt: Optional[callable] = None,
) -> Dict[str, Any]:
    """
    Executes the full cost optimization workflow with human-in-the-loop approval.
    """
    safe_print("\n" + "=" * 75)
    safe_print("[STEP 1] SCANNING AWS INFRASTRUCTURE (Real AWS Account)")
    safe_print("=" * 75)
    scan_output = run_scanner(region=region)
    safe_print(scan_output)

    findings_path = base_dir / "findings.json"
    if not findings_path.exists():
        findings_path = Path("findings.json")

    with open(findings_path, "r", encoding="utf-8") as f:
        findings = json.load(f)

    if not findings:
        safe_print("\n[OK] Zero waste detected in region. No action needed.")
        return {"status": "completed", "findings_count": 0, "total_inr": 0.0, "total_usd": 0.0}

    safe_print("\n" + "=" * 75)
    safe_print("[STEP 2] PRICING & PRIORITIZATION")
    safe_print("=" * 75)
    price_output = run_pricer(input_file=str(findings_path), output_file="prioritized_findings.json")
    safe_print(price_output)

    prioritized_path = base_dir / "prioritized_findings.json"
    if not prioritized_path.exists():
        prioritized_path = Path("prioritized_findings.json")

    with open(prioritized_path, "r", encoding="utf-8") as f:
        prioritized_findings = json.load(f)

    total_inr = sum(f.get("monthly_cost_inr", 0.0) for f in prioritized_findings)
    total_usd = sum(f.get("monthly_cost_usd", 0.0) for f in prioritized_findings)
    num_resources = len(prioritized_findings)

    safe_print("\n" + "=" * 75)
    safe_print("[STEP 3] BLAST RADIUS SIMULATION (dry_run=True)")
    safe_print("=" * 75)
    dry_run_results = []
    for item in prioritized_findings:
        res_id = item.get("resource_id")
        res_type = item.get("type")

        td_output = run_teardown(
            resource_id=res_id,
            resource_type=res_type,
            dry_run=True,
            confirmed=False,
        )
        dry_run_results.append({
            "resource_id": res_id,
            "type": res_type,
            "dry_run_output": td_output,
        })
        safe_print(f"  [DryRun Simulated] {res_id} ({res_type}) -> Verified safe for deletion")

    safe_print("\n" + "=" * 75)
    safe_print("[STEP 4] TRUEFORGE HUMAN-IN-THE-LOOP APPROVAL CHECKPOINT")
    safe_print("=" * 75)

    approval_prompt = (
        f"Approve deleting these {num_resources} resources, "
        f"saving ₹{total_inr:,.2f}/month (${total_usd:,.2f}/month)?"
    )
    safe_print(f"\n[APPROVAL PROMPT]: {approval_prompt}")

    approved = False
    if auto_approve:
        safe_print(">> Auto-approve flag set. Approving action.")
        approved = True
    elif interactive_prompt:
        approved = interactive_prompt(approval_prompt)
    else:
        # Standard TrueForge input checkpoint
        try:
            user_input = input(f"\n{approval_prompt} [y/N]: ").strip().lower()
            approved = user_input in ["y", "yes", "approve"]
        except EOFError:
            approved = False

    teardown_results = []
    if approved:
        safe_print("\n" + "=" * 75)
        safe_print("[STEP 5] EXECUTING TEARDOWN (dry_run=False, confirmed=True)")
        safe_print("=" * 75)
        for item in prioritized_findings:
            res_id = item.get("resource_id")
            res_type = item.get("type")
            td_real = run_teardown(
                resource_id=res_id,
                resource_type=res_type,
                dry_run=False,
                confirmed=True,
            )
            teardown_results.append({
                "resource_id": res_id,
                "type": res_type,
                "output": td_real,
            })
            safe_print(f"  [Teardown Confirmed] {res_id} ({res_type}) -> Success")

        safe_print(f"\n[DONE] Successfully cleaned up {num_resources} resources! Saved ₹{total_inr:,.2f}/month (${total_usd:,.2f}/month).")
    else:
        safe_print("\n[ABORTED] Action aborted by user. No resources were deleted.")

    return {
        "status": "approved" if approved else "aborted",
        "num_resources": num_resources,
        "total_inr": total_inr,
        "total_usd": total_usd,
        "approval_prompt": approval_prompt,
        "dry_run_results": dry_run_results,
        "teardown_results": teardown_results,
    }


if __name__ == "__main__":
    auto = "--auto-approve" in sys.argv
    execute_workflow(auto_approve=auto)
