# Seed Optimization Recommendations - Deployment Guide

## Problem
All optimization-related queries in the FinOps UI return generic fallback messages:
- "Unable to generate detailed optimization analysis. Showing top cost drivers."
- "Unable to identify optimization targets. Please specify a service or ask about top cost categories."

**Root Cause:** The `optimization_recommendations` table in AWS RDS is empty.

## Solution
Run the seed script to populate the table with 32 comprehensive optimization recommendations across all major AWS services.

---

## Prerequisites

1. Access to AWS RDS PostgreSQL instance
2. Database credentials (from deployment.env or AWS Secrets Manager)
3. One of the following connection methods:
   - AWS Session Manager (via bastion host)
   - VPN connection to VPC
   - RDS publicly accessible (if enabled)
   - AWS Cloud9 or EC2 instance in same VPC

---

## Deployment Steps

### Option 1: Via psql (Direct Connection)

If you have network access to RDS:

```bash
# Set environment variables
export PGHOST=<your-rds-endpoint>.rds.amazonaws.com
export PGPORT=5432
export PGDATABASE=finops
export PGUSER=finops
export PGPASSWORD=<your-db-password>

# Run the seed script
psql -f backend/scripts/seed_all_32_recommendations.sql

# Verify
psql -c "SELECT COUNT(*) as total FROM optimization_recommendations;"
```

### Option 2: Via AWS Systems Manager Session Manager

If using a bastion host or EC2 instance:

```bash
# 1. Start SSM session to bastion/EC2 instance
aws ssm start-session --target <instance-id>

# 2. On the remote instance, install PostgreSQL client if needed
sudo yum install -y postgresql15  # Amazon Linux 2023
# or
sudo apt-get install -y postgresql-client  # Ubuntu

# 3. Copy seed script to instance
# (Use S3, scp, or paste content into a file)
aws s3 cp s3://your-deployment-bucket/seed_all_32_recommendations.sql /tmp/

# 4. Run the script
psql -h <rds-endpoint> -U finops -d finops -f /tmp/seed_all_32_recommendations.sql

# 5. Verify
psql -h <rds-endpoint> -U finops -d finops \
  -c "SELECT service, COUNT(*) FROM optimization_recommendations GROUP BY service;"
```

### Option 3: Via ECS Task (Recommended for Production)

Run as a one-time ECS task in the same VPC:

```bash
# 1. Update the backend Docker image to include the seed script (already done)
# 2. Run ECS task with override command
aws ecs run-task \
  --cluster finops-cluster \
  --task-definition finops-backend:latest \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx]}" \
  --overrides '{
    "containerOverrides": [{
      "name": "backend",
      "command": ["sh", "-c", "PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -U $POSTGRES_USER -d $POSTGRES_DB -f /app/scripts/seed_all_32_recommendations.sql"]
    }]
  }'
```

### Option 4: Via Alembic Migration (For Next Deployment)

Create a data migration:

```bash
# In backend/ directory
cd backend
alembic revision -m "seed_all_32_recommendations"
```

Then edit the generated migration file to execute the SQL script.

---

## Verification

After running the seed script, verify the data:

```sql
-- Check total count
SELECT COUNT(*) as total_recommendations
FROM optimization_recommendations;
-- Expected: 32

-- Check by service
SELECT service, COUNT(*) as count, ROUND(AVG(estimated_savings_max_percent), 1) as avg_savings_pct
FROM optimization_recommendations
GROUP BY service
ORDER BY count DESC;

-- Expected output:
-- EC2        | 6 | 65.0
-- CloudWatch | 3 | 40.0
-- S3         | 3 | 45.0
-- RDS        | 4 | 70.0
-- Lambda     | 3 | 46.7
-- VPC        | 3 | 60.0
-- DynamoDB   | 4 | 55.0
-- General    | 2 | 32.5

-- Test a sample query
SELECT strategy_name, estimated_savings_max_percent, implementation_difficulty
FROM optimization_recommendations
WHERE service = 'EC2'
ORDER BY estimated_savings_max_percent DESC
LIMIT 5;
```

---

## Testing in UI

After seeding, test these queries in the FinOps chat UI:

1. **"What are my optimization opportunities?"**
   - Should now return LLM-generated analysis with specific recommendations

2. **"How can I optimize my EC2 costs?"**
   - Should return 6 EC2-specific recommendations with savings estimates

3. **"Show me CloudWatch optimization recommendations"**
   - Should return 3 CloudWatch strategies

4. **"Generate a cost optimization report"**
   - Should analyze top cost drivers and provide actionable recommendations

---

## Troubleshooting

### Issue: "relation 'optimization_recommendations' does not exist"
**Solution:** Run Alembic migrations first:
```bash
alembic upgrade head
```

### Issue: "column 'implementation_difficulty' does not exist"  
**Solution:** This was BUG-001 - ensure latest code with the column name fix is deployed.

### Issue: Script runs but count is still 0
**Check:**
```sql
-- Check for any errors in PostgreSQL logs
SELECT * FROM pg_stat_activity WHERE state = 'idle in transaction';

-- Verify the table structure
\d optimization_recommendations

-- Check if data exists but is_active = false
SELECT COUNT(*) FROM optimization_recommendations;
```

### Issue: Recommendations still not showing in UI
**Possible causes:**
1. Backend container not restarted after seeding (restart ECS tasks)
2. Wrong database being queried (check POSTGRES_HOST env var)
3. OptimizationEngine caching issue (redeploy backend)
4. LLM integration failing (check CloudWatch logs for bedrock errors)

---

## Rollback

If you need to clear the seeded data:

```sql
TRUNCATE TABLE optimization_recommendations CASCADE;
```

---

## Next Steps

After seeding:
1. ✅ Verify optimization queries work in UI
2. Monitor CloudWatch logs for any database errors
3. Track actual optimization implementation by users
4. Update recommendation confidence scores based on real results
5. Add more service-specific recommendations as needed (DMS, Redshift, etc.)
