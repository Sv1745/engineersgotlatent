"""
Verification Script for Cloud Cost Janitor Pricing & Teardown

Runs the 3 required verification steps:
1. Run pricer.py against shared/sample_findings.json, confirm output matches
   prioritized_findings.json schema and is sorted descending by cost.
2. Call each teardown.py function with dry_run=True against a real/seeded demo
   resource ID, confirm it reports what WOULD happen without changing anything in AWS.
3. Call each teardown.py function against a resource lacking the demo tag,
   confirm it refuses instead of proceeding.
Prints pass/fail per check.
"""

import json
import sys
from pathlib import Path

# Add cloud-cost-janitor root to sys.path
cloud_cost_janitor_dir = Path(__file__).resolve().parent.parent
if str(cloud_cost_janitor_dir) not in sys.path:
    sys.path.insert(0, str(cloud_cost_janitor_dir))

from pricing.pricer import prioritize_findings, run_pricer
from pricing.teardown import (
    delete_ebs_volume,
    release_eip,
    stop_ec2_instance,
    delete_snapshot
)


def verify_check_1():
    print("\n--- [CHECK 1] Verify pricer.py Output Schema and Descending Sorting ---")
    sample_file = cloud_cost_janitor_dir / "shared" / "sample_findings.json"
    output_file = cloud_cost_janitor_dir / "shared" / "sample_prioritized_findings.json"

    try:
        prioritized = run_pricer(str(sample_file), str(output_file))

        # Check required schema fields for findings.json + prioritized fields
        required_fields = {
            "resource_id", "type", "region", "reason",
            "created_date", "tags", "monthly_cost_usd", "monthly_cost_inr"
        }

        for idx, item in enumerate(prioritized):
            missing = required_fields - set(item.keys())
            if missing:
                print(f"FAILED: Entry {idx} missing required fields: {missing}")
                return False

            if not isinstance(item["monthly_cost_usd"], (int, float)):
                print(f"FAILED: Entry {idx} monthly_cost_usd is not a number")
                return False

            if not isinstance(item["monthly_cost_inr"], (int, float)):
                print(f"FAILED: Entry {idx} monthly_cost_inr is not a number")
                return False

        # Verify descending order by monthly_cost_inr
        inr_costs = [item["monthly_cost_inr"] for item in prioritized]
        is_sorted = inr_costs == sorted(inr_costs, reverse=True)

        if not is_sorted:
            print(f"FAILED: Output array is not sorted descending by monthly_cost_inr: {inr_costs}")
            return False

        print(f"  Schema Valid: YES ({len(prioritized)} entries checked)")
        print(f"  Sorted Descending by Cost (INR): YES ({inr_costs})")
        return True

    except Exception as e:
        print(f"FAILED with exception: {e}")
        return False


def verify_check_2():
    print("\n--- [CHECK 2] Call teardown.py functions with dry_run=True on Demo Resources ---")
    demo_tags = {"Environment": "hackathon-demo"}
    resources = [
        ("delete_ebs_volume", delete_ebs_volume, "vol-0f123456789abcdef"),
        ("release_eip", release_eip, "eipalloc-0a1b2c3d4e5f67890"),
        ("stop_ec2_instance", stop_ec2_instance, "i-0987654321fedcba0"),
        ("delete_snapshot", delete_snapshot, "snap-01234567898765432")
    ]

    all_passed = True
    for name, func, res_id in resources:
        try:
            res = func(res_id, tags=demo_tags, dry_run=True)
            if res.get("dry_run") is True or res.get("status") in ("dry_run_success", "simulated_success"):
                print(f"  [PASS] {name}({res_id}, dry_run=True) -> Reported dry_run status: {res.get('status')}")
            else:
                print(f"  [FAIL] {name}({res_id}, dry_run=True) -> Unexpected result: {res}")
                all_passed = False
        except Exception as e:
            print(f"  [FAIL] {name}({res_id}, dry_run=True) -> Unexpected exception: {e}")
            all_passed = False

    return all_passed


def verify_check_3():
    print("\n--- [CHECK 3] Call teardown.py functions on Resources Lacking Demo Tag ---")
    invalid_tags_list = [
        {"Environment": "production"},
        {"Project": "CloudCostJanitor"},
        {},
        None
    ]

    resources = [
        ("delete_ebs_volume", delete_ebs_volume, "vol-0f123456789abcdef"),
        ("release_eip", release_eip, "eipalloc-0a1b2c3d4e5f67890"),
        ("stop_ec2_instance", stop_ec2_instance, "i-0987654321fedcba0"),
        ("delete_snapshot", delete_snapshot, "snap-01234567898765432")
    ]

    all_passed = True
    for (name, func, res_id), inv_tags in zip(resources, invalid_tags_list):
        try:
            func(res_id, tags=inv_tags, dry_run=True)
            print(f"  [FAIL] {name}({res_id}, tags={inv_tags}) -> Did NOT raise PermissionError!")
            all_passed = False
        except PermissionError as pe:
            print(f"  [PASS] {name}({res_id}, tags={inv_tags}) -> Properly refused action: {pe}")
        except Exception as e:
            print(f"  [FAIL] {name}({res_id}, tags={inv_tags}) -> Raised wrong exception: {type(e).__name__}: {e}")
            all_passed = False

    return all_passed


def main():
    print("=" * 80)
    print("      CLOUD COST JANITOR - PRICING & TEARDOWN VERIFICATION SUITE")
    print("=" * 80)

    pass1 = verify_check_1()
    pass2 = verify_check_2()
    pass3 = verify_check_3()

    print("\n" + "=" * 80)
    print("SUMMARY OF VERIFICATION RESULTS:")
    print("=" * 80)
    print(f"Check 1 (Pricer Schema & Descending Cost Sort) : {'PASS' if pass1 else 'FAIL'}")
    print(f"Check 2 (Teardown DryRun Reports What Would Happen): {'PASS' if pass2 else 'FAIL'}")
    print(f"Check 3 (Teardown Refuses Resources Lacking Tag)  : {'PASS' if pass3 else 'FAIL'}")
    print("=" * 80)

    if pass1 and pass2 and pass3:
        print("ALL CHECKS PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("ONE OR MORE CHECKS FAILED!")
        sys.exit(1)


if __name__ == "__main__":
    main()
