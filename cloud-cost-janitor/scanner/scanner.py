"""
Cloud Cost Janitor - AWS Waste Scanner (scanner/scanner.py)

Scans AWS environment for wasted/idle cloud resources:
1. Unattached EBS volumes
2. Unassociated Elastic IPs
3. EC2 instances with average CPU < 5% (CloudWatch metrics with graceful lookback fallback)
4. Load Balancers (ALB/NLB/Classic) with zero requests (CloudWatch metrics)
5. Snapshots older than 30 days not referenced by any AMI

Outputs JSON matching shared/schemas.md findings.json contract:
[
  {
    "resource_id": "string",
    "type": "string",
    "region": "string",
    "reason": "string",
    "created_date": "string",
    "tags": {}
  }
]
"""

import argparse
from datetime import datetime, timezone, timedelta
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Set

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from dotenv import load_dotenv

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scanner")


def load_environment():
    """
    Find and load .env file from working directory, script directory,
    or project parent directories. Prioritizes .env over .env.example.
    """
    search_dirs = [
        Path.cwd(),
        Path(__file__).resolve().parent,
        Path(__file__).resolve().parent.parent,
        Path(__file__).resolve().parent.parent.parent,
    ]
    # First pass: look strictly for .env with actual credentials
    for d in search_dirs:
        env_file = d / ".env"
        if env_file.is_file():
            load_dotenv(dotenv_path=env_file, override=True)
            logger.debug("Loaded environment variables from %s", env_file)
            return

    # Second pass: fallback to .env.example if no .env exists
    for d in search_dirs:
        env_example = d / ".env.example"
        if env_example.is_file():
            load_dotenv(dotenv_path=env_example)
            return


def parse_tags(tags_list: Optional[List[Dict[str, str]]]) -> Dict[str, str]:
    """Convert AWS Tag list [{'Key': 'k', 'Value': 'v'}] to dict {'k': 'v'}."""
    if not tags_list:
        return {}
    if isinstance(tags_list, dict):
        return tags_list
    tags_dict = {}
    for item in tags_list:
        if isinstance(item, dict) and "Key" in item:
            tags_dict[item["Key"]] = item.get("Value", "")
    return tags_dict


