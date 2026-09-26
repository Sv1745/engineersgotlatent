"""
Cloud Cost Janitor - Teardown Module (pricing/teardown.py)

Provides teardown functions with safety controls:
1. Hard-coded safety check enforcing required {DEMO_TAG_KEY: DEMO_TAG_VALUE} tag.
2. Default dry_run=True utilizing AWS's native DryRun API parameter.
3. Explicit confirmed=True flag required for real execution when dry_run=False.
"""

import os
import sys
from pathlib import Path

# Try importing boto3, handle graceful fallback if not installed or without credentials
try:
    import boto3
    from botocore.exceptions import ClientError, BotoCoreError
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False
    ClientError = Exception
    BotoCoreError = Exception


def load_env_vars():
    """Parse .env or .env.example into os.environ if not present."""
    search_dirs = [Path.cwd(), Path(__file__).resolve().parent.parent]
    for directory in search_dirs:
        for env_filename in [".env", ".env.example"]:
            env_path = directory / env_filename
            if env_path.exists():
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, _, val = line.partition("=")
                            key = key.strip()
                            val = val.strip().strip("'\"")
                            if key and key not in os.environ:
                                os.environ[key] = val


def verify_safety_tags(resource_id, tags=None):
    """
    Safety check: Refuses to act on any resource without tag {DEMO_TAG_KEY: DEMO_TAG_VALUE}.
    Raises PermissionError if safety check fails.
    """
    load_env_vars()
    demo_tag_key = os.environ.get("DEMO_TAG_KEY") or "Environment"
    demo_tag_value = os.environ.get("DEMO_TAG_VALUE") or "hackathon-demo"

    if tags is None:
        tags = {}

    matching_value = tags.get(demo_tag_key)
    if matching_value != demo_tag_value:
        raise PermissionError(
            f"SAFETY CHECK FAILED: Refusing action on resource '{resource_id}'. "
            f"Required safety tag '{demo_tag_key}': '{demo_tag_value}' was not found. "
            f"Resource tags: {tags}"
        )
    return True


def _validate_execution_flags(resource_id, dry_run, confirmed):
    """
    Verifies that if dry_run=False, confirmed=True must be explicitly passed.
    """
    if not dry_run and not confirmed:
        raise ValueError(
            f"EXECUTION REFUSED: Action on '{resource_id}' specifies dry_run=False "
            f"but confirmed=False. Set confirmed=True explicitly to execute real teardown."
        )


def delete_ebs_volume(resource_id, tags=None, dry_run=True, confirmed=False, region="ap-south-1"):
    """
    Delete an unattached EBS volume.
    Defaults to dry_run=True. Requires tag validation and confirmed=True for real action.
    """
    verify_safety_tags(resource_id, tags)
    _validate_execution_flags(resource_id, dry_run, confirmed)

    action_desc = "DRY RUN Delete EBS Volume" if dry_run else "REAL Teardown Delete EBS Volume"
    print(f"[{action_desc}] Target: {resource_id} (Region: {region})")

    if HAS_BOTO3:
        try:
            client = boto3.client("ec2", region_name=region)
            response = client.delete_volume(VolumeId=resource_id, DryRun=dry_run)
            return {"status": "success", "dry_run": dry_run, "confirmed": confirmed, "response": response}
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "DryRunOperation":
                print(f"[AWS DryRun Success] Volume {resource_id} delete_volume DryRun passed.")
                return {"status": "dry_run_success", "dry_run": True, "resource_id": resource_id}
            print(f"[AWS API Response/Error] {e}")
            return {"status": "api_error", "error": str(e), "dry_run": dry_run}
        except Exception as e:
            print(f"[AWS Connection Warning] {e}. Falling back to simulation mode.")

    return {
        "status": "simulated_success",
        "action": "delete_ebs_volume",
        "resource_id": resource_id,
        "dry_run": dry_run,
        "confirmed": confirmed
    }


