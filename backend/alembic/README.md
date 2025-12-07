# FinOps Conversation Threading Database Migrations

This directory contains Alembic database migrations for the FinOps conversation threading system. These migrations create a comprehensive data model for tracking conversations, messages, intents, agent executions, and optimization recommendations.

## 📋 Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Migration Overview](#migration-overview)
- [Database Schema](#database-schema)
- [Usage Examples](#usage-examples)
- [Rollback Instructions](#rollback-instructions)
- [Performance Considerations](#performance-considerations)

## Prerequisites

Before running these migrations, ensure you have:

1. **PostgreSQL 12+** installed and running
2. **Python 3.8+** with the following packages:
   ```bash
   pip install alembic sqlalchemy psycopg2-binary
   ```
3. **Database connection** configured in `alembic.ini`

## Quick Start

### 1. Configure Database Connection

Edit `alembic.ini` and update the database URL:

```ini
sqlalchemy.url = postgresql://username:password@localhost:5432/finops
```

Or use environment variables:

```bash
export DATABASE_URL="postgresql://username:password@localhost:5432/finops"
```

### 2. Run Migrations

```bash
# Run all pending migrations
alembic upgrade head

# Run migrations one at a time
alembic upgrade +1

# Check current migration status
alembic current

# View migration history
alembic history --verbose
```

### 3. Rollback Migrations

```bash
# Rollback one migration
alembic downgrade -1

# Rollback to a specific revision
alembic downgrade 003

# Rollback all migrations
alembic downgrade base
```

## Migration Overview

### Migration 001: conversation_threads
**File:** `001_create_conversation_threads.py`

Creates the main conversation threads table with:
- UUID primary key (`thread_id`)
- User identification and metadata
- Soft delete capability (`is_active`)
- Automatic timestamp management
- Comprehensive indexing for performance

**Key Features:**
- Automatic `updated_at` trigger
- GIN index on JSONB metadata
- Composite indexes for common query patterns

### Migration 002: conversation_messages
**File:** `002_create_conversation_messages.py`

Creates the messages table for storing individual conversation messages:
- UUID primary key with foreign key to threads
- Message role ENUM (user/assistant/system)
- Message type ENUM (query/context/response/tool_call)
- Ordering index for conversation flow
- Full-text search on message content

**Key Features:**
- Cascade delete on thread deletion
- Automatic parent thread timestamp update
- Full-text search capabilities
- Unique constraint on thread + ordering

### Migration 003: query_intents
**File:** `003_create_query_intents.py`

Creates the query intents table for tracking query analysis:
- Intent classification with 17 intent types
- Original and rewritten query storage
- Confidence scoring (0.00-1.00)
- Extracted dimensions in JSONB format

**Intent Types:**
- cost_analysis
- optimization_recommendation
- cost_anomaly_detection
- budget_tracking
- resource_utilization
- cost_allocation
- forecast_prediction
- spend_comparison
- service_breakdown
- tagging_compliance
- savings_opportunity
- rightsizing
- reserved_instance_analysis
- spot_instance_analysis
- general_query
- clarification_needed
- multi_intent

**Key Features:**
- Check constraint on confidence score
- Full-text search on queries
- GIN index on extracted dimensions

### Migration 004: agent_executions
**File:** `004_create_agent_executions.py`

Creates the agent executions table for tracking agent performance:
- Agent type and name classification
- Execution time tracking in milliseconds
- Tools used (JSONB array)
- Error handling with stack traces
- Status tracking (success/error/partial/timeout/cancelled)

**Agent Types:**
- supervisor
- cost_analysis
- optimization
- infrastructure
- anomaly_detection
- forecasting
- recommendation
- report_generation
- query_rewriter
- intent_classifier
- data_retriever

**Key Features:**
- Performance monitoring indexes
- Partial index for failed executions
- Full-text search on input queries

### Migration 005: optimization_recommendations
**File:** `005_create_optimization_recommendations.py`

Creates the optimization recommendations table:
- Savings estimates (min/max percentages and USD)
- Implementation effort in hours
- Difficulty level classification
- Confidence and validation tracking
- Priority score auto-calculation
- Expiration tracking for time-sensitive recommendations

**Key Features:**
- Automatic priority calculation trigger
- Multiple check constraints for data integrity
- Status tracking (active/implemented/rejected/obsolete/under_review)
- Full-text search on descriptions
- GIN indexes on JSONB fields

## Database Schema

### Entity Relationship Diagram

```
conversation_threads (1) ─┬─ (N) conversation_messages
                          │
                          ├─ (N) query_intents
                          │
                          ├─ (N) agent_executions
                          │
                          └─ (N) optimization_recommendations
                                      │
                                      └─ (1) agent_executions (optional)

conversation_messages (1) ── (N) query_intents

agent_executions (1) ── (N) optimization_recommendations
```

### Key Relationships

- `conversation_messages` CASCADE deletes with `conversation_threads`
- `query_intents` CASCADE deletes with threads and messages
- `agent_executions` CASCADE deletes with threads
- `optimization_recommendations` uses SET NULL for optional relationships

## Usage Examples

### Python SQLAlchemy Models

```python
from sqlalchemy import Column, String, DateTime, Boolean, Integer, Numeric, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
import uuid

Base = declarative_base()

class ConversationThread(Base):
    __tablename__ = 'conversation_threads'
    
    thread_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), nullable=False, index=True)
    title = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default='CURRENT_TIMESTAMP')
    updated_at = Column(DateTime(timezone=True), server_default='CURRENT_TIMESTAMP')
    metadata = Column(JSONB, default={})
    is_active = Column(Boolean, default=True)

class ConversationMessage(Base):
    __tablename__ = 'conversation_messages'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(UUID(as_uuid=True), ForeignKey('conversation_threads.thread_id', ondelete='CASCADE'))
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    message_type = Column(String(20), nullable=False)
    metadata = Column(JSONB, default={})
    ordering_index = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default='CURRENT_TIMESTAMP')
```

### Query Examples

```sql
-- Get all active threads for a user
SELECT * FROM conversation_threads 
WHERE user_id = 'user123' AND is_active = true 
ORDER BY updated_at DESC;

-- Get messages in a conversation
SELECT * FROM conversation_messages 
WHERE thread_id = 'thread-uuid-here' 
ORDER BY ordering_index;

-- Find high-value, low-effort recommendations
SELECT * FROM optimization_recommendations 
WHERE status = 'active' 
  AND estimated_savings_max_percent > 20 
  AND implementation_effort_hours < 8 
ORDER BY priority_score DESC;

-- Search messages using full-text search
SELECT * FROM conversation_messages 
WHERE to_tsvector('english', content) @@ to_tsquery('english', 'cost & optimization');

-- Get agent performance metrics
SELECT 
    agent_name,
    agent_type,
    COUNT(*) as execution_count,
    AVG(execution_time_ms) as avg_execution_time,
    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END)::float / COUNT(*) as success_rate
FROM agent_executions 
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY agent_name, agent_type;

-- Find low-confidence query intents
SELECT qi.*, cm.content 
FROM query_intents qi 
JOIN conversation_messages cm ON qi.message_id = cm.id 
WHERE qi.intent_confidence < 0.7 
ORDER BY qi.created_at DESC;
```

## Rollback Instructions

### Safe Rollback Process

1. **Check current state:**
   ```bash
   alembic current
   ```

2. **Backup database:**
   ```bash
   pg_dump -U username finops > backup_before_rollback.sql
   ```

3. **Rollback one migration:**
   ```bash
   alembic downgrade -1
   ```

4. **Verify rollback:**
   ```bash
   alembic current
   psql -U username -d finops -c "\dt"
   ```

### Rollback Specific Migrations

```bash
# Rollback to migration 003 (removes recommendations and agent executions)
alembic downgrade 003

# Rollback all conversation tracking (remove all tables)
alembic downgrade base
```

## Performance Considerations

### Index Usage

The migrations create extensive indexes for optimal query performance:

1. **Foreign Key Indexes**: All foreign keys are indexed
2. **Composite Indexes**: Common query patterns use composite indexes
3. **GIN Indexes**: JSONB fields use GIN indexes for efficient querying
4. **Full-Text Search**: Message content and queries support full-text search
5. **Partial Indexes**: Specialized indexes for failed executions and active recommendations

### Query Optimization Tips

1. **Use composite indexes**: Query on `user_id` and `is_active` together
2. **JSONB queries**: Use `@>` operator for containment checks
3. **Pagination**: Always use `LIMIT` and `OFFSET` with large result sets
4. **Date ranges**: Index on timestamps supports efficient date range queries

### Monitoring

Monitor these key metrics:

```sql
-- Table sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables 
WHERE schemaname = 'public';

-- Index usage
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes 
ORDER BY idx_scan DESC;

-- Slow queries (requires pg_stat_statements extension)
SELECT 
    query,
    calls,
    mean_exec_time,
    max_exec_time
FROM pg_stat_statements 
WHERE query LIKE '%conversation_%'
ORDER BY mean_exec_time DESC;
```

## Troubleshooting

### Common Issues

1. **Migration fails with "relation already exists"**
   - Check current migration state: `alembic current`
   - Verify database state: `psql -d finops -c "\dt"`
   - May need to stamp current revision: `alembic stamp head`

2. **Foreign key constraint violations**
   - Ensure proper deletion order (child tables before parent)
   - Check CASCADE delete rules are working

3. **Performance issues**
   - Run `ANALYZE` on tables after bulk inserts
   - Check index usage with `EXPLAIN ANALYZE`
   - Consider partitioning for very large tables

### Getting Help

For issues or questions:
1. Check PostgreSQL logs for detailed error messages
2. Use `alembic history` to verify migration state
3. Review migration files for comments and documentation

## Maintenance

### Regular Tasks

```sql
-- Analyze tables for query optimizer
ANALYZE conversation_threads;
ANALYZE conversation_messages;
ANALYZE query_intents;
ANALYZE agent_executions;
ANALYZE optimization_recommendations;

-- Vacuum to reclaim space
VACUUM ANALYZE conversation_threads;

-- Check for bloat
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS total_size
FROM pg_tables 
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

## License

Part of the FinOps Orchestrator project.
