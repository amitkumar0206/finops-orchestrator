# Troubleshooting Guide - FinOps Intelligence Platform

## Overview

This guide covers common issues you may encounter when deploying and using the FinOps Intelligence Platform, with specific focus on CUR data integration and Athena query issues.

## Table of Contents

1. [CUR Setup Issues](#cur-setup-issues)
2. [Athena Query Problems](#athena-query-problems)
3. [Deployment Failures](#deployment-failures)
4. [Application Errors](#application-errors)
5. [Performance Issues](#performance-issues)
6. [Data Quality Problems](#data-quality-problems)
7. [ECS Exec and Session Manager Plugin](#ecs-exec-and-session-manager-plugin)

---

## CUR Setup Issues

### No CUR Data in S3 Bucket

**Symptoms:**
- Deploy script fails with "No CUR data found"
- Athena queries return 0 rows
- S3 bucket empty or missing data

**Causes & Solutions:**

**1. CUR Not Yet Configured**

Check if Legacy CUR is configured:

```bash
aws cur describe-report-definitions --region us-east-1
```

If empty, follow [SETUP_CUR.md](./SETUP_CUR.md) to configure CUR.

**2. First Data Delivery Pending**

AWS takes 24 hours to deliver first CUR data after configuration.

**Solution:** Wait 24 hours, then check:

```bash
aws s3 ls s3://your-bucket/cur/finops-cost-report/finops-cost-report/ --recursive | head -20
```

**3. Incorrect S3 Prefix**

Verify your CUR report path matches `CUR_S3_PREFIX` in `deployment.env`:

```bash
# Check actual S3 structure
aws s3 ls s3://your-bucket/cur/

# Should show: finops-cost-report/
# Then: aws s3 ls s3://your-bucket/cur/finops-cost-report/
# Should show: finops-cost-report/ (report directory)
```

Update `deployment.env` if path differs:

```bash
CUR_S3_PREFIX=cur/finops-cost-report/finops-cost-report
```

**4. Wrong Report Name**

If you used a different CUR report name than `finops-cost-report`:

```bash
# Find your report name
aws cur describe-report-definitions --region us-east-1 --query "ReportDefinitions[*].ReportName"

# Update CUR_S3_PREFIX accordingly
CUR_S3_PREFIX=cur/YOUR_REPORT_NAME/YOUR_REPORT_NAME
```

### CUR 2.0 Instead of Legacy CUR

**Symptoms:**
- Schema mismatch errors in Athena
- Missing columns like `split_line_item_*`
- Query failures on partition projection

**Cause:**
Platform requires **Legacy CUR**, not CUR 2.0.

**Solution:**

1. Delete CUR 2.0 report in AWS Console
2. Create new **Legacy CUR** report (see [SETUP_CUR.md](./SETUP_CUR.md))
3. Wait 24 hours for data delivery
4. Update deployment with correct S3 path

### Backfill Not Completing

**Symptoms:**
- Only current month data available
- Missing historical months
- AWS Support ticket not responding

**Solution:**

1. Check AWS Support ticket status
2. Verify backfill request included:
   - Correct account ID
   - Correct report name
   - Specific time range (36 months)
3. Typical completion: 24-48 hours
4. If > 72 hours, reply to support ticket

Check backfill progress:

```bash
# List all year/month partitions
aws s3 ls s3://your-bucket/cur/finops-cost-report/finops-cost-report/ --recursive | grep "year=" | cut -d'/' -f5-6 | sort -u

# Should show: year=2021/month=11/ through year=2024/month=11/
```

### S3 Bucket Permission Errors

**Symptoms:**
- "Access Denied" errors in deployment
- Cannot list S3 objects
- CUR validation fails

**Cause:**
Incorrect IAM permissions or bucket policy.

**Solution:**

Verify IAM user/role has permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket",
        "s3:HeadBucket"
      ],
      "Resource": [
        "arn:aws:s3:::your-cur-bucket",
        "arn:aws:s3:::your-cur-bucket/*"
      ]
    }
  ]
}
```

Verify bucket policy allows your account:

```bash
aws s3api get-bucket-policy --bucket your-cur-bucket --query Policy --output text | jq .
```

---

## Athena Query Problems

### Athena Table Not Found

**Symptoms:**
- Error: "Table cost_usage_db.cur_data not found"
- Queries fail immediately
- Health check shows table unhealthy

**Solution:**

1. Verify database exists:

```bash
aws athena get-database --catalog-name AwsDataCatalog --database-name cost_usage_db --region us-east-1
```

2. List tables:

```bash
aws glue get-tables --database-name cost_usage_db --region us-east-1 --query "TableList[*].Name"
```

3. Recreate table:

```bash
# Run setup script
bash scripts/setup/setup-athena-cur.sh \
  your-cur-bucket \
  cur/finops-cost-report/finops-cost-report \
  cost_usage_db \
  cur_data \
  us-east-1 \
  s3://your-app-bucket/athena-results/
```

### Partition Projection Not Working

**Symptoms:**
- "Partition not found" errors
- Queries scan all data (expensive)
- SHOW PARTITIONS returns empty

**Cause:**
Partition projection configuration incorrect.

**Solution:**

1. Check table properties:

```sql
SHOW TBLPROPERTIES cost_usage_db.cur_data;
```

Should show:
- `projection.enabled = true`
- `projection.year.type = integer`
- `projection.month.type = integer`
- `storage.location.template` matches S3 structure

2. Verify S3 path structure matches template:

```bash
# Should be: year=YYYY/month=MM/
aws s3 ls s3://your-bucket/prefix/ --recursive | grep parquet | head -5
```

3. If mismatch, drop and recreate table:

```sql
DROP TABLE cost_usage_db.cur_data;
```

Then re-run `setup-athena-cur.sh`.

### Queries Return No Results

**Symptoms:**
- COUNT(*) returns 0
- All queries empty
- Table exists but no data

**Causes & Solutions:**

**1. Partition Filter Missing**

Always filter by year/month:

```sql
-- BAD (scans all partitions)
SELECT * FROM cost_usage_db.cur_data WHERE line_item_product_code = 'AmazonEC2';

-- GOOD (partition pruning)
SELECT * FROM cost_usage_db.cur_data 
WHERE year = '2024' 
  AND month = '11' 
  AND line_item_product_code = 'AmazonEC2';
```

**2. No Data for Requested Month**

Check which months have data:

```sql
SELECT year, month, COUNT(*) as records
FROM cost_usage_db.cur_data
GROUP BY year, month
ORDER BY year DESC, month DESC;
```

**3. Wrong Column Names**

Legacy CUR uses lowercase with underscores:

```sql
-- WRONG
SELECT lineItemProductCode FROM cur_data;

-- CORRECT
SELECT line_item_product_code FROM cur_data;
```

### Query Timeout or Slow Performance

**Symptoms:**
- Queries take > 30 seconds
- Athena timeouts
- High query costs

**Solutions:**

**1. Always Use Partition Filtering**

```sql
WHERE year = '2024' AND month = '11'  -- Reduces scan by 97%
```

**2. Select Only Needed Columns**

```sql
-- BAD (scans all columns)
SELECT * FROM cur_data WHERE year = '2024' AND month = '11';

-- GOOD (selective columns)
SELECT line_item_product_code, SUM(line_item_unblended_cost)
FROM cur_data 
WHERE year = '2024' AND month = '11'
GROUP BY line_item_product_code;
```

**3. Use LIMIT for Exploration**

```sql
SELECT * FROM cur_data WHERE year = '2024' AND month = '11' LIMIT 100;
```

**4. Check Query Execution Details**

```bash
# Get query stats
aws athena get-query-execution --query-execution-id <query-id> --region us-east-1
```

Look for:
- Data scanned (should be < 10 GB for single month)
- Execution time
- Error messages

---

## Deployment Failures

### CloudFormation Stack CREATE_FAILED

**Symptoms:**
- Stack creation fails
- Resources partially created
- Rollback in progress

**Solution:**

1. Check stack events:

```bash
aws cloudformation describe-stack-events \
  --stack-name finops-intelligence-platform \
  --region us-east-1 \
  --query "StackEvents[?ResourceStatus=='CREATE_FAILED']" \
  --output table
```

2. Common failures:

**ECS Task Definition Failed:**
- Image not found in ECR
- Solution: Ensure `docker push` completed successfully

**RDS Instance Failed:**
- Subnet group issues
- Solution: Check VPC configuration, ensure private subnets exist

**ALB Certificate Failed:**
- DNS validation timeout
- Solution: Ensure Route 53 hosted zone is correct

3. Clean up failed stack:

```bash
./deploy.sh destroy
```

Then retry deployment.

### Docker Build/Push Failures

**Symptoms:**
- "docker push" fails
- "denied: Your authorization token has expired"
- Image tag not found

**Solution:**

1. Re-authenticate to ECR:

```bash
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  $(aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-1.amazonaws.com
```

2. Rebuild and push:

```bash
./deploy.sh update
```

---

## ECS Exec and Session Manager Plugin

### "SessionManagerPlugin is not found" when running migrations

**Symptoms:**
- Running migrations with ECS Exec fails with:
  `SessionManagerPlugin is not found. Please refer to SessionManager Documentation...`
- `aws ecs execute-command` exits immediately.

**Cause:**
Your local machine is missing the AWS Systems Manager Session Manager Plugin, which is required for `aws ecs execute-command`.

**Fix (macOS):**
1. Install the plugin via Homebrew:
   ```bash
   brew install session-manager-plugin
   ```
2. Verify installation:
   ```bash
   session-manager-plugin --version
   aws --version
   ```
   Ensure AWS CLI v2 is installed.

3. Re-run your command or deployment script. The deploy script will automatically fall back to a one-off Fargate task if ECS Exec is unavailable, but the plugin enables real-time exec and logs.

**Also ensure:**
- ECS Exec is enabled on the backend service. This repo sets `EnableExecuteCommand: true` in `infrastructure/cloudformation/ecs-services.yaml`.
- Your IAM identity has permissions for `ssm:StartSession`, `ssm:DescribeSessions`, `ssm:GetConnectionStatus`, `ssm:OpenControlChannel`, and `ssm:OpenDataChannel`.

If you prefer to skip ECS Exec, you can run migrations using the one-off task flow directly:
```bash
./scripts/deployment/aws_run_migrations.sh run \\
  --region us-east-1 \\
  --cluster <cluster-name> \\
  --task-def <task-def-arn> \\
  --subnets subnet-aaa,subnet-bbb \\
  --security-groups sg-xxxxx
```

3. Check ECR repository exists:

```bash
aws ecr describe-repositories --region us-east-1 --query "repositories[*].repositoryName"
```

### "AccessDenied" During Deployment

**Symptoms:**
- IAM permission errors
- Cannot create resources
- CloudFormation rollback

**Solution:**

Required IAM permissions for deployment:

- CloudFormation: Full access
- ECS: Full access
- ECR: Full access
- RDS: Create/modify instances
- VPC: Create/modify resources
- IAM: Create roles (for ECS tasks)
- S3: Create/manage buckets
- Athena: Query execution
- Glue: Database management

Check current permissions:

```bash
aws iam get-user --query "User.Arn"
aws iam list-attached-user-policies --user-name <your-username>
```

Contact AWS administrator to grant required permissions.

---

## Application Errors

### Health Check Shows "degraded"

**Symptoms:**
- `/api/health` returns status "degraded"
- CUR table health: "unhealthy"
- Athena: "unavailable"

**Solution:**

1. Check detailed health response:

```bash
curl -s https://your-app-url/api/health | jq .
```

2. If CUR unhealthy:
   - Verify CUR data exists (see [CUR Setup Issues](#cur-setup-issues))
   - Check Athena table (see [Athena Query Problems](#athena-query-problems))
   - Verify environment variables in backend container:

```bash
# Get ECS task ID
TASK_ID=$(aws ecs list-tasks --cluster finops-cluster --service-name finops-backend --query "taskArns[0]" --output text)

# Check environment
aws ecs describe-tasks --cluster finops-cluster --tasks $TASK_ID --query "tasks[0].overrides.containerOverrides[0].environment"
```

3. If database unhealthy:
   - Check RDS status
   - Verify security group allows ECS tasks to connect
   - Check database credentials in Secrets Manager

### "No Data Available" in UI

**Symptoms:**
- Frontend shows "No cost data found"
- Queries return empty results
- Application runs but no data

**Solution:**

1. Verify health check first (see above)

2. Test sample query manually:

```sql
SELECT COUNT(*) FROM cost_usage_db.cur_data 
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR);
```

3. Check application logs:

```bash
# Backend logs
aws logs tail /ecs/finops-backend --follow --region us-east-1

# Look for Athena errors or timeouts
```

4. Verify CUR data freshness:

```sql
SELECT MAX(line_item_usage_start_date) as latest_date
FROM cost_usage_db.cur_data
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR)
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR);
```

If latest_date > 2 days old, check CUR delivery status.

### Bedrock "AccessDenied" Errors

**Symptoms:**
- Chat queries fail
- Error: "Could not access model"
- LLM service unhealthy

**Solution:**

1. Verify Bedrock model access:

```bash
aws bedrock list-foundation-models --region us-east-1 --query "modelSummaries[?contains(modelId, 'nova-pro')]"
```

2. Check IAM role has Bedrock permissions:

```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "bedrock:ListFoundationModels"
  ],
  "Resource": "*"
}
```

3. Try different model:

Update `BEDROCK_MODEL_ID` in backend environment:

```bash
BEDROCK_MODEL_ID=us.amazon.nova-lite-v1:0
```

Restart ECS service.

---

## Performance Issues

### Slow Query Response Times

**Symptoms:**
- Queries take > 15 seconds
- UI feels sluggish
- Athena charges high

**Solutions:**

1. **Add Partition Filtering** (most important)

Ensure all queries include:

```sql
WHERE year = '2024' AND month = '11'
```

2. **Use Query Result Caching**

Athena caches results for 24 hours. Identical queries are free and instant.

3. **Optimize Column Selection**

Don't use `SELECT *`, specify needed columns.

4. **Consider Cost Explorer for Recent Data**

For last 13 months, Cost Explorer API may be faster than Athena.

### High Athena Costs

**Symptoms:**
- AWS bill shows high Athena charges
- Queries scanning TBs of data
- $50+ monthly Athena costs

**Solution:**

1. Check data scanned per query:

```bash
aws athena get-query-execution --query-execution-id <query-id> \
  --query "QueryExecution.Statistics.DataScannedInBytes" --output text
