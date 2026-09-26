---
name: aws_waste_scanner
description: Scans AWS cloud infrastructure to identify wasted, unattached, and idle resources (EBS volumes, Elastic IPs, low CPU EC2 instances, 0-request Load Balancers, and orphaned snapshots).
version: 1.0.0
author: Dev1 (Cloud Cost Janitor)
---

# AWS Waste Scanner Tool (`aws_waste_scanner`)

## Overview
The **AWS Waste Scanner** (`scanner/scanner.py`) audits AWS infrastructure to discover orphaned, unused, or underutilized resources that are driving unnecessary cloud expenses.

This tool is designed to integrate seamlessly into **TrueForge** agent workflows, CLI pipelines, and cron monitoring jobs.

---

## Tool Metadata for TrueForge Registration (Dev3)

```json
{
  "name": "scan_aws_waste",
  "description": "Scans AWS regions for idle, unattached, or orphaned resources (unattached EBS volumes, unassociated Elastic IPs, idle EC2 instances with <5% CPU, load balancers with 0 requests, and snapshots >30 days not linked to an AMI).",
  "parameters": {
    "type": "object",
    "properties": {
      "region": {
        "type": "string",
        "description": "AWS region to scan (e.g., 'ap-south-1', 'us-east-1'). Defaults to AWS_REGION in .env or 'ap-south-1'.",
        "default": "ap-south-1"
      },
      "all_regions": {
        "type": "boolean",
        "description": "If true, scans across all enabled AWS regions.",
        "default": false
      },
      "lookback_days": {
        "type": "number",
        "description": "Lookback window in days for CloudWatch metrics (CPU and LB requests). Automatically falls back to shorter 15-60 min windows if full history is not yet available.",
        "default": 3.0
      },
      "snapshot_days": {
        "type": "integer",
        "description": "Age threshold in days for orphaned EBS snapshots.",
        "default": 30
      },
      "cpu_threshold": {
        "type": "number",
        "description": "Average CPU utilization percentage threshold below which EC2 instances are marked idle.",
        "default": 5.0
      },
      "output_path": {
        "type": "string",
        "description": "Path to write the findings JSON file.",
        "default": "findings.json"
      }
    },
    "required": []
  }
}
```

---

## CLI Execution

```bash
# Run for a specific region
python scanner/scanner.py --region ap-south-1 --output findings.json

# Run with custom CloudWatch lookback (e.g. for demo resources)
python scanner/scanner.py --region ap-south-1 --lookback-days 0.5 --output findings.json

# Run across all regions
python scanner/scanner.py --all-regions --output findings.json
```

---

## Python Programmatic API

```python
from scanner.scanner import scan

# Run scan programmatically
findings = scan(
    region="ap-south-1",
    lookback_days=3.0,
    snapshot_days=30,
    cpu_threshold=5.0,
    output_path="findings.json"
)
```

---

## Output Contract (`findings.json`)

Output complies with `shared/schemas.md`:

```json
[
  {
    "resource_id": "vol-0a1b2c3d4e5f67890",
    "type": "ebs_volume",
    "region": "ap-south-1",
    "reason": "Unattached EBS Volume (State: available, Size: 20 GiB, Type: gp3)",
    "created_date": "2024-02-10T10:15:00Z",
    "tags": {
      "Environment": "hackathon-demo",
      "Owner": "Dev1"
    }
  },
  {
    "resource_id": "eipalloc-0123456789abcdef0",
    "type": "elastic_ip",
    "region": "ap-south-1",
    "reason": "Unassociated Elastic IP incurring idle charges (13.235.12.34)",
    "created_date": "2024-03-01T00:00:00Z",
    "tags": {}
  },
  {
    "resource_id": "i-0987654321fedcba0",
    "type": "ec2_instance",
    "region": "ap-south-1",
    "reason": "EC2 instance with low average CPU utilization (1.24% < 5.0%)",
    "created_date": "2024-03-01T09:00:00Z",
    "tags": {
      "Name": "demo-worker"
    }
  },
  {
    "resource_id": "arn:aws:elasticloadbalancing:ap-south-1:123456789012:loadbalancer/app/demo-alb/50dc6c495c0c9188",
    "type": "load_balancer",
    "region": "ap-south-1",
    "reason": "Application Load Balancer with zero requests over lookback period",
    "created_date": "2024-02-28T16:45:30Z",
    "tags": {}
  },
  {
    "resource_id": "snap-01234567898765432",
    "type": "snapshot",
    "region": "ap-south-1",
    "reason": "Orphaned EBS snapshot (45 days old) not referenced by any AMI",
    "created_date": "2024-01-15T11:05:00Z",
    "tags": {}
  }
]
```

---

## Waste Detection Rules

| Resource Type | Condition | CloudWatch / AWS Metric Checked |
|---|---|---|
| `ebs_volume` | Volume state is `available` or has no attachments | EC2 `describe_volumes` |
| `elastic_ip` | EIP has no `AssociationId`, `InstanceId`, or ENI | EC2 `describe_addresses` |
| `ec2_instance` | Stopped instance OR Average `CPUUtilization` < 5.0% | `AWS/EC2:CPUUtilization` (falls back gracefully to 15-60 min data for newly created demo resources) |
| `load_balancer` | ALB/NLB/CLB with 0 requests / active flows | `AWS/ApplicationELB:RequestCount`, `AWS/NetworkELB:ActiveFlowCount`, `AWS/ELB:RequestCount` |
| `snapshot` | Snapshots >30 days old not linked to any active AMI | EC2 `describe_snapshots` & `describe_images(Owners=['self'])` |

---

## Resilience & Error Handling
- **Non-Crashing**: Catches AWS `ClientError`, `BotoCoreError`, permission denials, and missing API endpoints per service. Logs warnings and continues scanning remaining resources.
- **Graceful Fallback**: If CloudWatch lacks multi-day history (e.g., demo resources spun up minutes ago), it queries 60m, 30m, and 15m windows dynamically.
- **Environment**: Automatically loads AWS credentials and region from `.env`.
