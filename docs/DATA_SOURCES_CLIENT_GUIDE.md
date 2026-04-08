# Data Sources — Client Connection Guide

**Audience:** FinOps teams, consultants, and IT administrators onboarding a client  
**Last updated:** April 2026

---

## Overview

The Data Sources feature supports two connection modes. Clients can use either mode or both simultaneously.

| Mode | How it works | Requires cloud credentials? | Best for |
|---|---|---|---|
| **Advisory / Upload** | Client exports a billing file and uploads it manually | No | Regulated environments, pre-sales evaluations, quick start |
| **Connected (Live)** | App uses API credentials to pull data automatically on a schedule | Yes — read-only | Ongoing monitoring, daily/weekly refresh |
| **S3 Bucket Integration** | Client delivers billing files to an S3 bucket; app watches and ingests automatically | Minimal (S3 access only) | High-volume / automated pipelines |

---

## Mode 1: Advisory Upload (File Upload)

### What the client does

1. Go to their cloud billing console and **download the monthly billing export** as a CSV or CSV.GZ file.
2. In the app, go to **Data Sources → Setup** and register a new source (takes 2 minutes).
3. Go to **Data Sources → Upload**, select the registered source, and click **Upload billing file**.
4. The app reads every row, converts it to a unified format, and stores the results.
5. **Run History** shows how many rows were read, how many normalized successfully, and any errors.

### What files are accepted

| Cloud Provider | File format | How to export |
|---|---|---|
| **AWS** | CUR CSV or CSV.GZ | AWS Console → Billing → Cost & Usage Reports → Download |
| **Azure** | CSV from Cost Management | Azure Portal → Cost Management + Billing → Export |
| **GCP** | CSV from Cloud Billing | GCP Console → Billing → Reports → Export |
| **Generic** | Any CSV with date, cost, service columns | Any billing tool that can export CSV |

### What happens after upload

```
Client uploads file
       ↓
App validates: checks required columns exist
       ↓
App normalizes: converts provider-specific columns → unified schema
 (provider, service, region, account, month, cost_USD, currency)
       ↓
Normalized rows stored in database
       ↓
AI chat can now answer: "What did we spend on Azure last month?"
       ↓
Run History records: rows_read, rows_normalized, errors, timestamp
```

### Limitations of Advisory Mode

- Data is only as fresh as the last uploaded file — no automatic refresh
- Historical data requires uploading one file per billing period
- Does not detect real-time anomalies (only pattern analysis on uploaded data)

---

## Mode 2: Live Connected Mode

Connected mode lets the app call cloud APIs directly on the client's behalf. The app polls for new billing data automatically (daily or weekly) without manual file uploads.

### What credentials are needed (per provider)

---

### AWS — Connected Mode

#### What the client needs to provide

| Credential | Description |
|---|---|
| `AWS Access Key ID` | Belongs to a read-only IAM user created specifically for this app |
| `AWS Secret Access Key` | Paired with the Access Key ID |
| `AWS Account ID` | The 12-digit account number |
| `AWS Region` | Primary region where CUR is stored (usually `us-east-1`) |

**Alternative (more secure):** Provide an **IAM Role ARN** that this app can assume via cross-account role delegation, instead of static keys.

#### Step-by-step: creating the IAM user / role

**Step 1 — Log in to AWS Console → IAM**

**Step 2 — Create a new IAM policy**  
Name it `aasmaa-readonly-policy`