```

2. Ensure partition projection working:

```sql
-- This should scan ~3 GB (1 month)
SELECT COUNT(*) FROM cur_data WHERE year = '2024' AND month = '11';

-- This scans ~100 GB (36 months) - EXPENSIVE
SELECT COUNT(*) FROM cur_data;
```

3. Monitor query patterns:

```bash
# List recent queries
aws athena list-query-executions --region us-east-1 --max-results 10
```

4. Set up Athena cost alerts:

Configure CloudWatch alarm for Athena spend > $X.

---

## Data Quality Problems

### Missing Resource IDs

**Symptoms:**
- `line_item_resource_id` is NULL
- Cannot drill down to specific resources
- Empty resource-level reports

**Cause:**
"Enable resource IDs" not checked during CUR creation.

**Solution:**

Cannot fix retroactively. For future data:

1. Edit CUR in AWS Console
2. Enable "Resource IDs"
3. Wait 24 hours for new data
4. Historical data will not have resource IDs

### Missing Split Cost Allocation

**Symptoms:**
- `split_line_item_split_cost` is NULL
- Cannot analyze ECS/EKS container costs
- Empty split cost reports

**Cause:**
"Split cost allocation" not enabled during CUR creation.

**Solution:**

Cannot fix retroactively. For future data:

1. Edit CUR in AWS Console
2. Enable "Split cost allocation data"
3. Wait 24 hours
4. Historical data will not have split costs

### Negative Costs Showing

**Symptoms:**
- Some cost values are negative
- Total costs lower than expected
- Confusing reports

**Cause:**
This is **normal**. Negative costs represent:
- Credits
- Refunds
- EDP discounts
- Rebates

**Solution:**

Filter by line item type:

```sql
-- Exclude negative line items
WHERE line_item_line_item_type NOT IN ('Credit', 'EdpDiscount', 'Refund')

