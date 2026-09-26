# Cloud Cost Janitor

An automated system to scan, price, prioritize, and report on wasted AWS cloud resources.

## Folder Ownership

- `scanner/` = **Dev1**
- `pricing/` = **Dev2**
- `agent/` = **Dev3**
- `report/` = **Dev4**

## Shared Contracts & Mock Data

- Schema specifications: [`shared/schemas.md`](shared/schemas.md)
- Scanner mock output: [`shared/sample_findings.json`](shared/sample_findings.json)
- Pricing mock output: [`shared/sample_prioritized_findings.json`](shared/sample_prioritized_findings.json)

## Setup

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Populate the required environment variables.
