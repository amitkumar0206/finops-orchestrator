# AWS Cost and Usage Report (CUR) Setup Guide

## Overview

This guide provides step-by-step instructions for manually configuring AWS Legacy Cost and Usage Report (CUR) to enable historical cost analysis beyond the 13-month limit of AWS Cost Explorer API. The aasmaa Intelligence Platform automatically uses Cost Explorer API but can leverage CUR data for extended historical analysis (up to 36 months).

> **⚠️ Important:** The platform **works immediately** with Cost Explorer API (no CUR required). CUR setup is **optional** and only needed for historical data beyond 13 months.

> **🆕 No Athena? Use Advisory Mode.** If you cannot configure Athena/Glue (or simply want a one-off analysis), download a CUR CSV from the Billing Console and upload it to `POST /api/v1/cur-analysis/upload` — the same seven waste/anomaly detectors run locally with no AWS API access. See [Advisory Mode](#advisory-mode-cur-csv-upload-no-athena-required) below.

## When to Configure CUR

**Configure CUR if you need:**
- Historical cost analysis beyond 13 months (up to 36 months)
- Hourly cost granularity (Cost Explorer provides daily)
- Resource-level cost attribution (detailed instance/resource IDs)
- Split cost allocation for ECS/EKS containers
- Custom cost allocation tags

**Skip CUR if:**
- You only need recent cost data (last 13 months)
- Daily granularity is sufficient
- You want the fastest deployment (Cost Explorer works immediately)

## Deployment Integration

The `deploy.sh` script handles CUR setup automatically:

1. **During Deployment:**
   - Creates S3 bucket for CUR data (if needed)
   - Sets up Athena database and workgroup
   - Creates Athena table with partition projection
   - Configures backend to use CUR when available, Cost Explorer as fallback

2. **CUR Configuration Options:**
   - Platform works immediately with Cost Explorer API (13 months)
   - Optionally configure CUR for extended history (manual AWS Console steps below)
   - Athena table is created even without data (queries work once CUR delivers files)

3. **No Additional Scripts Needed:**
   - Once CUR is configured in AWS Console, data is automatically queryable
   - Partition projection auto-discovers new data as it arrives
   - Backend automatically switches from Cost Explorer to CUR when data is available

## Prerequisites

- AWS Account with Billing Console access (requires **billing administrator** or equivalent permissions)
- S3 bucket for CUR data storage (created by deploy.sh or manually)
- AWS Support subscription (for 36-month backfill request)

## Step 1: Configure Legacy CUR via AWS Console

### 1.1 Navigate to Cost and Usage Reports

1. Log into [AWS Console](https://console.aws.amazon.com/)
2. Go to **Billing and Cost Management** → **Cost & Usage Reports**
3. Click **"Create report"**

### 1.2 Report Configuration

Configure your CUR with the following **exact** settings:

| Setting | Value | Notes |
|---------|-------|-------|
| **Report name** | `aasmaa-cost-report` | Must match platform configuration |
| **Report type** | **Legacy CUR** | ⚠️ DO NOT select "CUR 2.0" |
| **Time granularity** | **Hourly** | Required for detailed analysis |
| **Report versioning** | **Overwrite existing report** | Prevents duplicate data |
| **Enable resource IDs** | ✅ **Checked** | Critical for drill-down analysis |
| **Split cost allocation data** | ✅ **Checked** | Required for ECS/EKS costs |
| **Compression type** | **Parquet** | Optimized for Athena queries |
| **Data refresh settings** | **Automatically refresh** | Keep data current |

### 1.3 S3 Delivery Configuration

| Setting | Value | Example |
|---------|-------|---------|
| **S3 bucket** | Your CUR bucket | `aasmaa-data-123456789012` |
| **S3 path prefix** | `cur/aasmaa-cost-report` | Standard prefix structure |
| **Report path prefix** | `aasmaa-cost-report` | Matches report name |

**Expected S3 Path Structure:**
```
s3://your-bucket/cur/aasmaa-cost-report/aasmaa-cost-report/
  └── year=2024/
      ├── month=11/
      │   ├── aasmaa-cost-report-*.parquet
      │   └── aasmaa-cost-report-Manifest.json
      └── month=12/
          └── ...
```

### 1.4 Data Integration

| Setting | Value | Notes |
|---------|-------|-------|
| **Data integration for** | **Amazon Athena** | ✅ Select this option |
| **Enable data integration** | ✅ **Checked** | Tells AWS to use compatible format |

### 1.5 Confirm Configuration

Review all settings carefully:
- [ ] Report type is **Legacy CUR** (not CUR 2.0)
- [ ] Time granularity is **Hourly**
- [ ] Resource IDs are **enabled**
- [ ] Split cost allocation is **enabled**
- [ ] Compression is **Parquet**
- [ ] S3 bucket matches your deployment
- [ ] Athena integration is **enabled**

Click **"Create report"**

## Step 2: Request 36-Month Historical Backfill

AWS can backfill up to **36 months** of historical CUR data upon request via AWS Support.

### 2.1 Open AWS Support Case

1. Go to **AWS Support Center** → **Create Case**
2. Select **Account and billing support** (no additional cost)
3. Choose **Type**: Billing
4. **Category**: Cost and Usage Reports

### 2.2 Support Ticket Template

Use this exact template for your support ticket:

---

**Subject:** Request Historical Cost and Usage Report Data Backfill (36 Months)

**Description:**

Hello AWS Support,

I am requesting a historical backfill of Cost and Usage Report (CUR) data for my AWS account.

**Request Details:**
- AWS Account ID: `[YOUR_ACCOUNT_ID]`
- CUR Report Name: `aasmaa-cost-report`
- CUR Report Type: **Legacy CUR** (Parquet format)
- S3 Bucket: `s3://[YOUR_BUCKET_NAME]/cur/aasmaa-cost-report/`
- Requested Backfill Period: **36 months** from current date
  - Start Date: `[CURRENT_DATE - 36 months]` (e.g., November 2021)
  - End Date: `[CURRENT_DATE]` (e.g., November 2024)

**Business Justification:**
We are implementing a aasmaa intelligence platform that requires comprehensive historical cost data for trend analysis, budget forecasting, and cost optimization initiatives. Having 36 months of historical data will enable:
- Year-over-year cost comparisons
- Long-term trend analysis
- Accurate forecasting models
- Historical cost attribution for active resources

**Additional Information:**
- The CUR report was created on: `[CREATION_DATE]`
- S3 bucket has appropriate permissions configured
- Athena database is ready for backfilled data

Please confirm the backfill request and provide an estimated completion timeline.

Thank you for your assistance.

---

### 2.3 What to Expect

| Timeline | Event |
|----------|-------|
| **Within 24 hours** | AWS Support confirms the request |
| **24-48 hours** | Initial CUR data appears in S3 (current month) |
| **24-48 hours** | Historical backfill completes (36 months) |

> **Note:** Backfill timing can vary based on account size and data volume. Most accounts see completion within 48 hours.

### 2.4 Verify Backfill Progress

Check your S3 bucket for historical data:

```bash
# List all year/month partitions
aws s3 ls s3://your-bucket/cur/aasmaa-cost-report/aasmaa-cost-report/ --recursive | grep "year="

# Expected output (if backfill to 2021):
# year=2021/month=11/
# year=2021/month=12/
# year=2022/month=01/
# ... (all months through current date)
```

## Step 3: Verify CUR Configuration

### 3.1 Confirm Report Settings

In AWS Console → Billing → Cost & Usage Reports, verify:
- ✅ Report status shows "Active"
- ✅ Last updated is within 24 hours
- ✅ S3 bucket shows correct path

### 3.2 Check S3 Bucket

Verify data is being delivered:

```bash
# Check for current month data
aws s3 ls s3://your-bucket/cur/aasmaa-cost-report/aasmaa-cost-report/year=$(date +%Y)/month=$(date +%m)/

# Should show:
# aasmaa-cost-report-00001.snappy.parquet
# aasmaa-cost-report-Manifest.json
```

### 3.3 Verify Partition Structure

Ensure the directory structure follows the expected pattern:

```
s3://bucket/cur/aasmaa-cost-report/aasmaa-cost-report/
  └── year=YYYY/
      └── month=MM/
          ├── *.parquet (data files)
          └── *-Manifest.json (metadata)
```

This structure is **critical** for Athena Partition Projection to work correctly.

## Step 4: Deploy Platform with CUR

Once CUR is configured and data is available in S3, run the deployment:

```bash
# Set environment variables
export CUR_S3_BUCKET="your-bucket-name"
export CUR_S3_PREFIX="cur/aasmaa-cost-report/aasmaa-cost-report"
export AWS_REGION="us-east-1"

# Run deployment (will create Athena table with partition projection)
./deploy.sh deploy
```

The deploy script will:
1. ✅ Verify CUR S3 bucket and data exist
2. ✅ Create Athena database (if not exists)
3. ✅ Create Athena table with partition projection
4. ✅ Run validation query to confirm data accessibility
5. ✅ Deploy application with correct CUR configuration

## Troubleshooting

### Issue: No data in current month partition

**Cause:** AWS CUR updates daily (not real-time)

**Solution:** 
- Wait 24 hours after CUR creation for first data
- Check report status in Billing Console
- Verify S3 bucket permissions allow `billingreports.amazonaws.com`

### Issue: Backfill not completing

**Cause:** AWS Support ticket may need follow-up

**Solution:**
- Reply to support ticket for status update
- Typical backfill completes within 48 hours
- Check S3 for partial backfill completion

### Issue: Athena queries return no results

**Cause:** Partition projection configuration mismatch

**Solution:**
1. Verify S3 path structure matches: `year=YYYY/month=MM/`
2. Check Athena table DDL has correct `storage.location.template`
3. Run `SHOW PARTITIONS` query to see discovered partitions
4. Ensure CUR data is Parquet format (not Gzip CSV)

### Issue: Missing split cost allocation data

**Cause:** Split cost allocation not enabled during CUR creation

**Solution:**
- Go to Billing Console → Cost & Usage Reports
- Edit report and enable "Split cost allocation data"
- Wait 24 hours for next data refresh
- ⚠️ Cannot retroactively enable for historical data

### Issue: Resource IDs missing

**Cause:** "Enable resource IDs" was not checked

**Solution:**
- Edit CUR report to enable resource IDs
- Wait 24 hours for next data delivery
- ⚠️ Historical data will not have resource IDs retroactively

## Data Freshness & Update Cadence

| Update Frequency | Description |
|------------------|-------------|
| **Daily** | AWS delivers updated CUR data daily (typically by 9 AM UTC) |
| **Hourly granularity** | Each day's file contains hourly cost records |
| **Finalized** | Data finalizes 1-2 days after month end |
| **Corrections** | AWS may reprocess past days if corrections needed |

## Cost Implications

| Component | Cost | Notes |
|-----------|------|-------|
| **CUR Report** | **FREE** | No charge for CUR generation |
| **S3 Storage** | ~$0.023/GB | 36 months typically 50-200 GB |
| **Athena Queries** | $5/TB scanned | Partition projection minimizes scans |
| **Backfill Request** | **FREE** | No additional cost via AWS Support |

**Example:** 100 GB of CUR data = ~$2.30/month storage + ~$0.50/month Athena queries = **$2.80/month**

## Advisory Mode: CUR CSV Upload (No Athena Required)

If a tenant cannot or will not grant live AWS API access, the **CUR / Billing Export Deep Analysis** feature still works in **Advisory Mode**:

1. In the AWS Billing Console → **Cost & Usage Reports**, open any active report and download a recent `.csv` (or `.csv.gz`) export — or copy one directly from the CUR S3 bucket.
2. `POST` the file as `multipart/form-data` to:

   ```bash
   curl -X POST https://<host>/api/v1/cur-analysis/upload \
        -H "Authorization: Bearer <token>" \
        -F "file=@cur-2025-01.csv.gz" \
        -F "account_id=123456789012"   # optional override
   ```

3. The response contains the full **opportunity list** plus a **summary** (rows analyzed, billing period, total spend, savings by detector). Findings are also persisted into the org-scoped Opportunities dashboard with `source=cur_analysis`, so they appear alongside live signals.

The analyzer normalises all three CUR header conventions (Glue snake_case, Billing-console `lineItem/UsageType`, CUR 2.0) and runs the same seven detectors as Connected Mode:

| Detector | CUR columns used |
|----------|------------------|
| Usage-type cost drivers | `line_item_usage_type`, `line_item_unblended_cost` |
| RI unused hours | `reservation_unused_*`, `reservation_reservation_a_r_n` |
| SP unused commitment | `savings_plan_total_commitment_to_date`, `savings_plan_used_commitment` |
| Cross-region data transfer | `line_item_usage_type LIKE '%InterRegion%'`, `product_region` |
| Idle resources | `line_item_resource_id`, `line_item_usage_amount = 0`, `line_item_unblended_cost > 0` |
| On-demand steady-state DB | `line_item_product_code IN (RDS, ElastiCache, Redshift)`, `pricing_term = OnDemand` |
| Scheduling candidates | `line_item_usage_start_date` hour-of-day vs `BoxUsage` cost |

### Connected Mode (Athena + Cost Explorer)

Once Athena/CUR are configured per this guide, call `POST /api/v1/cur-analysis/mine` (or `POST /api/v1/opportunities/ingest?source=cur_analysis`) to run the same detectors against the live CUR table **plus** `ce:GetAnomalies` and `ce:GetCostAndUsage` month-over-month trend analysis. `GET /api/v1/cur-analysis/capabilities` reports which mode(s) are currently available.

### Per-Tenant Configuration

Every threshold is environment-driven (no code change required):

| Variable | Default | Purpose |
|----------|---------|---------|
| `CUR_PATTERN_MINING_ENABLED` | `true` | Master kill-switch for the feature |
| `CUR_UPLOAD_MAX_SIZE_MB` | `200` | Max accepted upload size |
| `CUR_UPLOAD_MAX_ROWS` | `2000000` | Max CSV rows parsed |
| `CUR_MINING_LOOKBACK_DAYS` | `30` | Connected-Mode Athena/CE lookback window |
| `CUR_MINING_MIN_IDLE_COST_USD` | `5.0` | Floor below which idle resources are ignored |
| `CUR_MINING_MIN_DATA_TRANSFER_USD` | `10.0` | Floor for cross-region transfer findings |
| `CUR_MINING_MIN_RI_UNUSED_USD` | `1.0` | Floor for unused-RI findings |
| `CUR_MINING_MIN_SP_UNUSED_USD` | `1.0` | Floor for unused-SP findings |
| `CUR_MINING_STEADY_STATE_HOURS_PER_DAY` | `20.0` | Hours/day above which a DB is "always on" |
| `CUR_MINING_MIN_STEADY_STATE_COST_USD` | `50.0` | Floor for RI-candidate findings |
| `CUR_MINING_SCHEDULING_OFF_HOURS_SHARE` | `0.40` | Off-hours cost share that triggers a scheduling rec |
| `CUR_MINING_MOM_INCREASE_THRESHOLD_PCT` | `40.0` | % above 3-month avg that triggers a trend alert |
| `CUR_MINING_MAX_FINDINGS_PER_DETECTOR` | `25` | Output cap per detector |

## Best Practices

### ✅ Do's

- Enable CUR as soon as possible (data available from creation date forward)
- Request backfill immediately after CUR creation
- Use consistent report name across environments
- Monitor S3 storage costs as data grows
- Enable S3 lifecycle policies after 36 months

### ❌ Don'ts

- Don't use CUR 2.0 (schema incompatible with platform)
- Don't modify S3 path structure (breaks partition projection)
- Don't delete current month data (AWS updates in-place)
- Don't compress or rename CUR files manually
- Don't mix multiple CUR reports in same S3 prefix

## Additional Resources

- [AWS Legacy CUR Documentation](https://docs.aws.amazon.com/cur/latest/userguide/what-is-cur.html)
- [Athena Partition Projection](https://docs.aws.amazon.com/athena/latest/ug/partition-projection.html)
- [CUR Data Dictionary](https://docs.aws.amazon.com/cur/latest/userguide/data-dictionary.html)
- [AWS Support Center](https://console.aws.amazon.com/support/home)

## Next Steps

After CUR setup completes:

1. ✅ Run `./deploy.sh deploy` to create Athena infrastructure
2. ✅ Verify platform health check endpoint shows CUR data accessible
3. ✅ Test sample queries in `docs/sample_queries.sql`
4. ✅ Review [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) for application deployment

---

**Questions or Issues?**
- Check [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)
- Review platform logs: `docker logs aasmaa-backend`
- Contact your AWS Solutions Architect for account-specific guidance