def format_iso_date(dt: Optional[datetime]) -> str:
    """Format a datetime to standard ISO 8601 string in UTC."""
    if not dt:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class CloudWasteScanner:
    """
    Scans AWS resources across configured regions for waste/idle assets.
    """

    def __init__(
        self,
        region: str = "ap-south-1",
        lookback_days: float = 3.0,
        snapshot_days: int = 30,
        cpu_threshold: float = 5.0,
    ):
        self.region = region
        self.lookback_days = lookback_days
        self.snapshot_days = snapshot_days
        self.cpu_threshold = cpu_threshold
        self.session = boto3.Session()

    def get_client(self, service_name: str, region: Optional[str] = None):
        """Create a boto3 client for a specific service and region."""
        target_region = region or self.region
        return self.session.client(service_name, region_name=target_region)

    def scan_unattached_ebs_volumes(self, region: str) -> List[Dict[str, Any]]:
        """
        Identify unattached EBS volumes (status == 'available' or empty attachments).
        """
        findings = []
        logger.info("[%s] Scanning for unattached EBS volumes...", region)
        try:
            ec2 = self.get_client("ec2", region)
            paginator = ec2.get_paginator("describe_volumes")
            for page in paginator.paginate():
                for volume in page.get("Volumes", []):
                    vol_id = volume.get("VolumeId")
                    state = volume.get("State", "")
                    attachments = volume.get("Attachments", [])
                    size_gb = volume.get("Size", 0)
                    vol_type = volume.get("VolumeType", "unknown")
                    create_time = volume.get("CreateTime")
                    tags = parse_tags(volume.get("Tags", []))

                    # Condition: unattached if state is 'available' or no attachments
                    if state == "available" or len(attachments) == 0:
                        reason = (
                            f"Unattached EBS Volume (State: {state}, Size: {size_gb} GiB, "
                            f"Type: {vol_type})"
                        )
                        finding = {
                            "resource_id": vol_id,
                            "type": "ebs_volume",
                            "region": region,
                            "reason": reason,
                            "created_date": format_iso_date(create_time),
                            "tags": tags,
                        }
                        findings.append(finding)
                        logger.info("  Found unattached EBS volume: %s (%s GiB)", vol_id, size_gb)
        except (ClientError, BotoCoreError) as e:
            logger.warning("[%s] Failed to scan EBS volumes: %s", region, e)
        except Exception as e:
            logger.error("[%s] Unexpected error scanning EBS volumes: %s", region, e)

        return findings

    def scan_unassociated_elastic_ips(self, region: str) -> List[Dict[str, Any]]:
        """
        Identify unassociated Elastic IPs (no instance or network interface association).
        """
        findings = []
        logger.info("[%s] Scanning for unassociated Elastic IPs...", region)
        try:
            ec2 = self.get_client("ec2", region)
            response = ec2.describe_addresses()
            addresses = response.get("Addresses", [])

            for addr in addresses:
                allocation_id = addr.get("AllocationId")
                public_ip = addr.get("PublicIp", "")
                association_id = addr.get("AssociationId")
                instance_id = addr.get("InstanceId")
                network_interface_id = addr.get("NetworkInterfaceId")
                tags = parse_tags(addr.get("Tags", []))

                # If not associated to an instance or ENI
                if not association_id and not instance_id and not network_interface_id:
                    res_id = allocation_id or public_ip or "unknown-eip"
                    reason = f"Unassociated Elastic IP incurring idle charges ({public_ip})"
                    finding = {
                        "resource_id": res_id,
                        "type": "elastic_ip",
                        "region": region,
                        "reason": reason,
                        "created_date": format_iso_date(None),
                        "tags": tags,
                    }
                    findings.append(finding)
                    logger.info("  Found unassociated Elastic IP: %s (%s)", res_id, public_ip)
        except (ClientError, BotoCoreError) as e:
            logger.warning("[%s] Failed to scan Elastic IPs: %s", region, e)
        except Exception as e:
            logger.error("[%s] Unexpected error scanning Elastic IPs: %s", region, e)

        return findings

    def _get_instance_cpu_utilization(
        self,
        cw_client,
        instance_id: str,
        now: datetime,
    ) -> Optional[float]:
        """
        Fetch average CPU utilization with graceful fallback for recent/demo resources.
        Tries primary lookback window first, falls back to shorter periods (1 hr, 15-30 mins).
        """
        # Primary window: lookback_days
        primary_start = now - timedelta(days=self.lookback_days)
        period = 300 if self.lookback_days >= 1.0 else 60

        try:
            res = cw_client.get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName="CPUUtilization",
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=primary_start,
                EndTime=now,
                Period=period,
                Statistics=["Average"],
            )
            datapoints = res.get("Datapoints", [])

            if datapoints:
                avg_cpu = sum(d["Average"] for d in datapoints) / len(datapoints)
                return avg_cpu

            # Graceful fallback: Demo AWS resources may only have 15-60 minutes of history
            logger.debug(
                "No primary CloudWatch data for %s over %.1f days. Attempting graceful fallback...",
                instance_id,
                self.lookback_days,
            )
            for fallback_mins in [60, 30, 15]:
                fallback_start = now - timedelta(minutes=fallback_mins)
                fallback_res = cw_client.get_metric_statistics(
                    Namespace="AWS/EC2",
                    MetricName="CPUUtilization",
                    Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                    StartTime=fallback_start,
                    EndTime=now,
                    Period=60,
                    Statistics=["Average"],
                )
                fb_datapoints = fallback_res.get("Datapoints", [])
                if fb_datapoints:
                    avg_cpu = sum(d["Average"] for d in fb_datapoints) / len(fb_datapoints)
                    logger.info(
                        "  [Fallback Hit] %s: Found %d datapoint(s) in last %d mins (Avg CPU: %.2f%%)",
                        instance_id,
                        len(fb_datapoints),
                        fallback_mins,
                        avg_cpu,
                    )
                    return avg_cpu

            # If still no datapoints (e.g. brand new or no activity emitted yet), return None
            return None
        except Exception as e:
            logger.debug("CloudWatch query error for instance %s: %s", instance_id, e)
            return None

    def scan_ec2_instances(self, region: str) -> List[Dict[str, Any]]:
        """
        Identify EC2 instances that are stopped or have average CPU utilization < threshold.
        """
        findings = []
        logger.info("[%s] Scanning for idle/underutilized EC2 instances...", region)
        try:
            ec2 = self.get_client("ec2", region)
            cw = self.get_client("cloudwatch", region)
            now = datetime.now(timezone.utc)

            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate():
                for reservation in page.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        instance_id = instance.get("InstanceId")
                        state = instance.get("State", {}).get("Name", "")
                        launch_time = instance.get("LaunchTime")
                        instance_type = instance.get("InstanceType", "unknown")
                        tags = parse_tags(instance.get("Tags", []))

                        # Check 1: Stopped instance is idle waste
                        if state in ["stopped", "stopping"]:
                            reason = (
                                f"Stopped EC2 instance idle in {state} state "
                                f"(Type: {instance_type})"
                            )
                            findings.append({
                                "resource_id": instance_id,
                                "type": "ec2_instance",
                                "region": region,
                                "reason": reason,
                                "created_date": format_iso_date(launch_time),
                                "tags": tags,
                            })
                            logger.info("  Found stopped EC2 instance: %s (%s)", instance_id, state)
                            continue

                        # Check 2: Running instance with low CPU (< cpu_threshold)
                        if state == "running":
                            avg_cpu = self._get_instance_cpu_utilization(cw, instance_id, now)
                            if avg_cpu is not None:
                                if avg_cpu < self.cpu_threshold:
                                    reason = (
                                        f"EC2 instance with low average CPU utilization "
                                        f"({avg_cpu:.2f}% < {self.cpu_threshold}%)"
                                    )
                                    findings.append({
                                        "resource_id": instance_id,
                                        "type": "ec2_instance",
                                        "region": region,
                                        "reason": reason,
                                        "created_date": format_iso_date(launch_time),
                                        "tags": tags,
                                    })
                                    logger.info(
                                        "  Found low-CPU EC2 instance: %s (Avg CPU: %.2f%%)",
                                        instance_id,
                                        avg_cpu,
                                    )
                            else:
                                # In demo environment if instance was just created and has 0 activity reported
                                # Check if launched more than 10 minutes ago
                                if launch_time:
                                    age_mins = (now - launch_time).total_seconds() / 60.0
                                    if age_mins > 10.0:
                                        # If running for >10 mins with 0 CloudWatch activity, consider idle
                                        reason = (
                                            f"EC2 instance with 0 recorded CPU activity over available history "
                                            f"(Type: {instance_type})"
                                        )
                                        findings.append({
                                            "resource_id": instance_id,
                                            "type": "ec2_instance",
                                            "region": region,
                                            "reason": reason,
                                            "created_date": format_iso_date(launch_time),
                                            "tags": tags,
                                        })
                                        logger.info(
                                            "  Found idle running EC2 instance (no CW metrics): %s",
                                            instance_id,
                                        )

        except (ClientError, BotoCoreError) as e:
            logger.warning("[%s] Failed to scan EC2 instances: %s", region, e)
        except Exception as e:
            logger.error("[%s] Unexpected error scanning EC2 instances: %s", region, e)

        return findings

    def _get_load_balancer_requests(
        self,
        cw_client,
        lb_type: str,
        lb_arn: str,
        now: datetime,
    ) -> int:
        """
        Query CloudWatch for load balancer request count / traffic.
        Returns total request/flow count (0 if idle).
        """
        try:
            # Suffix format for ALB/NLB in CloudWatch dimension is: app/my-load-balancer/50dc6c495c0c9188
            if "loadbalancer/" in lb_arn:
                lb_dimension = lb_arn.split("loadbalancer/")[1]
            else:
                lb_dimension = lb_arn

            namespace = "AWS/ApplicationELB" if lb_type == "application" else "AWS/NetworkELB"
            metric_name = "RequestCount" if lb_type == "application" else "ActiveFlowCount"

            primary_start = now - timedelta(days=self.lookback_days)
            period = 300 if self.lookback_days >= 1.0 else 60

            res = cw_client.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=[{"Name": "LoadBalancer", "Value": lb_dimension}],
                StartTime=primary_start,
                EndTime=now,
                Period=period,
                Statistics=["Sum"],
            )
            datapoints = res.get("Datapoints", [])
            if datapoints:
                return int(sum(d["Sum"] for d in datapoints))

            # Graceful fallback: check recent 1-hour / 30-min window
            fallback_start = now - timedelta(hours=1)
            fb_res = cw_client.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=[{"Name": "LoadBalancer", "Value": lb_dimension}],
                StartTime=fallback_start,
                EndTime=now,
                Period=60,
                Statistics=["Sum"],
            )
            fb_datapoints = fb_res.get("Datapoints", [])
            if fb_datapoints:
                return int(sum(d["Sum"] for d in fb_datapoints))

            return 0
        except Exception as e:
            logger.debug("CloudWatch query error for LB %s: %s", lb_arn, e)
            return 0

    def scan_load_balancers(self, region: str) -> List[Dict[str, Any]]:
        """
        Identify Application and Network Load Balancers with zero requests.
        """
        findings = []
        logger.info("[%s] Scanning for idle Load Balancers (ALB/NLB)...", region)
        try:
            elbv2 = self.get_client("elbv2", region)
            cw = self.get_client("cloudwatch", region)
            now = datetime.now(timezone.utc)

            paginator = elbv2.get_paginator("describe_load_balancers")
            for page in paginator.paginate():
                lbs = page.get("LoadBalancers", [])
                if not lbs:
                    continue

                # Batch fetch tags for these load balancers
                arn_list = [lb["LoadBalancerArn"] for lb in lbs if "LoadBalancerArn" in lb]
                tags_map = {}
                if arn_list:
                    try:
                        # describe_tags takes up to 20 arns per call
                        for i in range(0, len(arn_list), 20):
                            batch = arn_list[i:i + 20]
                            tag_res = elbv2.describe_tags(ResourceArns=batch)
                            for item in tag_res.get("TagDescriptions", []):
                                tags_map[item["ResourceArn"]] = parse_tags(item.get("Tags", []))
                    except Exception as te:
                        logger.debug("[%s] Could not fetch ELB tags: %s", region, te)

                for lb in lbs:
                    lb_arn = lb.get("LoadBalancerArn")
                    lb_type = lb.get("Type", "application")
                    created_time = lb.get("CreatedTime")
                    tags = tags_map.get(lb_arn, {})

                    requests = self._get_load_balancer_requests(cw, lb_type, lb_arn, now)
                    if requests == 0:
                        type_label = "Application Load Balancer" if lb_type == "application" else "Network Load Balancer"
                        reason = f"{type_label} with zero requests over lookback period"
                        findings.append({
                            "resource_id": lb_arn,
                            "type": "load_balancer",
                            "region": region,
                            "reason": reason,
                            "created_date": format_iso_date(created_time),
                            "tags": tags,
                        })
                        logger.info("  Found idle load balancer: %s (0 requests)", lb_arn)

        except (ClientError, BotoCoreError) as e:
            logger.warning("[%s] Failed to scan ELBv2 load balancers: %s", region, e)
        except Exception as e:
            logger.error("[%s] Unexpected error scanning ELBv2 load balancers: %s", region, e)

        # Also check Classic ELBs if any exist
        try:
            elb = self.get_client("elb", region)
            cw = self.get_client("cloudwatch", region)
            now = datetime.now(timezone.utc)
            classic_paginator = elb.get_paginator("describe_load_balancers")
            for page in classic_paginator.paginate():
                for clb in page.get("LoadBalancerDescriptions", []):
                    clb_name = clb.get("LoadBalancerName")
                    created_time = clb.get("CreatedTime")

                    # Check CloudWatch for Classic ELB
                    try:
                        res = cw.get_metric_statistics(
                            Namespace="AWS/ELB",
                            MetricName="RequestCount",
                            Dimensions=[{"Name": "LoadBalancerName", "Value": clb_name}],
                            StartTime=now - timedelta(days=self.lookback_days),
                            EndTime=now,
                            Period=300 if self.lookback_days >= 1.0 else 60,
                            Statistics=["Sum"],
                        )
                        dps = res.get("Datapoints", [])
                        total_req = int(sum(d["Sum"] for d in dps)) if dps else 0
                    except Exception:
                        total_req = 0

                    if total_req == 0:
                        # Fetch tags for classic elb
                        try:
                            ctags_res = elb.describe_tags(LoadBalancerNames=[clb_name])
                            ctags_list = ctags_res.get("TagDescriptions", [{}])[0].get("Tags", [])
                            tags = parse_tags(ctags_list)
                        except Exception:
                            tags = {}

                        findings.append({
                            "resource_id": clb_name,
                            "type": "load_balancer",
                            "region": region,
                            "reason": "Classic Load Balancer with zero requests",
                            "created_date": format_iso_date(created_time),
                            "tags": tags,
                        })
                        logger.info("  Found idle Classic ELB: %s (0 requests)", clb_name)
        except Exception as e:
            logger.debug("[%s] Classic ELB scan skipped or unsupported: %s", region, e)

        return findings

    def scan_orphaned_snapshots(self, region: str) -> List[Dict[str, Any]]:
        """
        Identify snapshots older than snapshot_days (default 30) not referenced by any AMI.
        """
        findings = []
        logger.info("[%s] Scanning for orphaned EBS snapshots (>%d days old)...", region, self.snapshot_days)
        try:
            ec2 = self.get_client("ec2", region)
            now = datetime.now(timezone.utc)

            # Step 1: Collect all Snapshot IDs referenced by user-owned AMIs
            ami_snapshot_ids: Set[str] = set()
            try:
                images_res = ec2.describe_images(Owners=["self"])
                for img in images_res.get("Images", []):
                    for bdm in img.get("BlockDeviceMappings", []):
                        ebs_info = bdm.get("Ebs", {})
                        snap_id = ebs_info.get("SnapshotId")
                        if snap_id:
                            ami_snapshot_ids.add(snap_id)
            except Exception as ie:
                logger.warning("[%s] Failed to retrieve AMIs for snapshot comparison: %s", region, ie)

            # Step 2: Query user-owned snapshots
            paginator = ec2.get_paginator("describe_snapshots")
            for page in paginator.paginate(OwnerIds=["self"]):
                for snap in page.get("Snapshots", []):
                    snap_id = snap.get("SnapshotId")
                    start_time = snap.get("StartTime")
                    tags = parse_tags(snap.get("Tags", []))

                    if not start_time:
                        continue

                    # Calculate age in days
                    age_days = (now - start_time).total_seconds() / 86400.0

                    # Condition: Older than threshold AND not referenced by any active AMI
                    if age_days >= self.snapshot_days and snap_id not in ami_snapshot_ids:
                        reason = (
                            f"Orphaned EBS snapshot ({int(age_days)} days old) "
                            f"not referenced by any AMI"
                        )
                        findings.append({
                            "resource_id": snap_id,
                            "type": "snapshot",
                            "region": region,
                            "reason": reason,
                            "created_date": format_iso_date(start_time),
                            "tags": tags,
                        })
                        logger.info("  Found orphaned snapshot: %s (%d days old)", snap_id, int(age_days))
        except (ClientError, BotoCoreError) as e:
            logger.warning("[%s] Failed to scan snapshots: %s", region, e)
        except Exception as e:
            logger.error("[%s] Unexpected error scanning snapshots: %s", region, e)

        return findings

    def scan_all_for_region(self, region: str) -> List[Dict[str, Any]]:
        """Run all scanners for a specific AWS region."""
        logger.info("==================================================")
        logger.info("Starting Cloud Cost Janitor Scan for Region: %s", region)
        logger.info("Lookback window: %.1f days | Snapshot threshold: %d days | CPU threshold: %.1f%%",
                    self.lookback_days, self.snapshot_days, self.cpu_threshold)
        logger.info("==================================================")

        all_findings = []
        all_findings.extend(self.scan_unattached_ebs_volumes(region))
        all_findings.extend(self.scan_unassociated_elastic_ips(region))
        all_findings.extend(self.scan_ec2_instances(region))
        all_findings.extend(self.scan_load_balancers(region))
        all_findings.extend(self.scan_orphaned_snapshots(region))

        logger.info("[%s] Completed scan. Found %d waste item(s).", region, len(all_findings))
        return all_findings


