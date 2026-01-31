# Quick Start Guide - Multi-Agent FinOps Platform

## What Was Fixed

✅ **Query Classification** - Now classifies into 10 specific intent types with confidence
✅ **Historical Data Access** - Complete Athena CUR query templates for all scenarios  
✅ **Beautiful Responses** - Structured markdown with Summary, Scope, Results, Insights, Charts, Next steps
✅ **Follow-up Context** - Conversation context manager tracks and inherits parameters
✅ **Smart Fallbacks** - No more generic errors; targeted clarifications and actionable suggestions

## Key Components

```
backend/
├── agents/
│   ├── intent_classifier.py           # Intent classification with confidence
│   └── multi_agent_workflow.py        # LangGraph-based multi-agent orchestration (default)
├── services/
│   ├── athena_executor.py             # Async Athena query execution
│   ├── response_formatter.py          # Structured FinOps template formatter
│   ├── chart_recommendation.py        # Intelligent chart suggestions
│   └── conversation_manager.py        # Postgres-backed conversation threads + context
└── api/
    └── chat.py                        # Uses multi-agent workflow by default
```

## How to Use

### 1. Start the Backend

```bash
cd backend
python main.py
```

### 2. Test with Examples

#### Example 1: Top Services Query
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What are my top 5 most expensive AWS services last month?",
    "conversation_id": "demo-001"
  }'
```

**Expected Response:**
```markdown
**Summary**
Your top 5 cost drivers total $33,738.36, with AmazonEC2 leading at $15,234.56 (45.2% of total).

**Scope**
- Period: 2024-09-01 to 2024-09-30
- Filters: None (all resources)

**Results**
| Rank | Service | Cost Usd | Pct Of Total |
| --- | --- | --- | --- |
| 1 | AmazonEC2 | $15,234.56 | 45.2% |
| 2 | AmazonS3 | $8,912.34 | 26.4% |
...

**Insights**
- Top 2 items represent 71.6% of total costs
- AmazonEC2 is the primary cost driver
- Focus on top 3 for maximum impact

**Recommended Charts**
1. Column chart: x=service, y=cost_usd

**Next steps**
- Drill down into AmazonEC2 by region
- Compare with previous period
```

#### Example 2: Follow-up Query
```bash
# Uses same conversation_id to maintain context
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Exclude CloudFront and show again",
    "conversation_id": "demo-001"
  }'
```

**What Happens:**
- System detects this is a follow-up (short query with "exclude")
- Inherits time range from previous query ("last month")
- Adds CloudFront to exclusion list
- Regenerates top 5 without CloudFront

#### Example 3: Breakdown Query
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Break down EC2 costs by instance type for last month",
    "conversation_id": "demo-002"
  }'
```

**Response Includes:**
- Table with instance_type, cost_usd, pct_of_ec2
- Insights about concentration and top types
- Bar chart recommendation
- Next steps for optimization

#### Example 4: Anomaly Detection
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Why did S3 costs spike in September 2025?",
    "conversation_id": "demo-003"
  }'
```

**Response Includes:**
- Month-over-month comparison (Aug vs Sep)
- Breakdown by driver (Storage, Requests, DataTransfer, Glacier)
- Delta analysis with $ and %
- Clustered bar chart showing Aug vs Sep

## Understanding the Pipeline

Every query goes through this multi-agent pipeline:

```
User Query
    ↓
1. Get/Create Thread + Context (services/conversation_manager.py)
    ↓
2. Supervisor classifies and routes (agents/multi_agent_workflow.py)
    ↓
3. Specialist agent executes data retrieval (services/athena_executor.py)
    ↓
4. Recommend Charts (services/chart_recommendation.py)
    ↓
5. Format Response (services/response_formatter.py)
    ↓
6. Persist messages, intents, and execution logs (services/conversation_manager.py)
    ↓
