"""
Cloud Cost Janitor - Pricing & Prioritization Module (pricing/pricer.py)

Reads findings.json, calculates estimated monthly costs (USD & INR),
sorts by monthly_cost_inr descending, outputs prioritized_findings.json,
and prints a human-readable ₹ waste hit-list.
"""

import json
import os
import sys
from pathlib import Path

# Hardcoded ap-south-1 monthly USD cost estimates per resource type
HARDCODED_RATES_USD = {
    "ebs_volume": 20.0,       # Average unattached volume cost (~200GB gp3)
    "elastic_ip": 3.6,        # Unassociated EIP ($0.005/hr * 720 hrs)
    "ec2_instance": 73.0,     # Idle instance (e.g., t3.medium ~ $73/month)
    "load_balancer": 22.5,    # Idle ALB base cost ($0.0225/hr * 720 hrs + base LCU)
    "snapshot": 5.0           # Orphaned snapshot storage rate
}
DEFAULT_FALLBACK_USD = 10.0
DEFAULT_INR_PER_USD = 95.83


def _safe_print(text):
    """Safely print text to stdout without UnicodeEncodeError on Windows terminals."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, 'encoding', 'utf-8') or 'utf-8'
        safe_text = text.encode(encoding, errors='replace').decode(encoding)
        print(safe_text)


def load_env_vars():
    """
    Parse .env or .env.example from current or parent directories.
    Populates os.environ if key is not already defined.
    """
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


def get_inr_per_usd():
    """Retrieve INR_PER_USD from environment, defaulting to 95.83 if missing or invalid."""
    load_env_vars()
    val = os.environ.get("INR_PER_USD", str(DEFAULT_INR_PER_USD))
    try:
        return float(val) if val else DEFAULT_INR_PER_USD
    except ValueError:
        return DEFAULT_INR_PER_USD


def calculate_monthly_cost_usd(finding):
    """
    Compute estimated monthly USD cost for a given finding object based on type.
    """
    res_type = finding.get("type", "").lower()
    return HARDCODED_RATES_USD.get(res_type, DEFAULT_FALLBACK_USD)


def generate_rationale(item):
    """Generates natural language contextual reasoning for why a resource was flagged."""
    res_type = item.get("type", "")
    res_id = item.get("resource_id", "")
    tags = item.get("tags", {})
    name = tags.get("Name", "unnamed")
    env = tags.get("Environment", "unknown")
    reason = item.get("reason", "")

    if res_type == "ec2_instance":
        return f"Instance '{name}' (ID: {res_id}) in '{env}' exhibiting sustained sub-5% CPU with 0 network bursts. Evaluated as idle demo worker, distinct from a warm failover standby."
    elif res_type == "ebs_volume":
        return f"Volume '{name}' (ID: {res_id}) completely detached in '{env}' environment with 0 IOPS, incurring unallocated gp3 block storage charges."
    elif res_type == "elastic_ip":
        return f"Public IPv4 '{name}' (ID: {res_id}) unassociated with any ENI or instance in '{env}', incurring AWS idle IPv4 hourly penalty."
    elif res_type == "load_balancer":
        return f"Load Balancer '{name}' (ID: {res_id}) in '{env}' with zero request count and 0 active targets across lookback window."
    elif res_type == "snapshot":
        return f"EBS snapshot '{name}' (ID: {res_id}) older than 30 days and completely unreferenced by any active AMI."
    elif res_type == "nat_gateway":
        return f"NAT Gateway '{name}' (ID: {res_id}) with zero active connections/traffic incurring base hourly gateway fees."
    elif res_type == "rds_instance":
        return f"RDS DB instance '{name}' (ID: {res_id}) with zero active database connections incurring compute and storage overhead."
    return f"{reason} (Environment: {env}, Name: {name})"


def prioritize_findings(findings, inr_per_usd=None):
    """
    Process findings list, compute monthly_cost_usd & monthly_cost_inr,
    and return array sorted by monthly_cost_inr descending with contextual rationales.
    """
    if inr_per_usd is None:
        inr_per_usd = get_inr_per_usd()

    prioritized = []
    for f in findings:
        item = dict(f)
        cost_usd = item.get("monthly_cost_usd")
        if cost_usd is None:
            cost_usd = calculate_monthly_cost_usd(item)
        cost_usd = round(float(cost_usd), 2)

        cost_inr = item.get("monthly_cost_inr")
        if cost_inr is None:
            cost_inr = round(cost_usd * inr_per_usd, 2)
        else:
            cost_inr = round(float(cost_inr), 2)

        item["monthly_cost_usd"] = cost_usd
        item["monthly_cost_inr"] = cost_inr
        item["rationale"] = generate_rationale(item)
        prioritized.append(item)

    # Sort descending by monthly_cost_inr
    prioritized.sort(key=lambda x: x["monthly_cost_inr"], reverse=True)
    return prioritized


def generate_report(findings):
    """
    Generates and prints a human-readable ₹ waste hit-list.
    Returns the formatted report string.
    """
    if not findings:
        report_str = "No waste findings to report."
        _safe_print(report_str)
        return report_str

    # Ensure prioritized format with cost fields
    if "monthly_cost_inr" not in findings[0]:
        findings = prioritize_findings(findings)

    total_inr = sum(item.get("monthly_cost_inr", 0.0) for item in findings)
    total_usd = sum(item.get("monthly_cost_usd", 0.0) for item in findings)

    header_title = "CLOUD COST JANITOR - MONTHLY WASTE HIT-LIST (₹)"
    lines = [
        "=" * 85,
        f"{header_title:^85}",
        "=" * 85,
        f"{'Rank':<5} | {'Resource ID':<45} | {'Type':<14} | {'Monthly (₹)':<12} | {'Monthly ($)':<10}",
        "-" * 85
    ]

    for rank, item in enumerate(findings, 1):
        res_id = str(item.get("resource_id", "N/A"))
        if len(res_id) > 45:
            res_id = res_id[:42] + "..."
        res_type = str(item.get("type", "unknown"))
        cost_inr = float(item.get("monthly_cost_inr", 0.0))
        cost_usd = float(item.get("monthly_cost_usd", 0.0))

        lines.append(
            f"{rank:<5} | {res_id:<45} | {res_type:<14} | ₹{cost_inr:<11,.2f} | ${cost_usd:<9,.2f}"
        )

    lines.extend([
        "-" * 85,
        f"TOTAL ESTIMATED MONTHLY WASTE: ₹{total_inr:,.2f} INR (${total_usd:,.2f} USD)",
        "=" * 85
    ])

    report_str = "\n".join(lines)
    _safe_print(report_str)
    return report_str


def run_pricer(input_path="shared/sample_findings.json", output_path="shared/sample_prioritized_findings.json"):
    """
    Reads findings from input_path, computes costs, outputs prioritized_findings JSON,
    and prints report.
    """
    input_file = Path(input_path)
    if not input_file.exists():
        root_dir = Path(__file__).resolve().parent.parent
        alt_input = root_dir / input_path
        if alt_input.exists():
            input_file = alt_input

    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found at {input_path}")

    with open(input_file, "r", encoding="utf-8") as f:
        findings = json.load(f)

    prioritized = prioritize_findings(findings)

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(prioritized, f, indent=2)

    _safe_print(f"Successfully generated prioritized findings: {output_file}")
    generate_report(prioritized)
    return prioritized


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Cloud Cost Janitor - Pricing & Prioritization Module")
    parser.add_argument("pos_input", nargs="?", default=None, help="Positional input findings JSON path")
    parser.add_argument("pos_output", nargs="?", default=None, help="Positional output prioritized JSON path")
    parser.add_argument("--input", "-i", dest="flag_input", default=None, help="Input findings JSON path")
    parser.add_argument("--output", "-o", dest="flag_output", default=None, help="Output prioritized JSON path")

    args = parser.parse_args()
    inp = args.flag_input or args.pos_input or "findings.json"
    out = args.flag_output or args.pos_output or "prioritized_findings.json"
    run_pricer(inp, out)