def release_eip(resource_id, tags=None, dry_run=True, confirmed=False, region="ap-south-1"):
    """
    Release an unassociated Elastic IP.
    Defaults to dry_run=True. Requires tag validation and confirmed=True for real action.
    """
    verify_safety_tags(resource_id, tags)
    _validate_execution_flags(resource_id, dry_run, confirmed)

    action_desc = "DRY RUN Release Elastic IP" if dry_run else "REAL Teardown Release Elastic IP"
    print(f"[{action_desc}] Target: {resource_id} (Region: {region})")

    if HAS_BOTO3:
        try:
            client = boto3.client("ec2", region_name=region)
            if resource_id.startswith("eipalloc-"):
                response = client.release_address(AllocationId=resource_id, DryRun=dry_run)
            else:
                response = client.release_address(PublicIp=resource_id, DryRun=dry_run)
            return {"status": "success", "dry_run": dry_run, "confirmed": confirmed, "response": response}
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "DryRunOperation":
                print(f"[AWS DryRun Success] EIP {resource_id} release_address DryRun passed.")
                return {"status": "dry_run_success", "dry_run": True, "resource_id": resource_id}
            print(f"[AWS API Response/Error] {e}")
            return {"status": "api_error", "error": str(e), "dry_run": dry_run}
        except Exception as e:
            print(f"[AWS Connection Warning] {e}. Falling back to simulation mode.")

    return {
        "status": "simulated_success",
        "action": "release_eip",
        "resource_id": resource_id,
        "dry_run": dry_run,
        "confirmed": confirmed
    }


def stop_ec2_instance(resource_id, tags=None, dry_run=True, confirmed=False, region="ap-south-1"):
    """
    Stop an idle EC2 instance.
    Defaults to dry_run=True. Requires tag validation and confirmed=True for real action.
    """
    verify_safety_tags(resource_id, tags)
    _validate_execution_flags(resource_id, dry_run, confirmed)

    action_desc = "DRY RUN Stop EC2 Instance" if dry_run else "REAL Teardown Stop EC2 Instance"
    print(f"[{action_desc}] Target: {resource_id} (Region: {region})")

    if HAS_BOTO3:
        try:
            client = boto3.client("ec2", region_name=region)
            response = client.stop_instances(InstanceIds=[resource_id], DryRun=dry_run)
            return {"status": "success", "dry_run": dry_run, "confirmed": confirmed, "response": response}
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "DryRunOperation":
                print(f"[AWS DryRun Success] Instance {resource_id} stop_instances DryRun passed.")
                return {"status": "dry_run_success", "dry_run": True, "resource_id": resource_id}
            print(f"[AWS API Response/Error] {e}")
            return {"status": "api_error", "error": str(e), "dry_run": dry_run}
        except Exception as e:
            print(f"[AWS Connection Warning] {e}. Falling back to simulation mode.")

    return {
        "status": "simulated_success",
        "action": "stop_ec2_instance",
        "resource_id": resource_id,
        "dry_run": dry_run,
        "confirmed": confirmed
    }


def delete_snapshot(resource_id, tags=None, dry_run=True, confirmed=False, region="ap-south-1"):
    """
    Delete an orphaned EBS snapshot.
    Defaults to dry_run=True. Requires tag validation and confirmed=True for real action.
    """
    verify_safety_tags(resource_id, tags)
    _validate_execution_flags(resource_id, dry_run, confirmed)

    action_desc = "DRY RUN Delete Snapshot" if dry_run else "REAL Teardown Delete Snapshot"
    print(f"[{action_desc}] Target: {resource_id} (Region: {region})")

    if HAS_BOTO3:
        try:
            client = boto3.client("ec2", region_name=region)
            response = client.delete_snapshot(SnapshotId=resource_id, DryRun=dry_run)
            return {"status": "success", "dry_run": dry_run, "confirmed": confirmed, "response": response}
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "DryRunOperation":
                print(f"[AWS DryRun Success] Snapshot {resource_id} delete_snapshot DryRun passed.")
                return {"status": "dry_run_success", "dry_run": True, "resource_id": resource_id}
            print(f"[AWS API Response/Error] {e}")
            return {"status": "api_error", "error": str(e), "dry_run": dry_run}
        except Exception as e:
            print(f"[AWS Connection Warning] {e}. Falling back to simulation mode.")

    return {
        "status": "simulated_success",
        "action": "delete_snapshot",
        "resource_id": resource_id,
        "dry_run": dry_run,
        "confirmed": confirmed
    }