7. Return Result
```

## Intent Types

The system classifies queries into these 10 types:

1. **COST_BREAKDOWN** - "Break down EC2 by instance type"
2. **TOP_N_RANKING** - "Top 5 services by cost"
3. **ANOMALY_ANALYSIS** - "Why did costs spike?"
4. **COST_TREND** - "Show month-over-month trends"
5. **UTILIZATION** - "Underutilized RDS instances"
6. **OPTIMIZATION** - "How can I save money?"
7. **GOVERNANCE** - "Show untagged resources"
8. **DATA_METADATA** - "CUR record count per day"
9. **COMPARATIVE** - "Compare Dev vs Prod"
10. **OTHER** - Generic queries (asks clarification)

## Follow-up Patterns

The system understands these refinement patterns:

- **"Exclude X"** → Adds to exclusion list
- **"Only X"** → Replaces filter entirely
- **"Include X" / "Add X"** → Appends to existing filters
- **"Drill into X by Y"** → Adds dimension and filter
- **"Same period"** → Inherits time range
- **"For region Z"** → Adds regional filter
- **"Show top N"** → Limits results

## Chart Types by Intent

| Intent | Primary Chart | Alternative |
|--------|---------------|-------------|
| TOP_N_RANKING | Column | Bar |
| COST_BREAKDOWN | Stacked Bar | Column |
| COST_TREND | Line | Area |
| ANOMALY_ANALYSIS | Line (with spikes) | Scatter |
| COMPARATIVE | Clustered Bar | Column |
| UTILIZATION | Scatter | Bar |

## Configuration Checklist

Before using, ensure these are set:

```bash
# Required
AWS_REGION=us-east-1
AWS_CUR_DATABASE=cost_usage_db
AWS_CUR_TABLE=cur_dazn_linked

# AWS credentials via IAM role (recommended) or default credential chain
# For local dev: uses ~/.aws/credentials or environment variables
# For production: uses IAM task role (ECS) or instance profile (EC2)

# Optional (has defaults)
BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0
MAX_TOKENS=4000
TEMPERATURE=0.7
```

## Troubleshooting

### Issue: "No data found"
- Check CUR table exists in Athena
- Verify date range has data
- Confirm partition columns (year, month, day)

### Issue: "Athena timeout"
- Increase query timeout in settings
- Reduce date range
- Check Athena service quotas

### Issue: "Intent classified as OTHER"
- Query may be too vague
- System will ask clarification question
- Rephrase with specific service/metric/time

### Issue: "Follow-up not working"
- Ensure the same thread is used (conversation_id or auto-derived user session)
- Check conversation_manager logs
- Verify context exists for the previous turn

## Testing All Few-Shot Examples

Run this script to test all 15 examples:

```bash
#!/bin/bash

# Example 1: EC2 breakdown
curl -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message": "Break down EC2 costs for last month by instance type", "conversation_id": "test-001"}'

# Example 1a: Region drilldown
curl -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message": "Which region had the most expensive m5.large usage?", "conversation_id": "test-001"}'

# Example 2: S3 spike
curl -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message": "Why did S3 costs spike in September 2025?", "conversation_id": "test-002"}'

# Example 3: Top services
curl -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
  -d '{"message": "Top 5 services by cost for Q3 2025", "conversation_id": "test-003"}'

# ... (add remaining examples)
```

## Next Steps

1. **Test with Real Data**: Point to your actual CUR table
2. **Customize Intents**: Add domain-specific patterns to `intent_classifier.py`
3. **Enhance Templates**: Add custom SQL templates to `athena_cur_templates.py`
4. **Persist Context**: Replace in-memory storage with ChromaDB/Postgres
5. **Add Caching**: Implement Valkey for frequent queries

## Additional Resources

- **Production Deployment**: See [AWS Deployment Guide](./AWS_DEPLOYMENT_GUIDE.md)
- **Deep Dive**: Read [UPS Architecture](./UPS_ARCHITECTURE.md) for technical details
- **Advanced Filters**: See [Phase 2 Documentation](./PHASE_2_ADVANCED_FILTERS.md)
- **System Design**: Review [Backend Architecture](./BACKEND_ARCHITECTURE.md)
- **CUR Setup**: Configure 36-month history with [CUR Setup Guide](./SETUP_CUR.md)
- **Troubleshooting**: Check [Troubleshooting Guide](./TROUBLESHOOTING.md)
- **Scripts**: Review [Scripts README](../scripts/README.md) for operational tools

## Support

For issues or questions:
1. Check the [AWS Deployment Guide](./AWS_DEPLOYMENT_GUIDE.md) for detailed documentation
2. Review logs in `backend/*.log`
3. Enable debug logging: `LOG_LEVEL=DEBUG`
4. Contact: Platform Team

---

**Status**: ✅ Multi-agent workflow enabled by default
**Version**: 3.0 (Multi-Agent Default)
**Last Updated**: November 2025