Paste the following permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "FinOpsReadOnly",
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
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes",
        "ec2:DescribeSnapshots",
        "ec2:DescribeNatGateways",
        "ec2:DescribeVpcEndpoints",
        "ec2:DescribeReservedInstances",
        "rds:DescribeDBInstances",
        "elasticloadbalancing:DescribeLoadBalancers",
        "lambda:ListFunctions",
        "autoscaling:DescribeAutoScalingGroups",
        "s3:ListAllMyBuckets",
        "s3:GetBucketLifecycleConfiguration",
        "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics",
        "cloudformation:GetTemplate",
        "cloudformation:ListStacks",
        "cloudformation:ListStackResources",
        "tag:GetResources",
        "tag:GetTagKeys",
        "tag:GetTagValues"
      ],
      "Resource": "*"
    }
  ]
}
```

**Step 3 — Create an IAM user**  
- IAM → Users → Create user
- Username: `aasmaa-readonly`
- Access type: **Programmatic access only** (no console login)
- Attach the policy you just created

**Step 4 — Download credentials**  
- After creation, download the Access Key ID and Secret Access Key CSV
- This is the only time the Secret Key is visible — store it securely

**Step 5 — Enter credentials in the app**  
- Data Sources → Setup → New Source → Provider: AWS CUR → Connection Mode: Connected
- Enter Access Key ID, Secret Access Key, Account ID, Region

#### Security note: IAM Role (recommended over user keys)

Instead of creating a user with long-lived keys, create a cross-account IAM role:

```
Client AWS Account
  └── IAM Role: aasmaa-cross-account-reader
        └── Trust policy: Allow aasmaa-app-account (our AWS account) to assume this role
        └── Permissions: same policy above
```

The client provides the Role ARN (`arn:aws:iam::ACCOUNT_ID:role/aasmaa-cross-account-reader`). The app assumes the role temporarily — no static secrets are stored.

#### AWS prerequisites checklist

- [ ] **CUR enabled**: AWS Console → Billing → Cost & Usage Reports → at least one report exists
  - Must be Standard or Legacy CUR format
  - Ideally with resource-level detail enabled
- [ ] **14+ days of billing history** for Cost Explorer recommendations (RI/SP analysis)
- [ ] **Trusted Advisor full checks**: requires AWS Business or Enterprise Support tier (not free tier)
- [ ] **Compute Optimizer enabled**: must be manually activated at AWS Console → Compute Optimizer → Enable
- [ ] **CloudWatch metrics**: available on all accounts — no prerequisites

---

### Azure — Connected Mode

#### What the client needs to provide

| Credential | Description |
|---|---|
| `Tenant ID` | Azure Entra ID (formerly Azure AD) directory/tenant GUID |
| `Client ID` | Application (client) ID from the App Registration |
| `Client Secret` | Secret value from the App Registration |
| `Subscription ID` | Azure subscription to analyze |

#### Step-by-step: creating the App Registration

**Step 1 — Azure Portal → Entra ID → App registrations → New registration**
- Name: `aasmaa-finops-reader`
- Supported account types: Single tenant
- No redirect URI needed
- Click Register

**Step 2 — Note the identifiers**  
From the Overview page, copy:
- `Application (client) ID` — this is the `Client ID`
- `Directory (tenant) ID` — this is the `Tenant ID`

**Step 3 — Create a client secret**  
- App Registration → Certificates & secrets → New client secret
- Description: `aasmaa-finops`
- Expiry: 24 months (or per your security policy)
- Copy the **Value** immediately (it won't be shown again)

**Step 4 — Assign the Billing Reader role**  
- Azure Portal → Subscriptions → Select the subscription
- Access control (IAM) → Add role assignment
- Role: **Billing Reader**
- Member: the App Registration created above (`aasmaa-finops-reader`)

**Step 5 — For multi-subscription coverage**  
Repeat Step 4 for each subscription. Or assign at Management Group level for all subscriptions at once.

**Step 6 — Enter credentials in the app**  
- Data Sources → Setup → New Source → Provider: Azure Export → Connection Mode: Connected
- Enter Tenant ID, Client ID, Client Secret, Subscription ID

#### Azure prerequisites checklist

- [ ] Cost Management enabled (included in most Azure subscriptions by default)
- [ ] App Registration created in the correct Entra ID tenant
- [ ] Billing Reader role assigned — not Contributor or Owner (read-only is sufficient)
- [ ] Cost export configured if using advisory mode as fallback: Azure Portal → Cost Management → Exports

---

### GCP — Connected Mode

#### What the client needs to provide

| Credential | Description |
|---|---|
| `Service Account JSON key` | JSON key file downloaded from Google Cloud Console |
| `Project ID` | GCP project that owns the billing data |
| `Billing Account ID` | Found in GCP Console → Billing → Billing accounts |

#### Step-by-step: creating the service account

**Step 1 — GCP Console → IAM & Admin → Service Accounts → Create Service Account**
- Name: `aasmaa-finops-reader`
- Description: Read-only access for FinOps cost analysis
- Click Create and continue

**Step 2 — Assign roles**  
Add the following roles:
- `Billing Account Viewer` — view billing costs
- `BigQuery Data Viewer` — if billing export goes to BigQuery
- `Storage Object Viewer` — if billing export goes to GCS bucket

**Step 3 — Create a JSON key**  
- Service account → Keys → Add key → Create new key → JSON
- Download the key file (this is the service account JSON key)

**Step 4 — Enable Billing Export (if not already done)**  
GCP Console → Billing → Billing export → Enable detailed usage cost export to BigQuery or GCS

**Step 5 — Enter credentials in the app**  
- Data Sources → Setup → New Source → Provider: GCP Billing → Connection Mode: Connected
- Upload the service account JSON key file, enter Project ID and Billing Account ID

#### GCP prerequisites checklist

- [ ] Cloud Billing API enabled in the project
- [ ] Billing export configured to BigQuery or GCS
- [ ] Service account key generated (minimum: Billing Account Viewer)
- [ ] If using BigQuery export: BigQuery Data Viewer role on the billing dataset

---

## Mode 3: S3 Bucket Integration

This is the recommended path for clients who want automation without granting full live API credentials. Billing files are delivered to an S3 bucket, and the app watches and ingests them automatically.

### Option A: Client delivers to their own S3 bucket (Pull model)

The client sets up AWS to automatically deliver their CUR files to an S3 bucket in their account. They then grant our app cross-account read access to that bucket.

```
AWS Billing Service
    ↓ (automatic delivery — hourly or daily)