def get_all_aws_regions(session: boto3.Session, default_region: str = "ap-south-1") -> List[str]:
    """Retrieve list of all available AWS regions for EC2."""
    try:
        ec2 = session.client("ec2", region_name=default_region)
        regions_response = ec2.describe_regions(AllRegions=False)
        return [r["RegionName"] for r in regions_response.get("Regions", [])]
    except Exception as e:
        logger.warning("Could not list all AWS regions, defaulting to ['%s']: %s", default_region, e)
        return [default_region]


def scan(
    region: Optional[str] = None,
    all_regions: bool = False,
    lookback_days: float = 3.0,
    snapshot_days: int = 30,
    cpu_threshold: float = 5.0,
    output_path: Optional[str] = "findings.json",
) -> List[Dict[str, Any]]:
    """
    Main programmatic interface to execute cloud resource waste scanning.
    """
    load_environment()

    # Determine target region(s)
    env_region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    target_region = region or env_region or "ap-south-1"

    scanner = CloudWasteScanner(
        region=target_region,
        lookback_days=lookback_days,
        snapshot_days=snapshot_days,
        cpu_threshold=cpu_threshold,
    )

    regions_to_scan = []
    if all_regions:
        regions_to_scan = get_all_aws_regions(scanner.session, default_region=target_region)
    else:
        regions_to_scan = [target_region]

    findings = []
    for r in regions_to_scan:
        try:
            r_findings = scanner.scan_all_for_region(r)
            findings.extend(r_findings)
        except Exception as e:
            logger.error("Error scanning region %s: %s", r, e)

    # Save to output file if specified
    if output_path:
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(findings, f, indent=2)
        logger.info("Saved %d finding(s) to %s", len(findings), out_file.resolve())

    return findings


