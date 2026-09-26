# Cloud Cost Janitor - Data Schemas

This document defines the JSON contracts for communication between the Cloud Cost Janitor modules.

---

## 1. `findings.json` (array of objects)

Output contract produced by the `scanner/` module. Represents identified unused or waste AWS resources.

```json
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
```

### Schema Specification:
- **`resource_id`** (`string`): Unique identifier of the AWS resource (e.g., `vol-0a1b2c3d4e5f67890`, `eipalloc-0123456789abcdef0`).
- **`type`** (`string`): Type of resource scanned (`ebs_volume`, `elastic_ip`, `ec2_instance`, `load_balancer`, `snapshot`).
- **`region`** (`string`): AWS region where the resource resides (e.g., `us-east-1`, `ap-south-1`).
- **`reason`** (`string`): Description of why the resource is considered wasted or idle.
- **`created_date`** (`string`): Creation timestamp formatted in ISO 8601 string.
- **`tags`** (`object`): Dictionary of resource key-value tags.

---

## 2. `prioritized_findings.json` (array of objects)

Output contract produced by the `pricing/` module. Extends `findings.json` with cost estimation figures.

```json
[
  {
    "resource_id": "string",
    "type": "string",
    "region": "string",
    "reason": "string",
    "created_date": "string",
    "tags": {},
    "monthly_cost_usd": 0.0,
    "monthly_cost_inr": 0.0
  }
]
```

### Schema Specification:
Contains all fields from `findings.json` plus:
- **`monthly_cost_usd`** (`number`): Estimated wasted monthly cost in USD.
- **`monthly_cost_inr`** (`number`): Estimated wasted monthly cost in INR (calculated via `INR_PER_USD`).