-- Or explicitly include usage only
WHERE line_item_line_item_type IN ('Usage', 'DiscountedUsage', 'SavingsPlanCoveredUsage')
```

### Data Freshness Issues

**Symptoms:**
- Latest data is 2+ days old
- Missing today's costs
- Stale reports

**Cause:**
CUR updates daily, not real-time. AWS finalizes data 1-2 days after usage.

**Expected Behavior:**
- Current day: No data
- Yesterday: Partial data
- 2 days ago: Complete data

**Solution:**

For real-time costs, use Cost Explorer API (13 months only):

```python
# Cost Explorer for today's costs (estimated)
ce_client.get_cost_and_usage(
    TimePeriod={
        'Start': '2024-11-11',
        'End': '2024-11-12'
    },
    Granularity='DAILY',
    Metrics=['UnblendedCost']
)
```

---

## Getting Additional Help

### Check Application Logs

**Backend:**

```bash
aws logs tail /ecs/finops-backend --follow --region us-east-1
```

**Frontend:**

```bash
aws logs tail /ecs/finops-frontend --follow --region us-east-1
```

### Enable Debug Logging

Update backend environment:

```bash
DEBUG=true
LOG_LEVEL=DEBUG
```

Restart ECS service, check logs for detailed information.

### Run Health Check

```bash
curl -s https://your-app-url/api/health | jq .
```

Review each service status and error messages.

### Test CUR Access Manually

```sql
-- Basic accessibility test
SELECT 'CUR_ACCESSIBLE' as status, COUNT(*) as record_count
FROM cost_usage_db.cur_data 
WHERE year = CAST(YEAR(CURRENT_DATE) AS VARCHAR) 
  AND month = CAST(MONTH(CURRENT_DATE) AS VARCHAR)