def main():
    """CLI entrypoint for scanner."""
    load_environment()

    default_region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-south-1"
    default_lookback = float(os.environ.get("LOOKBACK_DAYS", os.environ.get("CPU_LOOKBACK_DAYS", "3.0")))
    default_snapshot_age = int(os.environ.get("SNAPSHOT_AGE_DAYS", "30"))
    default_cpu_threshold = float(os.environ.get("CPU_THRESHOLD", "5.0"))

    parser = argparse.ArgumentParser(
        description="Cloud Cost Janitor - AWS Waste Scanner (boto3 & CloudWatch)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--region",
        type=str,
        default=default_region,
        help="AWS region to scan (e.g. ap-south-1, us-east-1)",
    )
    parser.add_argument(
        "--all-regions",
        action="store_true",
        help="Scan across all enabled AWS regions",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="findings.json",
        help="Output JSON file path for findings",
    )
    parser.add_argument(
        "--lookback-days",
        type=float,
        default=default_lookback,
        help="Lookback window in days for CloudWatch metrics (supports fractional days, e.g., 0.5)",
    )
    parser.add_argument(
        "--lookback-hours",
        type=float,
        default=None,
        help="Optional lookback window in hours (overrides --lookback-days)",
    )
    parser.add_argument(
        "--snapshot-days",
        type=int,
        default=default_snapshot_age,
        help="Age threshold in days for orphaned EBS snapshots",
    )
    parser.add_argument(
        "--cpu-threshold",
        type=float,
        default=default_cpu_threshold,
        help="Average CPU utilization percentage below which an instance is flagged as idle",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    lookback = args.lookback_days
    if args.lookback_hours is not None:
        lookback = args.lookback_hours / 24.0

    try:
        findings = scan(
            region=args.region,
            all_regions=args.all_regions,
            lookback_days=lookback,
            snapshot_days=args.snapshot_days,
            cpu_threshold=args.cpu_threshold,
            output_path=args.output,
        )
        print(f"\n[SCAN COMPLETE] Identified {len(findings)} wasted resource(s). Output written to: {args.output}")
    except NoCredentialsError:
        logger.error("AWS credentials not found. Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env.")
        sys.exit(1)
    except Exception as e:
        logger.error("Scan failed with error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
