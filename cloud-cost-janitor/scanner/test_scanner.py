"""
Unit tests for scanner/scanner.py
"""

from datetime import datetime, timezone, timedelta
import json
import os
import unittest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

from scanner.scanner import CloudWasteScanner, scan, parse_tags, format_iso_date


class TestCloudWasteScanner(unittest.TestCase):

    def setUp(self):
        self.scanner = CloudWasteScanner(region="ap-south-1", lookback_days=3.0, snapshot_days=30, cpu_threshold=5.0)

    def test_parse_tags(self):
        tag_list = [{"Key": "Name", "Value": "test-res"}, {"Key": "Env", "Value": "prod"}]
        expected = {"Name": "test-res", "Env": "prod"}
        self.assertEqual(parse_tags(tag_list), expected)
        self.assertEqual(parse_tags([]), {})
        self.assertEqual(parse_tags(None), {})
        self.assertEqual(parse_tags({"already": "dict"}), {"already": "dict"})

    def test_format_iso_date(self):
        dt = datetime(2024, 2, 10, 10, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(format_iso_date(dt), "2024-02-10T10:15:00Z")

    @patch.object(CloudWasteScanner, "get_client")
    def test_scan_unattached_ebs_volumes(self, mock_get_client):
        mock_ec2 = MagicMock()
        mock_get_client.return_value = mock_ec2

        mock_paginator = MagicMock()
        mock_ec2.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Volumes": [
                    {
                        "VolumeId": "vol-0123456789abcdef0",
                        "State": "available",
                        "Attachments": [],
                        "Size": 20,
                        "VolumeType": "gp3",
                        "CreateTime": datetime(2024, 2, 10, 10, 15, 0, tzinfo=timezone.utc),
                        "Tags": [{"Key": "Owner", "Value": "Dev1"}],
                    },
                    {
                        "VolumeId": "vol-in-use-1234",
                        "State": "in-use",
                        "Attachments": [{"InstanceId": "i-123"}],
                        "Size": 100,
                        "VolumeType": "gp3",
                        "CreateTime": datetime(2024, 2, 10, 10, 15, 0, tzinfo=timezone.utc),
                        "Tags": [],
                    }
                ]
            }
        ]

        findings = self.scanner.scan_unattached_ebs_volumes("ap-south-1")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["resource_id"], "vol-0123456789abcdef0")
        self.assertEqual(findings[0]["type"], "ebs_volume")
        self.assertEqual(findings[0]["region"], "ap-south-1")
        self.assertEqual(findings[0]["tags"], {"Owner": "Dev1"})
        self.assertIn("Unattached EBS Volume", findings[0]["reason"])

    @patch.object(CloudWasteScanner, "get_client")
    def test_scan_unassociated_elastic_ips(self, mock_get_client):
        mock_ec2 = MagicMock()
        mock_get_client.return_value = mock_ec2

        mock_ec2.describe_addresses.return_value = {
            "Addresses": [
                {
                    "AllocationId": "eipalloc-0a1b2c3d4e5f67890",
                    "PublicIp": "13.235.1.2",
                    "Tags": [{"Key": "Project", "Value": "Demo"}],
                },
                {
                    "AllocationId": "eipalloc-attached",
                    "PublicIp": "13.235.1.3",
                    "AssociationId": "eipassoc-123",
                    "InstanceId": "i-123",
                }
            ]
        }

        findings = self.scanner.scan_unassociated_elastic_ips("ap-south-1")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["resource_id"], "eipalloc-0a1b2c3d4e5f67890")
        self.assertEqual(findings[0]["type"], "elastic_ip")
        self.assertEqual(findings[0]["region"], "ap-south-1")
        self.assertEqual(findings[0]["tags"], {"Project": "Demo"})

    @patch.object(CloudWasteScanner, "get_client")
    def test_scan_ec2_instances_stopped_and_low_cpu(self, mock_get_client):
        mock_ec2 = MagicMock()
        mock_cw = MagicMock()

        def client_side_effect(service, region):
            if service == "ec2":
                return mock_ec2
            if service == "cloudwatch":
                return mock_cw
            return MagicMock()

        mock_get_client.side_effect = client_side_effect

        mock_paginator = MagicMock()
        mock_ec2.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-stopped-001",
                                "State": {"Name": "stopped"},
                                "LaunchTime": datetime(2024, 3, 1, 9, 0, 0, tzinfo=timezone.utc),
                                "InstanceType": "t3.micro",
                                "Tags": [{"Key": "Name", "Value": "stopped-inst"}],
                            },
                            {
                                "InstanceId": "i-lowcpu-002",
                                "State": {"Name": "running"},
                                "LaunchTime": datetime(2024, 3, 1, 9, 0, 0, tzinfo=timezone.utc),
                                "InstanceType": "t3.medium",
                                "Tags": [{"Key": "Name", "Value": "lowcpu-inst"}],
                            },
                            {
                                "InstanceId": "i-busy-003",
                                "State": {"Name": "running"},
                                "LaunchTime": datetime(2024, 3, 1, 9, 0, 0, tzinfo=timezone.utc),
                                "InstanceType": "t3.large",
                                "Tags": [{"Key": "Name", "Value": "busy-inst"}],
                            }
                        ]
                    }
                ]
            }
        ]

        # CloudWatch returns 1.5% for i-lowcpu-002 and 55.0% for i-busy-003
        def get_metric_side_effect(**kwargs):
            inst_id = kwargs.get("Dimensions", [{}])[0].get("Value")
            if inst_id == "i-lowcpu-002":
                return {"Datapoints": [{"Average": 1.5}]}
            elif inst_id == "i-busy-003":
                return {"Datapoints": [{"Average": 55.0}]}
            return {"Datapoints": []}

        mock_cw.get_metric_statistics.side_effect = get_metric_side_effect

        findings = self.scanner.scan_ec2_instances("ap-south-1")
        self.assertEqual(len(findings), 2)
        inst_ids = [f["resource_id"] for f in findings]
        self.assertIn("i-stopped-001", inst_ids)
        self.assertIn("i-lowcpu-002", inst_ids)
        self.assertNotIn("i-busy-003", inst_ids)

    @patch.object(CloudWasteScanner, "get_client")
    def test_scan_orphaned_snapshots(self, mock_get_client):
        mock_ec2 = MagicMock()
        mock_get_client.return_value = mock_ec2

        now = datetime.now(timezone.utc)
        old_time = now - timedelta(days=45)
        new_time = now - timedelta(days=10)

        mock_ec2.describe_images.return_value = {
            "Images": [
                {
                    "ImageId": "ami-12345",
                    "BlockDeviceMappings": [
                        {"Ebs": {"SnapshotId": "snap-ami-referenced"}}
                    ]
                }
            ]
        }

        mock_paginator = MagicMock()
        mock_ec2.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Snapshots": [
                    {
                        "SnapshotId": "snap-orphaned-old",
                        "StartTime": old_time,
                        "Tags": [{"Key": "Backup", "Value": "Manual"}],
                    },
                    {
                        "SnapshotId": "snap-ami-referenced",
                        "StartTime": old_time,
                        "Tags": [],
                    },
                    {
                        "SnapshotId": "snap-recent",
                        "StartTime": new_time,
                        "Tags": [],
                    }
                ]
            }
        ]

        findings = self.scanner.scan_orphaned_snapshots("ap-south-1")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["resource_id"], "snap-orphaned-old")
        self.assertEqual(findings[0]["type"], "snapshot")

    @patch.object(CloudWasteScanner, "get_client")
    def test_resilience_on_client_error(self, mock_get_client):
        mock_ec2 = MagicMock()
        mock_ec2.get_paginator.side_effect = ClientError(
            {"Error": {"Code": "UnauthorizedOperation", "Message": "Access Denied"}},
            "DescribeVolumes"
        )
        mock_get_client.return_value = mock_ec2

        # Ensure scan does not raise exception
        findings = self.scanner.scan_unattached_ebs_volumes("ap-south-1")
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
