# FinOps Database Migrations - Quick Reference

## 🚀 Quick Commands

```bash
# Navigate to backend directory
cd backend

# Run all migrations
alembic upgrade head

# Check status
alembic current

# Rollback one migration
alembic downgrade -1

# Using the helper script (recommended)
python run_migrations.py upgrade
python run_migrations.py status
python run_migrations.py downgrade
```

## 📊 Database Tables Created

### 1. conversation_threads
**Purpose:** Store conversation metadata and thread information

| Column | Type | Description |
|--------|------|-------------|
| thread_id | UUID | Primary key |
| user_id | VARCHAR(255) | User identifier |
| title | VARCHAR(500) | Thread title |
| created_at | TIMESTAMP | Creation time |
| updated_at | TIMESTAMP | Last update time |
| metadata | JSONB | Flexible metadata |
| is_active | BOOLEAN | Soft delete flag |

**Indexes:** user_id, is_active, created_at, updated_at, metadata (GIN)

### 2. conversation_messages
**Purpose:** Store individual messages within conversations

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| thread_id | UUID | Foreign key to threads |
| role | ENUM | user/assistant/system |
| content | TEXT | Message content |
| message_type | ENUM | query/context/response/tool_call |
| metadata | JSONB | Message metadata |
| ordering_index | INTEGER | Message order |
| created_at | TIMESTAMP | Creation time |

**Indexes:** thread_id, role, message_type, content (full-text)

### 3. query_intents
**Purpose:** Track query intent analysis and classification

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| thread_id | UUID | Foreign key to threads |
| message_id | UUID | Foreign key to messages |
| original_query | TEXT | Original user query |
| rewritten_query | TEXT | Optimized query |
| intent_type | ENUM | 17 intent types |
| intent_confidence | NUMERIC(3,2) | 0.00-1.00 |
| extracted_dimensions | JSONB | Query dimensions |

**Intent Types:** cost_analysis, optimization_recommendation, anomaly_detection, budget_tracking, resource_utilization, cost_allocation, forecast_prediction, spend_comparison, service_breakdown, tagging_compliance, savings_opportunity, rightsizing, reserved_instance_analysis, spot_instance_analysis, general_query, clarification_needed, multi_intent

### 4. agent_executions
**Purpose:** Log agent execution with performance metrics

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| thread_id | UUID | Foreign key to threads |
| message_id | UUID | Optional FK to messages |
| agent_name | VARCHAR(255) | Agent identifier |
| agent_type | ENUM | Agent category |
| input_query | TEXT | Input to agent |
| output_response | JSONB | Agent output |
| tools_used | JSONB | Tools/services used |
| execution_time_ms | INTEGER | Execution duration |
| status | ENUM | success/error/partial/timeout/cancelled |
| error_message | TEXT | Error details |
| created_at | TIMESTAMP | Start time |
| completed_at | TIMESTAMP | End time |

**Agent Types:** supervisor, cost_analysis, optimization, infrastructure, anomaly_detection, forecasting, recommendation, report_generation, query_rewriter, intent_classifier, data_retriever

### 5. optimization_recommendations
**Purpose:** Store cost optimization strategies and recommendations

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| thread_id | UUID | Optional FK to threads |
| agent_execution_id | UUID | Optional FK to executions |
| service | VARCHAR(255) | AWS service |
| strategy_id | VARCHAR(100) | Strategy identifier |
| strategy_name | VARCHAR(255) | Strategy name |
| description | TEXT | Detailed description |
| estimated_savings_min_percent | NUMERIC(5,2) | Min savings % |
| estimated_savings_max_percent | NUMERIC(5,2) | Max savings % |
| estimated_savings_min_usd | NUMERIC(12,2) | Min savings $ |
| estimated_savings_max_usd | NUMERIC(12,2) | Max savings $ |
| implementation_effort_hours | NUMERIC(6,2) | Effort estimate |
| implementation_difficulty | ENUM | low/medium/high/very_high |
| recommendation_steps | JSONB | Implementation steps |
| confidence_score | NUMERIC(3,2) | 0.00-1.00 |
| validation_count | INTEGER | Validation count |
| status | ENUM | active/implemented/rejected/obsolete/under_review |
| priority_score | INTEGER | Auto-calculated 1-100 |
| tags | JSONB | Categorization tags |
| created_at | TIMESTAMP | Creation time |
| expires_at | TIMESTAMP | Expiration time |

## 🔗 Relationships

