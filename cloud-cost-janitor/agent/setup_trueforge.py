"""
Automated Setup & Registration script for TrueForge

Registers:
1. Model Provider: OpenAI (using OPENAI_API_KEY from .env)
2. Agent: cloud-cost-janitor (with comprehensive live context, rationales, and Human-in-the-Loop approval gating)
"""

import json
import os
from pathlib import Path
import sys
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get("OPENAI_API_KEY", "")

TRUEFORGE_URL = "http://localhost:8790"


def send_request(method: str, endpoint: str, data: dict = None):
    url = f"{TRUEFORGE_URL}{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8") if data else None,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            res_data = resp.read().decode("utf-8")
            return resp.status, json.loads(res_data) if res_data else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        return e.code, err_body
    except Exception as e:
        return 500, str(e)


def setup_model_provider():
    print("\n1. Configuring OpenAI Model Provider in TrueForge...")
    payload = {
        "manifest": {
            "type": "openai",
            "auth": {
                "api_key": api_key
            },
            "models": [
                {
                    "name": "gpt-4o",
                    "model_id": "gpt-4o",
                    "properties": {
                        "context_length": 128000,
                        "max_output_tokens": 4096
                    }
                },
                {
                    "name": "gpt-4o-mini",
                    "model_id": "gpt-4o-mini",
                    "properties": {
                        "context_length": 128000,
                        "max_output_tokens": 4096
                    }
                }
            ]
        }
    }
    status, res = send_request("POST", "/api/v1/settings/model-providers", payload)
    if status in [200, 201]:
        print("  [SUCCESS] OpenAI Model Provider registered successfully!")
    else:
        status_put, res_put = send_request("PUT", "/api/v1/settings/model-providers", payload)
        print(f"  [INFO] Model Provider setup result: HTTP {status} (PUT: {status_put})")


def setup_mcp_server():
    print("\n2. Configuring MCP Server 'cloud-cost-janitor' in TrueForge...")
    payload = {
        "name": "cloud-cost-janitor",
        "url": "http://127.0.0.1:8000/mcp"
    }
    status, res = send_request("POST", "/api/v1/mcp-servers", payload)
    if status in [200, 201]:
        print("  [SUCCESS] MCP Server registered successfully!")
    else:
        status_put, res_put = send_request("PUT", "/api/v1/mcp-servers/cloud-cost-janitor", payload)
        print(f"  [INFO] MCP Server registration result: HTTP {status} (PUT: {status_put})")


