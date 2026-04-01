# FinOps Orchestrator — Top 3 Features & Required AWS Signals

**Document Type:** Strategic Planning Reference  
**Date:** 2026-03-28  
**Scope:** Features required to move from "no opportunities found" to actionable cost savings across both live-connected and advisory-only (file-based) deployment modes

---

## Executive Summary

The FinOps Orchestrator currently returns empty optimization results for most clients. Root cause analysis identified three systemic gaps:

1. The only existing AWS integrations (Trusted Advisor, Compute Optimizer, Cost Explorer) all have **hard prerequisites** that most clients don't meet: Business/Enterprise Support tier, manual opt-in, or 14+ days of history.
2. There is **no scheduled ingestion** — the database stays empty unless manually triggered.
3. The app has **no offline/advisory mode** — clients who are unwilling or unable to grant live AWS credentials get zero value.

The three features below address all three gaps and are designed to work in both **Connected Mode** (live AWS API access) and **Advisory Mode** (client provides exported files).

---

## Deployment Modes

### Connected Mode
Client grants read-only AWS IAM credentials. The app calls live AWS APIs to discover optimization opportunities in real time or on a schedule. Highest accuracy; requires trust and IAM configuration.

### Advisory Mode
Client provides exported files — no credentials required. The app analyzes:
- **CloudFormation / Terraform templates** (infrastructure-as-code)
- **CUR CSV exports** from the AWS Billing Console
- **AWS Config snapshots** (JSON export of resource inventory)
- **CloudWatch Logs Insights exports** (CSV metric exports)
- **Cost & Usage Report** direct S3 exports

Advisory Mode enables engagements where clients are not ready to grant API access, are in a pre-sales evaluation, or operate in regulated environments with strict credential controls.

---

## Feature 1: Infrastructure-as-Code (IaC) Architecture Analysis

### What It Does
Parses CloudFormation templates (`.yaml`, `.json`) and Terraform configurations (`.tf`, `.tfvars`) to identify cost-inefficient architecture patterns before or without cloud deployment. Useful for both pre-deployment audits and post-deployment reviews when clients can export their IaC.

### Why It's High Priority
IaC templates encode the **intended state** of infrastructure. A single sub-optimal instance type, missing auto-scaling policy, or hardcoded `MultiAZ: true` on a dev database can represent thousands of dollars per year. Unlike live-API analysis, IaC analysis requires zero credentials and can catch problems before they're deployed.

### Connected Mode Signals

| Signal | AWS API | Key Fields |
|--------|---------|------------|
| Actual running instance types vs. template-specified types | `ec2:DescribeInstances` | `InstanceType`, `State` |
| RDS Multi-AZ usage in non-production environments | `rds:DescribeDBInstances` | `MultiAZ`, `DBInstanceIdentifier` |
| NAT Gateway vs. VPC Endpoint routing opportunity | `ec2:DescribeNatGateways`, `ec2:DescribeVpcEndpoints` | `VpcId`, data transfer metrics |
| Load balancer idle state (no targets or no traffic) | `elasticloadbalancing:DescribeLoadBalancers` | `LoadBalancerArn`, CloudWatch `RequestCount` |
| Auto Scaling group min/max alignment | `autoscaling:DescribeAutoScalingGroups` | `MinSize`, `MaxSize`, `DesiredCapacity` |

### Advisory Mode Signals (File-Based)

| Input File | What to Extract | Opportunity |
|-----------|-----------------|-------------|
| CloudFormation `.yaml/.json` | `InstanceType`, `DBInstanceClass`, `MultiAZ`, `AllocatedStorage` | Over-provisioned types, dev Multi-AZ, oversized storage |
| Terraform `.tf` | `instance_type`, `db_instance_class`, `multi_az`, `allocated_storage` | Same as above |
| `terraform plan -out` JSON | Resource additions, modifications, destroys | Cost delta before apply |
| AWS Config snapshot JSON | `configuration.instanceType`, `configuration.dbInstanceClass` | Current vs. optimal sizing |

### Analysis Approach
- In Connected Mode: cross-reference template values against actual CloudWatch utilization
- In Advisory Mode: use LLM (Bedrock/Nova — already integrated) with a structured prompt to:
  1. Parse the template and extract all resource definitions
  2. Apply a rule-based cost pattern library (hardcoded thresholds: `t3.xlarge` on a Lambda-backed system = over-provisioned, etc.)
  3. Generate findings with specific line references from the original template