```
conversation_threads
├── conversation_messages (1:N, CASCADE DELETE)
├── query_intents (1:N, CASCADE DELETE)
├── agent_executions (1:N, CASCADE DELETE)
└── optimization_recommendations (1:N, SET NULL)

conversation_messages
└── query_intents (1:N, CASCADE DELETE)

agent_executions
└── optimization_recommendations (1:N, SET NULL)
```

## 📝 Common Queries

### Get user's active conversations
```sql
SELECT * FROM conversation_threads 
WHERE user_id = 'user123' AND is_active = true 
ORDER BY updated_at DESC 
LIMIT 10;
```

### Get conversation with messages
```sql
SELECT 
    ct.*,
    json_agg(
        json_build_object(
            'id', cm.id,
            'role', cm.role,
            'content', cm.content,
            'created_at', cm.created_at
        ) ORDER BY cm.ordering_index
    ) as messages
FROM conversation_threads ct
LEFT JOIN conversation_messages cm ON ct.thread_id = cm.thread_id
WHERE ct.thread_id = 'thread-uuid'
GROUP BY ct.thread_id;
```

### Top optimization recommendations
```sql
SELECT 
    service,
    strategy_name,
    estimated_savings_max_percent,
    implementation_effort_hours,
    priority_score,
    status
FROM optimization_recommendations 
WHERE status = 'active' 
ORDER BY priority_score DESC 
LIMIT 20;
```

### Agent performance metrics (last 7 days)
```sql
SELECT 
    agent_type,
    agent_name,
    COUNT(*) as executions,
    AVG(execution_time_ms) as avg_time_ms,
    ROUND(100.0 * SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate
FROM agent_executions 
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY agent_type, agent_name
ORDER BY executions DESC;
```

### Low confidence query intents
```sql
SELECT 
    qi.intent_type,
    qi.intent_confidence,
    qi.original_query,
    cm.created_at
FROM query_intents qi
JOIN conversation_messages cm ON qi.message_id = cm.id
WHERE qi.intent_confidence < 0.7
ORDER BY qi.created_at DESC
LIMIT 50;
```

### Full-text search in conversations
```sql
SELECT 
    cm.*,
    ct.title,
    ct.user_id
FROM conversation_messages cm
JOIN conversation_threads ct ON cm.thread_id = ct.thread_id
WHERE to_tsvector('english', cm.content) @@ to_tsquery('english', 'ec2 & cost')
ORDER BY cm.created_at DESC;
```

## 🛠️ Maintenance

### Update statistics
```sql
ANALYZE conversation_threads;
ANALYZE conversation_messages;
ANALYZE query_intents;
ANALYZE agent_executions;
ANALYZE optimization_recommendations;
```

### Check table sizes
```sql
SELECT 
    tablename,
    pg_size_pretty(pg_total_relation_size('public.'||tablename)) AS size,
    (SELECT COUNT(*) FROM information_schema.columns 
     WHERE table_name = tablename) as columns
FROM pg_tables 
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size('public.'||tablename) DESC;
```

### Monitor index usage
```sql
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan as scans,
    pg_size_pretty(pg_relation_size(indexrelid)) as size
FROM pg_stat_user_indexes 
WHERE schemaname = 'public'
ORDER BY idx_scan DESC;
```

## 🔧 Troubleshooting

### Check migration status
```bash
alembic current
alembic history --verbose
```

### Force stamp revision (if out of sync)
```bash
# Stamp to specific revision
alembic stamp 005

# Stamp to head
alembic stamp head
```

### Backup before changes
```bash
pg_dump -U username -d finops > backup_$(date +%Y%m%d_%H%M%S).sql
```

### Restore from backup
```bash
psql -U username -d finops < backup_20251112_100000.sql
```

## 📚 Files Structure

```
backend/
├── alembic/
│   ├── versions/
│   │   ├── 001_create_conversation_threads.py
│   │   ├── 002_create_conversation_messages.py
│   │   ├── 003_create_query_intents.py
│   │   ├── 004_create_agent_executions.py
│   │   └── 005_create_optimization_recommendations.py
│   ├── env.py
│   ├── script.py.mako
│   └── README.md
├── alembic.ini
└── run_migrations.py
```

## 🎯 Best Practices

1. **Always backup before migrations**
2. **Test in development first**
3. **Review migration SQL before applying**
4. **Monitor performance after migrations**
5. **Keep migrations small and focused**
6. **Document schema changes**
7. **Use transactions for data migrations**
8. **Validate data integrity after changes**

## 📞 Support

For issues or questions about the migration system:
1. Check logs: `alembic.log`
2. Review PostgreSQL logs
3. Verify database connectivity
4. Check permissions (CREATE, ALTER, DROP)