Client S3 Bucket
  s3://client-bucket/cost-exports/
    ↓ (cross-account read via IAM role or bucket policy)
aasmaa App (polls every 6 hours, ingests new files)
    ↓
Database → Normalized cost records
    ↓
AI Analysis
```

#### Setup steps (Option A)

**Step 1 — Enable CUR delivery in the client's AWS account**

AWS Console → Billing → Cost & Usage Reports → Create report:
- Report name: `aasmaa-cost-export`
- Include resource IDs: Yes
- Time granularity: Hourly or Daily
- Report versioning: Overwrite existing report
- S3 bucket: choose or create `<client-org>-finops-exports`
- S3 prefix: `cost-exports/`
- Format: CSV or Parquet

**Step 2 — Grant cross-account read access**

Client adds a bucket policy granting our app's AWS account read access:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowAasmaaCrossAccountRead",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::AASMAA_APP_AWS_ACCOUNT_ID:role/aasmaa-ingestion-role"
      },
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::client-bucket",
        "arn:aws:s3:::client-bucket/cost-exports/*"
      ]
    }
  ]
}
```

Replace `AASMAA_APP_AWS_ACCOUNT_ID` with the AWS account ID provided during onboarding.

**Step 3 — Register the source in the app**
- Data Sources → Setup → New Source → Provider: AWS CUR → Connection Mode: S3 Pull
- Enter: S3 bucket name, S3 prefix, AWS Region
- Optionally: poll interval (e.g., every 6 hours)

---

### Option B: Client pushes to our hosted S3 bucket (Push model)

We provision a dedicated S3 prefix for the client. The client uses the AWS CLI, SDK, or an S3 Transfer automation to push their billing exports to our bucket.

```
Client billing export (local file, or automated from their S3)
    ↓ (client pushes using provided credentials)
Our S3 Bucket: s3://aasmaa-ingest/org-<CLIENT_ORG_ID>/
    ↓ (S3 event triggers Lambda → backend ingest job)
Database → Normalized cost records
    ↓
AI Analysis
```

#### Setup steps (Option B)