### Estimated Savings Signal Categories
- Right-sizing: instance type downgrades (30–60% per instance)
- Multi-AZ removal in non-prod: ~50% RDS cost reduction
- NAT Gateway → VPC Endpoint: eliminates NAT data processing charges ($0.045/GB)
- Idle load balancers: $16–$22/month per ALB, eliminated entirely

### Required IAM Permissions (Connected Mode — read-only)
```json
{
  "Effect": "Allow",
  "Action": [
    "ec2:DescribeInstances",
    "ec2:DescribeNatGateways",
    "ec2:DescribeVpcEndpoints",
    "autoscaling:DescribeAutoScalingGroups",
    "elasticloadbalancing:DescribeLoadBalancers",
    "rds:DescribeDBInstances",
    "cloudformation:GetTemplate",
    "cloudformation:ListStacks",
    "cloudformation:ListStackResources"
  ],
  "Resource": "*"
}
```

---

## Feature 2: CUR / Billing Export Deep Analysis

### What It Does
Mines the AWS Cost and Usage Report (CUR) for patterns that reveal waste, anomalies, and optimization opportunities. The app already has a 376-column Athena query template library — this feature fully activates it with both live Athena queries and uploaded CUR CSV exports.

### Why It's High Priority
The CUR is the **single most comprehensive billing signal** AWS provides. It contains per-resource, per-hour cost breakdowns including Reserved Instance and Savings Plan amortization, data transfer charges, idle resource markers, and tag data. Most clients already have CUR enabled; many have it in S3 but are not analyzing it.

### Connected Mode Signals

| Signal | Source | Description |
|-------|--------|-------------|
| RI/SP coverage rate | `ce:GetReservationCoverage`, `ce:GetSavingsPlansCoverage` | % of on-demand hours that could be covered |
| RI/SP utilization rate | `ce:GetReservationUtilization`, `ce:GetSavingsPlansUtilization` | % of purchased capacity actually being used |
| Expiring RIs | `ec2:DescribeReservedInstances` | RIs expiring within 30 days with no renewal plan |
| RI purchase recommendations | `ce:GetReservationPurchaseRecommendation` | CE-modeled 1-yr and 3-yr payback calculations |
| Savings Plans recommendations | `ce:GetSavingsPlansPurchaseRecommendation` | Compute SP vs. EC2 Instance SP comparison |
| Anomaly detection | `ce:GetAnomalyDetectors`, `ce:GetAnomalies` | Cost spikes vs. baseline |
| Service cost breakdown | `ce:GetCostAndUsage` | Current month vs. prior 3 months by service |

### Advisory Mode Signals (File-Based)

| CUR Column Group | Signal Extracted | Opportunity |
|-----------------|-----------------|-------------|
| `line_item_usage_type`, `line_item_line_item_type` | `BoxUsage`, `DataTransfer`, `EBS:VolumeUsage` breakdowns | Identify dominant cost drivers |
| `reservation_*` columns (12 columns) | RI amortized cost, unused RI hours, coverage gaps | RI waste and coverage opportunities |
| `savings_plan_*` columns (8 columns) | SP amortized cost, unused SP commitment | SP utilization waste |
| `line_item_unblended_cost` + `product_region` | Cross-region data transfer costs | Consolidate resources to single region |
| `line_item_resource_id` + `line_item_usage_amount` | Zero-usage resources with non-zero cost | Idle resource identification |
| `pricing_term` = `OnDemand` on `db.r5.large`+ | On-demand DB instances that are always running | RI purchase opportunity |
| `product_servicecode` + time-of-day patterns | Batch workloads running 24/7 | Scheduling opportunity |

### CUR Columns Already in Template Library
The app already has query templates for: `line_item_product_code`, `line_item_usage_type`, `line_item_line_item_type`, `line_item_unblended_cost`, `line_item_blended_cost`, `reservation_amortized_upfront_fee_for_billing_period`, `reservation_unused_amortized_upfront_fee_for_billing_period`, `savings_plan_savings_plan_effective_cost`, `product_region`, `resource_tags_*` — these cover all of the above signals.

### Required IAM Permissions (Connected Mode — read-only)
```json
{
  "Effect": "Allow",
  "Action": [
    "ce:GetCostAndUsage",
    "ce:GetReservationCoverage",
    "ce:GetReservationUtilization",
    "ce:GetReservationPurchaseRecommendation",
    "ce:GetSavingsPlansCoverage",
    "ce:GetSavingsPlansUtilization",
    "ce:GetSavingsPlansPurchaseRecommendation",
    "ce:GetAnomalyDetectors",
    "ce:GetAnomalies",
    "ec2:DescribeReservedInstances",
    "ec2:DescribeReservedInstancesOfferings"
  ],
  "Resource": "*"
}
```

