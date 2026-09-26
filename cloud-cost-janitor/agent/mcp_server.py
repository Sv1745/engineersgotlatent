"""
Cloud Cost Janitor - MCP Server
Exposes scanner, pricing, and teardown tools to TrueForge agent harness over Model Context Protocol (MCP).
"""

import argparse
from pathlib import Path
import subprocess
import sys

# Support MCP 2.x (MCPServer) and fallback to MCP 1.x (FastMCP)
try:
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    mcp = MCPServer("cloud-cost-janitor")
    teardown_annotations = ToolAnnotations(destructive_hint=True)
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        from fastmcp import FastMCP
    mcp = FastMCP("cloud-cost-janitor")
    try:
        from mcp.types import ToolAnnotations
        teardown_annotations = ToolAnnotations(destructive_hint=True)
    except Exception:
        teardown_annotations = {"destructiveHint": True}


def get_base_dir() -> Path:
    """
    Locates the project root directory containing scanner/ and pricing/ scripts.
    """
    here = Path(__file__).resolve().parent
    parent = here.parent

    # Check if parent is the project root containing scanner/ or pricing/
    if (parent / "scanner").exists() or (parent / "pricing").exists():
        return parent

    # Check if nested under cloud-cost-janitor
    if (parent / "cloud-cost-janitor" / "scanner").exists():
        return parent / "cloud-cost-janitor"

    # Check current working directory
    cwd = Path.cwd()
    if (cwd / "scanner").exists() or (cwd / "pricing").exists():
        return cwd
    if (cwd / "cloud-cost-janitor" / "scanner").exists():
        return cwd / "cloud-cost-janitor"

    return parent


@mcp.tool(
    name="run_scanner",
    description="Run the scanner script to detect wasted, orphaned, or idle AWS cloud resources in a given region.",
)
def run_scanner(region: str = "ap-south-1") -> str:
    """
    Runs: python scanner/scanner.py --region <region> --output findings.json
    Returns the standard output (stdout) of the script.
    """
    base_dir = get_base_dir()
    cmd = [
        sys.executable,
        "scanner/scanner.py",
        "--region",
        region,
        "--output",
        "findings.json",
    ]
    result = subprocess.run(
        cmd,
        cwd=base_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and not result.stdout and result.stderr:
        return f"[Error running scanner]: {result.stderr.strip()}"
    return result.stdout


@mcp.tool(
    name="run_pricer",
    description="Run the pricing module to calculate monthly wasted cost (USD & INR) and prioritize findings.",
)
def run_pricer(
    input_file: str = "findings.json",
    output_file: str = "prioritized_findings.json",
) -> str:
    """
    Runs: python pricing/pricer.py --input <input_file> --output <output_file>
    Returns the standard output (stdout) of the script.
    """
    base_dir = get_base_dir()
    cmd = [
        sys.executable,
        "pricing/pricer.py",
        "--input",
        input_file,
        "--output",
        output_file,
    ]
    result = subprocess.run(
        cmd,
        cwd=base_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and not result.stdout and result.stderr:
        return f"[Error running pricer]: {result.stderr.strip()}"
    return result.stdout


@mcp.tool(
    name="run_teardown",
    description="Simulate or execute resource teardown. Dry-run by default; requires confirmed=True and human approval for actual deletion.",
    annotations=teardown_annotations,
)
def run_teardown(
    resource_id: str,
    resource_type: str,
    dry_run: bool = True,
    confirmed: bool = False,
) -> str:
    """
    Runs: python pricing/teardown.py --resource-id <resource_id> --type <resource_type> [--dry-run] [--confirmed]
    Returns the standard output (stdout) of the script.
    Marked with destructiveHint: True to require human confirmation before execution.
    """
    base_dir = get_base_dir()
    cmd = [
        sys.executable,
        "pricing/teardown.py",
        "--resource-id",
        resource_id,
        "--type",
        resource_type,
    ]
    if dry_run:
        cmd.append("--dry-run")
    if confirmed:
        cmd.append("--confirmed")

    result = subprocess.run(
        cmd,
        cwd=base_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and not result.stdout and result.stderr:
        return f"[Error running teardown]: {result.stderr.strip()}"
    return result.stdout


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cloud Cost Janitor MCP Server")
    parser.add_argument(
        "--transport",
        choices=["streamable-http", "sse", "stdio"],
        default="streamable-http",
        help="MCP transport protocol (default: streamable-http)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind HTTP/SSE server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind HTTP/SSE server (default: 8000)",
    )

    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:  # streamable-http (default, mounts endpoint at /mcp)
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