**What we provide to the client:**
- S3 bucket name and prefix: `s3://aasmaa-ingest/org-<THEIR_ORG_ID>/`
- Scoped IAM credentials (Write-only to their prefix, no read access to other orgs):
  ```json
  {
    "Action": ["s3:PutObject"],
    "Resource": "arn:aws:s3:::aasmaa-ingest/org-CLIENT_ORG_ID/*"
  }
  ```
- Access Key ID + Secret (write-only, scoped to their prefix only)

**What the client does:**

Push manually via AWS CLI:
```bash
aws s3 cp my-billing-export.csv \
  s3://aasmaa-ingest/org-<CLIENT_ORG_ID>/ \
  --profile finops-upload
```

Or automate from their S3 bucket using an S3 replication rule or Lambda trigger:
```bash
# Automated: replicate new CUR files from their bucket to ours
aws s3 sync \
  s3://client-bucket/cost-exports/ \
  s3://aasmaa-ingest/org-<CLIENT_ORG_ID>/ \
  --profile finops-upload
```

When a new file lands in the prefix, an S3 event notification triggers automatic ingestion.

---

## Deciding Which Mode to Use

```
Does the client agree to share read-only API credentials?
├── YES → Use Connected Mode for automatic daily refresh
│         AND use Upload/S3 for historical backfill (first 12+ months)
└── NO  → Is the client AWS-based?
          ├── YES → Use S3 bucket integration (Option A: they push CUR files automatically)
          │         No credentials shared — only S3 bucket policy
          └── NO (Azure/GCP or mixed) → Use Advisory Upload
                    Client exports monthly, uploads manually
                    30–60 minutes of work per billing period per cloud
```

---

## Data Freshness by Mode

| Mode | How fresh is the data? | Manual work required |
|---|---|---|
| Connected (live) | Updated daily or weekly automatically | None after setup |
| S3 Pull | Updated every 6 hours when AWS delivers new CUR | None after setup |
| S3 Push | Updated whenever client runs the sync | Client must run CLI command or schedule it |
| Advisory Upload | Only as fresh as the last uploaded file | Upload once per billing period |

---

## Security Considerations

### All credentials are stored encrypted
- AWS keys stored using AES-256 encryption at rest in the database
- Azure client secrets stored encrypted
- GCP service account JSON stored encrypted
- No credentials are logged or visible after initial entry

### Principle of least privilege
All credentials used by this app are **read-only**. The app cannot:
- Create, modify, or delete any cloud resources
- Launch or stop any instances
- Modify billing configurations
- Create or delete S3 objects (except in the S3 push bucket — write-only to client's prefix)

### Credential rotation
Connected mode credentials can be rotated at any time in Data Sources → Setup → Edit source. Old credentials are immediately replaced.

### Audit trail
Every ingestion run is recorded in Run History with: timestamp, who triggered it, how many rows were ingested, and whether it succeeded.

---

## Frequently Asked Questions

**Q: What if a client is not on AWS Business Support — can they still use the app?**  
Yes. Trusted Advisor full checks require Business Support, but all other analysis (Cost Explorer, CloudWatch, uploaded CUR, Compute Optimizer) works on any support tier. Trusted Advisor will simply show fewer recommendations.

**Q: Can the app analyze multiple AWS accounts?**  
Yes. Register one data source per account (or use AWS Organizations consolidated billing by uploading the master payer account's CUR file).

**Q: Is the upload size limited?**  
The default limit is 100 MB per file and 5 million rows. Large CUR files (which can be multi-GB) should be compressed as `.csv.gz` to reduce file size, or split by month. For files larger than 100 MB, the S3 integration (Option A or B) is the recommended path.

**Q: Can a client use Advisory Mode for historical data and Connected Mode going forward?**  
Yes, this is the recommended onboarding path. Upload 12–24 months of historical CSV exports first to establish a baseline, then switch to Connected Mode for ongoing daily refresh.

**Q: Does the app keep the raw uploaded files?**  
Only the normalized records are kept. The raw billing file is processed in memory and not stored. A checksum fingerprint is recorded to prevent duplicate uploads from being processed twice.

**Q: Can Azure and AWS data be analyzed together?**  
Yes. Once both sources are normalized, the AI can answer questions that span both, such as "Compare our AWS vs Azure spend by service category."