LIMIT 1;
```

### Useful AWS CLI Commands

```bash
# Check ECS service status
aws ecs describe-services --cluster finops-cluster --services finops-backend

# Check RDS instance
aws rds describe-db-instances --query "DBInstances[?DBInstanceIdentifier=='finops-db']"

# Check ALB target health
aws elbv2 describe-target-health --target-group-arn <arn>

# Check CloudWatch logs
aws logs tail /ecs/finops-backend --since 30m
```

### Contact Information

- **Documentation**: Check [README.md](../README.md) and [SETUP_CUR.md](./SETUP_CUR.md)
- **AWS Support**: For CUR-specific issues, open AWS Support case
- **GitHub Issues**: Report platform bugs
- **Internal Support**: Contact your AWS Solutions Architect

### Common Error Codes Reference

| Error Code | Meaning | Solution |
|------------|---------|----------|
| `TABLE_NOT_FOUND` | Athena table doesn't exist | Run setup-athena-cur.sh |
| `PARTITION_NOT_FOUND` | Partition projection failed | Verify S3 path structure |
| `ACCESS_DENIED` | IAM permission issue | Check IAM policies |
| `QUERY_TIMEOUT` | Query too slow | Add partition filters |
| `NO_SUCH_BUCKET` | S3 bucket missing | Verify CUR_S3_BUCKET |
| `INVALID_REQUEST` | Bad SQL syntax | Check query format |
| `THROTTLING` | Rate limit exceeded | Reduce query frequency |

---

**Last Updated:** November 11, 2024  
**Version:** 1.0.0
