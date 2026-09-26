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
    search_dirs = [Path.cwd(), Path(__file__).resolve().parent.parent, Path(__file__).resolve().parent]
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

# Ensure env vars are loaded upon module import
load_env_vars()



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


def fetch_resource_tags(resource_id, resource_type, region="ap-south-1"):
    """
    Fetches live tags from AWS for a given resource if not provided.
    """
    if not HAS_BOTO3:
        return {}
    try:
        client = boto3.client("ec2", region_name=region)
        if resource_type in ["ec2_instance", "instance"] or resource_id.startswith("i-"):
            res = client.describe_instances(InstanceIds=[resource_id])
            tags_list = res["Reservations"][0]["Instances"][0].get("Tags", [])
            return {t["Key"]: t["Value"] for t in tags_list}
        elif resource_type in ["ebs_volume", "volume"] or resource_id.startswith("vol-"):
            res = client.describe_volumes(VolumeIds=[resource_id])
            tags_list = res["Volumes"][0].get("Tags", [])
            return {t["Key"]: t["Value"] for t in tags_list}
        elif resource_type in ["elastic_ip", "eip"] or resource_id.startswith("eipalloc-"):
            res = client.describe_addresses(AllocationIds=[resource_id])
            tags_list = res["Addresses"][0].get("Tags", [])
            return {t["Key"]: t["Value"] for t in tags_list}
        elif resource_type in ["snapshot", "ebs_snapshot"] or resource_id.startswith("snap-"):
            res = client.describe_snapshots(SnapshotIds=[resource_id])
            tags_list = res["Snapshots"][0].get("Tags", [])
            return {t["Key"]: t["Value"] for t in tags_list}
    except Exception as e:
        print(f"[Tag Fetch Warning] Could not fetch tags for {resource_id}: {e}")
    return {}


def delete_ebs_volume(resource_id, tags=None, dry_run=True, confirmed=False, region="ap-south-1"):
    """
    Delete an unattached EBS volume.
    Defaults to dry_run=True. Requires tag validation and confirmed=True for real action.
    """
    if not tags:
        tags = fetch_resource_tags(resource_id, "ebs_volume", region)
    verify_safety_tags(resource_id, tags)
    _validate_execution_flags(resource_id, dry_run, confirmed)

    action_desc = "DRY RUN Delete EBS Volume" if dry_run else "REAL Teardown Delete EBS Volume"
    print(f"[{action_desc}] Target: {resource_id} (Region: {region})")

    if HAS_BOTO3:
        try:
            client = boto3.client("ec2", region_name=region)
            response = client.delete_volume(VolumeId=resource_id, DryRun=dry_run)
            return {"status": "success", "dry_run": dry_run, "confirmed": confirmed, "resource_id": resource_id, "response": response}
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "DryRunOperation":
                print(f"[AWS DryRun Success] Volume {resource_id} delete_volume DryRun passed.")
                return {"status": "dry_run_success", "dry_run": True, "resource_id": resource_id}
            print(f"[AWS API Response/Error] {e}")
            return {"status": "api_error", "error": str(e), "dry_run": dry_run, "confirmed": confirmed}
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
    if not tags:
        tags = fetch_resource_tags(resource_id, "elastic_ip", region)
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
            return {"status": "success", "dry_run": dry_run, "confirmed": confirmed, "resource_id": resource_id, "response": response}
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "DryRunOperation":
                print(f"[AWS DryRun Success] EIP {resource_id} release_address DryRun passed.")
                return {"status": "dry_run_success", "dry_run": True, "resource_id": resource_id}
            print(f"[AWS API Response/Error] {e}")
            return {"status": "api_error", "error": str(e), "dry_run": dry_run, "confirmed": confirmed}
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
    if not tags:
        tags = fetch_resource_tags(resource_id, "ec2_instance", region)
    verify_safety_tags(resource_id, tags)
    _validate_execution_flags(resource_id, dry_run, confirmed)

    action_desc = "DRY RUN Stop EC2 Instance" if dry_run else "REAL Teardown Stop EC2 Instance"
    print(f"[{action_desc}] Target: {resource_id} (Region: {region})")

    if HAS_BOTO3:
        try:
            client = boto3.client("ec2", region_name=region)
            response = client.stop_instances(InstanceIds=[resource_id], DryRun=dry_run)
            return {"status": "success", "dry_run": dry_run, "confirmed": confirmed, "resource_id": resource_id, "response": response}
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "DryRunOperation":
                print(f"[AWS DryRun Success] Instance {resource_id} stop_instances DryRun passed.")
                return {"status": "dry_run_success", "dry_run": True, "resource_id": resource_id}
            print(f"[AWS API Response/Error] {e}")
            return {"status": "api_error", "error": str(e), "dry_run": dry_run, "confirmed": confirmed}
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
    if not tags:
        tags = fetch_resource_tags(resource_id, "snapshot", region)
    verify_safety_tags(resource_id, tags)
    _validate_execution_flags(resource_id, dry_run, confirmed)

    action_desc = "DRY RUN Delete Snapshot" if dry_run else "REAL Teardown Delete Snapshot"
    print(f"[{action_desc}] Target: {resource_id} (Region: {region})")

    if HAS_BOTO3:
        try:
            client = boto3.client("ec2", region_name=region)
            response = client.delete_snapshot(SnapshotId=resource_id, DryRun=dry_run)
            return {"status": "success", "dry_run": dry_run, "confirmed": confirmed, "resource_id": resource_id, "response": response}
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "DryRunOperation":
                print(f"[AWS DryRun Success] Snapshot {resource_id} delete_snapshot DryRun passed.")
                return {"status": "dry_run_success", "dry_run": True, "resource_id": resource_id}
            print(f"[AWS API Response/Error] {e}")
            return {"status": "api_error", "error": str(e), "dry_run": dry_run, "confirmed": confirmed}
        except Exception as e:
            print(f"[AWS Connection Warning] {e}. Falling back to simulation mode.")

    return {
        "status": "simulated_success",
        "action": "delete_snapshot",
        "resource_id": resource_id,
        "dry_run": dry_run,
        "confirmed": confirmed
    }


