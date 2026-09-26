# ☁️ Cloud Cost Janitor — Infrastructure Waste Audit Report
**Generated At:** `2026-09-26 09:35:09 UTC` | **Target Region:** `ap-south-1` | **Status:** `Audit Complete`

---
### 📊 Executive Summary
- **Total Flagged Waste Assets:** **3**
- **Total Monthly Waste:** **INR 9,256.21** (`$96.60 USD`)
- **Projected Annual Waste:** **INR 111,074.52** (`$1,159.20 USD`)
- **Blast Radius Simulation:** ✅ **100% Safe** (AWS Native `DryRun=True` Passed)
- **Safety Isolation Tag:** `Environment: hackathon-demo` strictly enforced

---
### 🎯 Cost-Ranked Waste Hit-List
| Rank | Resource ID | Type | Monthly Waste (INR) | Monthly Waste ($) | Technical Rationale & Evidence |
| :---: | :--- | :---: | :---: | :---: | :--- |
| 1 | `i-0221764b3c3d2e4e5` | `ec2_instance` | INR 6,994.86 | $73.00 | Instance 'janitor-demo-idle-ec2' (ID: i-0221764b3c3d2e4e5) in 'hackathon-demo' exhibiting sustained sub-5% CPU with 0 network bursts. Evaluated as idle demo worker, distinct from a warm failover standby. |
| 2 | `vol-0da631f7e0f15ce9a` | `ebs_volume` | INR 1,916.40 | $20.00 | Volume 'janitor-demo-orphan-volume' (ID: vol-0da631f7e0f15ce9a) completely detached in 'hackathon-demo' environment with 0 IOPS, incurring unallocated gp3 block storage charges. |
| 3 | `eipalloc-0cf761ac03aee6a47` | `elastic_ip` | INR 344.95 | $3.60 | Public IPv4 'janitor-demo-orphan-eip' (ID: eipalloc-0cf761ac03aee6a47) unassociated with any ENI or instance in 'hackathon-demo', incurring AWS idle IPv4 hourly penalty. |

---
### 🛡️ Safety & Governance Verification
- **Blast Radius Check:** All destructive actions simulated using AWS `DryRun=True` to prevent accidental disruption.
- **Human-in-the-Loop Policy:** Deletion strictly gated behind explicit TrueForge approval.
- **Zero Production Touch:** Workloads lacking `Environment=hackathon-demo` are strictly immutable.