> **Note:** `ce:*` APIs require at least 14 days of EC2 usage history. In new accounts, seed with manual CUR CSV upload via Advisory Mode.

---

## Feature 3: Tagging & Cost Attribution Advisor

### What It Does
Analyzes resource tagging completeness and consistency to enable cost allocation by team, project, environment, and application. Identifies untagged or inconsistently tagged resources that are generating cost but cannot be attributed.

### Why It's High Priority
Tagging is a prerequisite for meaningful showback/chargeback reports — the most common deliverable in a FinOps engagement. Without attribution, clients cannot hold teams accountable for cloud spend. This feature requires **no special AWS permissions** beyond billing data and is fully achievable in Advisory Mode from CUR CSV alone.

### Connected Mode Signals

| Signal | AWS API | Key Fields |
|-------|---------|------------|
| Untagged resources by service | `resourcegroupstaggingapi:GetResources` | `ResourceARN`, `Tags` |
| Tag key coverage by resource type | `resourcegroupstaggingapi:GetTagKeys` | All tag keys in use across account |
| Tag compliance per policy | `resourcegroupstaggingapi:GetComplianceSummary` | Compliant/non-compliant resource counts |
| Cost per tag value | `ce:GetCostAndUsage` with `GroupBy: [{Type: TAG, Key: "Environment"}]` | $ by team/project/env |
| S3 bucket cost with no owner tag | `ce:GetCostAndUsage` filtered by `ResourceId` | Orphaned cost centers |

### Advisory Mode Signals (File-Based)

| CUR Column | Signal | Opportunity |
|-----------|--------|-------------|
| `resource_tags_user_environment` | Missing or non-standard values (`prod`, `dev`, `staging` vs. freeform) | Standardize for cost allocation |
| `resource_tags_user_project` | Absence in rows with high `line_item_unblended_cost` | Identify unattributed spend |
| `resource_tags_user_owner` | Absence on high-cost resources | Find ownerless spend |
| `resource_tags_user_team` | Coverage rate across total spend | Calculate % of spend with attribution |
| `line_item_resource_id` + zero tags + high cost | Resources > $X/month with no tags at all | Priority tagging targets |

### Tag Governance Analysis Output
For each client the feature should produce:
1. **Tag coverage score** — % of total monthly spend that has all required tags
2. **Top 10 untagged cost drivers** — resources with the highest unattributed spend
3. **Tag key inconsistency report** — e.g., `env` vs. `Environment` vs. `environment` used across resources
4. **Recommended tag taxonomy** — standardized keys based on client's existing patterns
5. **Enforcement recommendation** — AWS Config rule or Tag Policy to prevent future untagged launches

### Required IAM Permissions (Connected Mode — read-only)
```json
{
  "Effect": "Allow",
  "Action": [
    "tag:GetResources",
    "tag:GetTagKeys",
    "tag:GetTagValues",
    "tag:GetComplianceSummary",
    "ce:GetCostAndUsage",
    "config:DescribeConfigurationRecorders",
    "config:GetComplianceDetailsByConfigRule",
    "organizations:ListTagsForResource"
  ],
  "Resource": "*"
}
```

---

## Signal Priority Matrix

| Signal | Connected Mode | Advisory Mode | Prerequisite | Estimated Impact |
|--------|---------------|--------------|--------------|-----------------|
| Idle EC2 (CPU < 5%) | CloudWatch GetMetricData | CloudWatch Logs Insights export | None | High — eliminates 100% of idle cost |
| RI/SP coverage gap | Cost Explorer APIs | CUR `reservation_*` columns | 14-day history | Very High — 30–72% discount vs. on-demand |
| Expiring RIs | ec2:DescribeReservedInstances | CUR `reservation_expiration_date` | None | High — prevents unexpected on-demand surge |
| IaC right-sizing | Cross-ref template + CloudWatch | Template file upload + LLM | None | Medium-High — 20–60% per instance |
| Multi-AZ dev/test removal | RDS DescribeDBInstances | CloudFormation template | None | Medium — ~50% of RDS cost in non-prod |
| Untagged resources | Resource Groups Tagging API | CUR `resource_tags_*` null check | None | Low-direct / High-strategic |
| EBS unattached volumes | ec2:DescribeVolumes | AWS Config snapshot | None | Low per unit, accumulates silently |
| S3 no lifecycle policy | s3:GetBucketLifecycleConfiguration | S3 Storage Lens export | None | Medium on large buckets |
| gp2 → gp3 migration | ec2:DescribeVolumes | CUR `product_volume_api_name` | None | 20% savings, zero downtime |
| Cost anomaly detection | ce:GetAnomalies | CUR spend trend analysis | 14-day history | Variable — catches runaway spend |
| NAT Gateway elimination | ec2:DescribeNatGateways + CloudWatch | CloudFormation VPC resource | None | Medium — $0.045/GB data charges |