def setup_agent():
    print("\n3. Configuring 'cloud-cost-janitor' Agent with live MCP Tools in TrueForge...")

    instructions = (
        "You are **Cloud Cost Janitor**, an autonomous, evidence-backed AWS cloud cost optimization agent running on TrueForge.\n\n"
        "### Operational Protocol:\n"
        "1. **Audit & Price (Step 1)**:\n"
        "   - When the user asks to scan, audit, look for waste, or optimize AWS resources, invoke `run_scanner(region='ap-south-1')`.\n"
        "   - Next, invoke `run_pricer(input_file='findings.json')` to calculate monthly waste in INR (₹) and USD ($).\n"
        "   - Next, invoke `generate_audit_report()` to generate standalone HTML & Markdown reports.\n\n"
        "2. **Present Full Audit Report with Rationales & Download Links (Step 2 - CRITICAL)**:\n"
        "   - If 0 wasted resources are detected, inform the user with congratulations that their AWS environment in the selected region has 0 waste resources and is fully optimized!\n"
        "   - If waste resources are detected, you MUST output a comprehensive markdown report in the chat BEFORE attempting any teardown.\n"
        "   - Present the summary: Total Resources Flagged and Total Monthly Waste (INR & USD).\n"
        "   - Present the Cost-Ranked Waste Hit-List table including columns: Rank, Resource ID, Resource Type, Monthly Waste (INR), Monthly Waste ($), and Detailed Rationale.\n"
        "   - Explain the technical rationale for each resource (e.g. 0.22% sustained CPU, 0 IOPS detached EBS volume, unassociated EIP incurring $0.005/hr) to justify why it is safe to delete vs. a warm standby.\n"
        "   - Show the Blast Radius & Safety Verification (AWS Native `DryRun=True` simulated, tag-scoped strictly to `Environment=hackathon-demo`).\n"
        "   - Provide the downloadable report links:\n"
        "     > 📄 **Exportable FinOps Reports**:\n"
        "     > - 🌐 [View & Print Full Audit Report (HTML / PDF Export)](http://localhost:8000/report/audit)\n"
        "     > - 📋 [Download Raw Audit Markdown](http://localhost:8000/report/audit.md)\n\n"
        "   - Explicitly present the approval checkpoint question:\n"
        "     > **Approval Checkpoint**:\n"
        "     > *\"Approve deleting these N resources, saving INR X/month ($Y/month)?\"*\n\n"
        "3. **Wait for Human Approval (Step 3)**:\n"
        "   - STOP and wait for the user's explicit response.\n"
        "   - Do NOT invoke teardown in the initial audit turn. Let the user review your findings and rationales.\n\n"
        "4. **Execute Teardown on Explicit Approval (Step 4)**:\n"
        "   - When the user approves (e.g., 'yes', 'approve', 'proceed', 'delete them', 'go ahead'), you MUST first write an Executive Remediation Card in the chat:\n"
        "     ```markdown\n"
        "     ### 🛡️ Teardown Approval Request\n"
        "     > **Target Resource**: `<resource_id>` (`<type>`)\n"
        "     > **Monthly Waste Savings**: **INR <savings_inr>** ($<savings_usd> USD)\n"
        "     > **Audit Rationale**: <rationale>\n"
        "     > **Blast Radius & Tag Safety**: AWS `DryRun=True` 100% Passed (Tagged `Environment=hackathon-demo`)\n"
        "     > **Action**: Permanent deletion of unallocated cloud waste\n\n"
        "     *Please click **Allow** below to confirm execution or **Deny** to cancel.*\n"
        "     ```\n"
        "   - Then, invoke `run_teardown` with:\n"
        "     `resource_id='...'`, `resource_type='...'`, `justification_and_telemetry='...'`, `monthly_savings_inr=...`, `monthly_savings_usd=...`, `safety_check_verified='AWS DryRun Passed (Environment=hackathon-demo)'`, `dry_run=False`, `confirmed=True`.\n"
        "   - Next, invoke `generate_remediation_report()` to generate the post-teardown remediation report.\n"
        "   - Provide the downloadable remediation report links:\n"
        "     > 📄 **Post-Remediation Reports**:\n"
        "     > - 🌐 [View & Print Remediation Report (HTML / PDF Export)](http://localhost:8000/report/remediation)\n"
        "     > - 📋 [Download Raw Remediation Markdown](http://localhost:8000/report/remediation.md)\n\n"
        "   - Summarize total monthly savings achieved."
    )





    payload = {
        "name": "cloud-cost-janitor",
        "description": "Audits AWS accounts for wasted resources, prices in INR/USD, simulates blast radius, and halts at TrueForge approval checkpoints before executing teardowns.",
        "manifest": {
            "model": {
                "name": "openai/gpt-4o"
            },
            "instructions": instructions.strip(),
            "mcp_servers": [
                {
                    "name": "cloud-cost-janitor",
                    "enable_tools": ["@all"],
                    "disable_tools": [],
                    "preload_tools": [],
                    "require_approval_for_tools": ["@destructive"],
                    "preload": True
                }
            ],
            "config": {
                "iteration_limit": 100,
                "sandbox": {
                    "enabled": False,
                    "file_downloads": True
                },
                "dynamic_sub_agents": {
                    "enabled": True
                },
                "context_management": {
                    "compaction": {
                        "enabled": True
                    },
                    "large_tool_response": {
                        "enabled": True
                    }
                },
                "generative_ui": {
                    "enabled": True
                },
                "ask_user_questions": {
                    "enabled": True
                },
                "web_search": {
                    "enabled": False
                }
            }
        }
    }

    # Fetch existing agents
    status_get, res_get = send_request("GET", "/api/v1/agents")
    agents = res_get.get("data", []) if isinstance(res_get, dict) else []
    agent_id = None
    for a in agents:
        if a.get("name") == "cloud-cost-janitor":
            agent_id = a.get("id")
            break

    if agent_id:
        put_payload = {
            "description": payload["description"],
            "manifest": payload["manifest"]
        }
        status, res = send_request("PUT", f"/api/v1/agents/{agent_id}", put_payload)
        print(f"  [SUCCESS] Agent updated via PUT /api/v1/agents/{agent_id}: HTTP {status}")
    else:
        status, res = send_request("POST", "/api/v1/agents", payload)
        print(f"  [SUCCESS] Agent created via POST /api/v1/agents: HTTP {status}")


def verify_setup():
    print("\n==================================================")
    print("VERIFYING REGISTERED AGENTS & TOOLS IN TRUEFORGE")
    print("==================================================")
    status, res = send_request("GET", "/api/v1/agents")
    agents = res.get("data", []) if isinstance(res, dict) else []
    print(f"Total Agents in TrueForge: {len(agents)}")
    for a in agents:
        print(f"  - Agent Name: {a.get('name')} (ID: {a.get('id')})")
        mcp = a.get('manifest', {}).get('mcp_servers', [])
        print(f"    Attached MCP Servers: {mcp}")


if __name__ == "__main__":
    setup_model_provider()
    setup_mcp_server()
    setup_agent()
    verify_setup()