def terminate_ec2_instance(resource_id, tags=None, dry_run=True, confirmed=False, region="ap-south-1"):
    """
    Terminate an EC2 instance.
    Defaults to dry_run=True. Requires tag validation and confirmed=True for real action.
    """
    if not tags:
        tags = fetch_resource_tags(resource_id, "ec2_instance", region)
    verify_safety_tags(resource_id, tags)
    _validate_execution_flags(resource_id, dry_run, confirmed)

    action_desc = "DRY RUN Terminate EC2 Instance" if dry_run else "REAL Teardown Terminate EC2 Instance"
    print(f"[{action_desc}] Target: {resource_id} (Region: {region})")

    if HAS_BOTO3:
        try:
            client = boto3.client("ec2", region_name=region)
            response = client.terminate_instances(InstanceIds=[resource_id], DryRun=dry_run)
            return {"status": "success", "dry_run": dry_run, "confirmed": confirmed, "resource_id": resource_id, "response": response}
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "DryRunOperation":
                print(f"[AWS DryRun Success] Instance {resource_id} terminate_instances DryRun passed.")
                return {"status": "dry_run_success", "dry_run": True, "resource_id": resource_id}
            print(f"[AWS API Response/Error] {e}")
            return {"status": "api_error", "error": str(e), "dry_run": dry_run, "confirmed": confirmed}
        except Exception as e:
            print(f"[AWS Connection Warning] {e}. Falling back to simulation mode.")

    return {
        "status": "simulated_success",
        "action": "terminate_ec2_instance",
        "resource_id": resource_id,
        "dry_run": dry_run,
        "confirmed": confirmed
    }


def execute_teardown(resource_id, resource_type, tags=None, dry_run=True, confirmed=False, region="ap-south-1"):
    """
    Dispatches to appropriate teardown function based on resource type.
    """
    r_type = (resource_type or "").lower().replace("-", "_").strip()
    if "ebs" in r_type or "volume" in r_type or resource_id.startswith("vol-"):
        return delete_ebs_volume(resource_id, tags=tags, dry_run=dry_run, confirmed=confirmed, region=region)
    elif "eip" in r_type or "elastic_ip" in r_type or resource_id.startswith("eipalloc-"):
        return release_eip(resource_id, tags=tags, dry_run=dry_run, confirmed=confirmed, region=region)
    elif "ec2" in r_type or "instance" in r_type or resource_id.startswith("i-"):
        return terminate_ec2_instance(resource_id, tags=tags, dry_run=dry_run, confirmed=confirmed, region=region)
    elif "snap" in r_type or resource_id.startswith("snap-"):
        return delete_snapshot(resource_id, tags=tags, dry_run=dry_run, confirmed=confirmed, region=region)
    else:
        raise ValueError(f"Unsupported resource type: '{resource_type}' for resource ID '{resource_id}'")



if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Cloud Cost Janitor Teardown CLI")
    parser.add_argument("--resource-id", required=True, help="AWS Resource ID")
    parser.add_argument("--type", required=True, help="Resource Type (ec2_instance, ebs_volume, elastic_ip, snapshot)")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Perform dry run")
    parser.add_argument("--confirmed", action="store_true", default=False, help="Confirm real teardown")
    parser.add_argument("--region", default="ap-south-1", help="AWS Region (default: ap-south-1)")

    args = parser.parse_args()
    dry_run = args.dry_run
    if not dry_run and not args.confirmed:
        dry_run = True

    try:
        res = execute_teardown(
            resource_id=args.resource_id,
            resource_type=args.type,
            dry_run=dry_run,
            confirmed=args.confirmed,
            region=args.region,
        )
        print(json.dumps(res, indent=2, default=str))
    except Exception as exc:
        print(f"[TEARDOWN ERROR]: {exc}", file=sys.stderr)
        sys.exit(1)