---

## Consolidated Minimum IAM Policy (Connected Mode — All Features)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "FinOpsReadOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes",
        "ec2:DescribeSnapshots",
        "ec2:DescribeNatGateways",
        "ec2:DescribeVpcEndpoints",
        "ec2:DescribeReservedInstances",
        "ec2:DescribeReservedInstancesOfferings",
        "rds:DescribeDBInstances",
        "elasticloadbalancing:DescribeLoadBalancers",
        "lambda:ListFunctions",
        "autoscaling:DescribeAutoScalingGroups",
        "s3:ListAllMyBuckets",
        "s3:GetBucketLifecycleConfiguration",
        "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics",
        "ce:GetCostAndUsage",
        "ce:GetReservationCoverage",
        "ce:GetReservationUtilization",
        "ce:GetReservationPurchaseRecommendation",
        "ce:GetSavingsPlansCoverage",
        "ce:GetSavingsPlansUtilization",
        "ce:GetSavingsPlansPurchaseRecommendation",
        "ce:GetAnomalyDetectors",
        "ce:GetAnomalies",
        "cloudformation:GetTemplate",
        "cloudformation:ListStacks",
        "cloudformation:ListStackResources",
        "tag:GetResources",
        "tag:GetTagKeys",
        "tag:GetTagValues",
        "tag:GetComplianceSummary",
        "config:DescribeConfigurationRecorders",
        "config:GetComplianceDetailsByConfigRule"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## Implementation Notes

### Existing Infrastructure to Leverage
- **AWS Bedrock / Nova LLM** (`backend/services/llm_service.py`) — already integrated; use for IaC template parsing in Advisory Mode
- **ChromaDB vector store** (`backend/services/vector_store.py`) — already wired; can store parsed template chunks for RAG-based querying
- **Athena CUR template library** (`backend/services/athena_cur_templates.py`) — 376 columns already mapped; apply same logic to uploaded CSV
- **psycopg2 + PostgreSQL** — all new services must follow the `OpportunitiesService(organization_id=uuid)` pattern
- **Celery scheduler** (in `requirements.txt`) — configure with `CELERY_BROKER_URL=redis://...` for nightly ingestion runs

### File Upload Endpoints to Build (Advisory Mode)
The following API endpoints do not yet exist and are required for Advisory Mode:

| Endpoint | Accepts | Processing |
|---------|---------|-----------|
| `POST /api/v1/ingest/iac` | `.yaml`, `.json`, `.tf` files | LLM parsing → structured findings → OpportunitiesService |
| `POST /api/v1/ingest/cur-csv` | CUR CSV export from S3 or Billing Console | CSV parsing → same analysis as Athena queries |
| `POST /api/v1/ingest/config-snapshot` | AWS Config snapshot JSON | Resource inventory → tag coverage + sizing analysis |

### Advisory Mode UI Requirements
- File upload component (drag-and-drop, multiple files)
- Upload progress indicator
- Per-file processing status
- Toggle in UI to switch between Connected Mode and Advisory Mode view

---

## What Already Works (Do Not Rebuild)

The following are already implemented and wired into `POST /api/v1/opportunities/ingest`:

| Feature | Service File | Notes |
|---------|-------------|-------|
| CloudWatch idle detection | `cloudwatch_optimization_signals.py` | EC2, RDS, ELB, Lambda; no prerequisites |
| RI/SP coverage + utilization | `ri_savings_plans_signals.py` | 7 Cost Explorer API calls |
| Storage waste | `storage_optimization_signals.py` | Unattached EBS, orphaned snapshots, gp2→gp3, S3 lifecycle |
| Trusted Advisor | `aws_optimization_signals.py` | Requires Business/Enterprise Support |
| Compute Optimizer | `aws_optimization_signals.py` | Requires manual opt-in per account |
| Nightly scheduler | `worker/tasks.py` + `worker/__init__.py` | Celery Beat at 2 AM UTC; needs Redis |

---

*No implementation should begin on Advisory Mode features without reviewing file format support requirements and the client-facing upload UX with the product team.*
