"""
FinOps Conversation Threading - Database Schema Visualization

This file provides SQL scripts to visualize and explore the complete schema.
"""

-- ============================================================================
-- SCHEMA OVERVIEW
-- ============================================================================

-- List all tables created by migrations
SELECT 
    table_name,
    (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = t.table_name) as column_count
FROM information_schema.tables t
WHERE table_schema = 'public' 
    AND table_name IN (
        'conversation_threads',
        'conversation_messages', 
        'query_intents',
        'agent_executions',
        'optimization_recommendations'
    )
ORDER BY table_name;

-- ============================================================================
-- TABLE RELATIONSHIPS (Foreign Keys)
-- ============================================================================

SELECT
    tc.table_name as from_table,
    kcu.column_name as from_column,
    ccu.table_name as to_table,
    ccu.column_name as to_column,
    rc.delete_rule
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu 
    ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.referential_constraints rc 
    ON tc.constraint_name = rc.constraint_name
JOIN information_schema.constraint_column_usage ccu 
    ON rc.constraint_name = ccu.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
    AND tc.table_schema = 'public'
ORDER BY from_table, from_column;

-- ============================================================================
-- INDEXES OVERVIEW
-- ============================================================================

SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
    AND tablename IN (
        'conversation_threads',
        'conversation_messages',
        'query_intents',
        'agent_executions',
        'optimization_recommendations'
    )
ORDER BY tablename, indexname;

-- ============================================================================
-- ENUM TYPES
-- ============================================================================

SELECT 
    t.typname as enum_name,
    string_agg(e.enumlabel, ', ' ORDER BY e.enumsortorder) as enum_values,
    COUNT(*) as value_count
FROM pg_type t
JOIN pg_enum e ON t.oid = e.enumtypid
WHERE t.typname IN (
    'message_role',
    'message_type',
    'intent_type',
    'agent_type',
    'execution_status',
    'implementation_difficulty',
    'recommendation_status'
)
GROUP BY t.typname
ORDER BY t.typname;

-- ============================================================================
-- TRIGGERS
-- ============================================================================

SELECT
    trigger_name,
    event_object_table as table_name,
    action_timing,
    event_manipulation,
    action_statement
FROM information_schema.triggers
WHERE trigger_schema = 'public'
ORDER BY event_object_table, trigger_name;

-- ============================================================================
-- TABLE SIZES AND ROW COUNTS
-- ============================================================================

SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as total_size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) as table_size,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename)) as index_size
FROM pg_tables
WHERE schemaname = 'public'
    AND tablename IN (
        'conversation_threads',
        'conversation_messages',
        'query_intents',
        'agent_executions',
        'optimization_recommendations'
    )
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- ============================================================================
-- DETAILED COLUMN INFORMATION
-- ============================================================================

-- conversation_threads columns
SELECT 
    'conversation_threads' as table_name,
    column_name,
    data_type,
    character_maximum_length,
    is_nullable,
    column_default,
    CASE WHEN pk.column_name IS NOT NULL THEN 'YES' ELSE 'NO' END as is_primary_key
FROM information_schema.columns c
LEFT JOIN (
    SELECT ku.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage ku 
        ON tc.constraint_name = ku.constraint_name
    WHERE tc.table_name = 'conversation_threads' 
        AND tc.constraint_type = 'PRIMARY KEY'
) pk ON c.column_name = pk.column_name
WHERE c.table_name = 'conversation_threads'
ORDER BY c.ordinal_position;

-- conversation_messages columns
SELECT 
    'conversation_messages' as table_name,
    column_name,
    data_type,
    character_maximum_length,
    is_nullable,
    column_default,
    CASE WHEN pk.column_name IS NOT NULL THEN 'YES' ELSE 'NO' END as is_primary_key
FROM information_schema.columns c
LEFT JOIN (
    SELECT ku.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage ku 
        ON tc.constraint_name = ku.constraint_name
    WHERE tc.table_name = 'conversation_messages' 
        AND tc.constraint_type = 'PRIMARY KEY'
) pk ON c.column_name = pk.column_name
WHERE c.table_name = 'conversation_messages'
ORDER BY c.ordinal_position;

-- query_intents columns
SELECT 
    'query_intents' as table_name,
    column_name,
    data_type,
    character_maximum_length,
    is_nullable,
    column_default,
    CASE WHEN pk.column_name IS NOT NULL THEN 'YES' ELSE 'NO' END as is_primary_key
FROM information_schema.columns c
LEFT JOIN (
    SELECT ku.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage ku 
        ON tc.constraint_name = ku.constraint_name
    WHERE tc.table_name = 'query_intents' 
        AND tc.constraint_type = 'PRIMARY KEY'
) pk ON c.column_name = pk.column_name
WHERE c.table_name = 'query_intents'
ORDER BY c.ordinal_position;

-- agent_executions columns
SELECT 
    'agent_executions' as table_name,
    column_name,
    data_type,
    character_maximum_length,
    is_nullable,
    column_default,
    CASE WHEN pk.column_name IS NOT NULL THEN 'YES' ELSE 'NO' END as is_primary_key
FROM information_schema.columns c
LEFT JOIN (
    SELECT ku.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage ku 
        ON tc.constraint_name = ku.constraint_name
    WHERE tc.table_name = 'agent_executions' 
        AND tc.constraint_type = 'PRIMARY KEY'
) pk ON c.column_name = pk.column_name
WHERE c.table_name = 'agent_executions'
ORDER BY c.ordinal_position;

-- optimization_recommendations columns
SELECT 
    'optimization_recommendations' as table_name,
    column_name,
    data_type,
    character_maximum_length,
    is_nullable,
    column_default,
    CASE WHEN pk.column_name IS NOT NULL THEN 'YES' ELSE 'NO' END as is_primary_key
FROM information_schema.columns c
LEFT JOIN (
    SELECT ku.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage ku 
        ON tc.constraint_name = ku.constraint_name
    WHERE tc.table_name = 'optimization_recommendations' 
        AND tc.constraint_type = 'PRIMARY KEY'
) pk ON c.column_name = pk.column_name
WHERE c.table_name = 'optimization_recommendations'
ORDER BY c.ordinal_position;

-- ============================================================================
-- CHECK CONSTRAINTS
-- ============================================================================

SELECT
    tc.table_name,
    tc.constraint_name,
    cc.check_clause
FROM information_schema.table_constraints tc
JOIN information_schema.check_constraints cc 
    ON tc.constraint_name = cc.constraint_name
WHERE tc.constraint_type = 'CHECK'
    AND tc.table_schema = 'public'
ORDER BY tc.table_name, tc.constraint_name;

-- ============================================================================
-- INDEX USAGE STATISTICS
-- ============================================================================

SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan as times_used,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
    AND tablename IN (
        'conversation_threads',
        'conversation_messages',
        'query_intents',
        'agent_executions',
        'optimization_recommendations'
    )
ORDER BY idx_scan DESC;

-- ============================================================================
-- SCHEMA DIAGRAM (ASCII Art)
-- ============================================================================

/*
                        ┌─────────────────────────┐
                        │  conversation_threads   │
                        ├─────────────────────────┤
                        │ PK thread_id (UUID)     │
                        │    user_id              │
                        │    title                │
                        │    created_at           │
                        │    updated_at           │
                        │    metadata (JSONB)     │
                        │    is_active            │
                        └────────────┬────────────┘
                                     │
                 ┌───────────────────┼───────────────────┬─────────────────┐
                 │                   │                   │                 │
                 ▼                   ▼                   ▼                 ▼
    ┌────────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────────────┐
    │conversation_messages│ │  query_intents   │  │agent_executions  │  │optimization_             │
    ├────────────────────┤  ├──────────────────┤  ├──────────────────┤  │recommendations          │
    │PK id (UUID)        │  │PK id (UUID)      │  │PK id (UUID)      │  ├─────────────────────────┤
    │FK thread_id ───────┼──│FK thread_id      │  │FK thread_id      │  │PK id (UUID)             │
    │   role (ENUM)      │  │FK message_id ────┼──┤FK message_id     │  │FK thread_id (NULL)      │
    │   content          │  │   original_query │  │   agent_name     │  │FK agent_execution_id ───┼──┐
    │   message_type     │  │   rewritten_query│  │   agent_type     │  │   service               │  │
    │   metadata (JSONB) │  │   intent_type    │  │   input_query    │  │   strategy_id           │  │
    │   ordering_index   │  │   intent_confid. │  │   output_resp.   │  │   strategy_name         │  │
    │   created_at       │  │   extracted_dims │  │   tools_used     │  │   description           │  │
    │   updated_at       │  │   created_at     │  │   execution_time │  │   savings (min/max)     │  │
    └────────────────────┘  └──────────────────┘  │   status (ENUM)  │  │   effort_hours          │  │
                                                   │   error_message  │  │   difficulty (ENUM)     │  │
                                                   │   created_at     │  │   steps (JSONB)         │  │
                                                   │   completed_at   │  │   confidence_score      │  │
                                                   └──────────────────┘  │   validation_count      │  │
                                                              │          │   status (ENUM)         │  │
                                                              └──────────┤   priority_score        │  │
                                                                         │   tags (JSONB)          │  │
                                                                         │   created_at            │  │
                                                                         │   expires_at            │  │
                                                                         └─────────────────────────┘

Relationship Types:
─────> CASCADE DELETE (parent deletion removes children)
- - -> SET NULL (parent deletion sets FK to NULL)

Foreign Keys:
• conversation_messages.thread_id → conversation_threads.thread_id (CASCADE)
• query_intents.thread_id → conversation_threads.thread_id (CASCADE)
• query_intents.message_id → conversation_messages.id (CASCADE)
• agent_executions.thread_id → conversation_threads.thread_id (CASCADE)
• agent_executions.message_id → conversation_messages.id (SET NULL)
• optimization_recommendations.thread_id → conversation_threads.thread_id (SET NULL)
• optimization_recommendations.agent_execution_id → agent_executions.id (SET NULL)
*/

-- ============================================================================
-- SAMPLE DATA QUERIES
-- ============================================================================

-- Example: Get a complete conversation with all related data
WITH conversation_data AS (
    SELECT 
        ct.thread_id,
        ct.user_id,
        ct.title,
        ct.created_at as thread_created,
        json_agg(
            json_build_object(
                'message_id', cm.id,
                'role', cm.role,
                'content', cm.content,
                'type', cm.message_type,
                'order', cm.ordering_index,
                'created_at', cm.created_at
            ) ORDER BY cm.ordering_index
        ) FILTER (WHERE cm.id IS NOT NULL) as messages,
        (
            SELECT json_agg(
                json_build_object(
                    'intent', qi.intent_type,
                    'confidence', qi.intent_confidence,
                    'dimensions', qi.extracted_dimensions
                )
            )
            FROM query_intents qi
            WHERE qi.thread_id = ct.thread_id
        ) as intents,
        (
            SELECT json_agg(
                json_build_object(
                    'agent', ae.agent_name,
                    'status', ae.status,
                    'execution_time', ae.execution_time_ms
                )
            )
            FROM agent_executions ae
            WHERE ae.thread_id = ct.thread_id
        ) as executions
    FROM conversation_threads ct
    LEFT JOIN conversation_messages cm ON ct.thread_id = cm.thread_id
    GROUP BY ct.thread_id
)
SELECT * FROM conversation_data
LIMIT 1;

-- ============================================================================
-- TESTING QUERIES
-- ============================================================================

-- Test data integrity
DO $$
DECLARE
    test_thread_id UUID;
    test_message_id UUID;
BEGIN
    -- Insert test thread
    INSERT INTO conversation_threads (user_id, title, metadata)
    VALUES ('test_user', 'Test Thread', '{"environment": "testing"}'::jsonb)
    RETURNING thread_id INTO test_thread_id;
    
    -- Insert test message
    INSERT INTO conversation_messages (thread_id, role, content, message_type, ordering_index)
    VALUES (test_thread_id, 'user', 'Test message', 'query', 0)
    RETURNING id INTO test_message_id;
    
    -- Insert test intent
    INSERT INTO query_intents (thread_id, message_id, original_query, intent_type, intent_confidence)
    VALUES (test_thread_id, test_message_id, 'Test query', 'cost_analysis', 0.95);
    
    -- Insert test execution
    INSERT INTO agent_executions (
        thread_id, agent_name, agent_type, input_query, 
        execution_time_ms, status
    )
    VALUES (
        test_thread_id, 'TestAgent', 'cost_analysis', 'Test query',
        100, 'success'
    );
    
    -- Insert test recommendation
    INSERT INTO optimization_recommendations (
        service, strategy_id, strategy_name, description,
        estimated_savings_min_percent, estimated_savings_max_percent,
        implementation_effort_hours, confidence_score
    )
    VALUES (
        'EC2', 'test_strategy', 'Test Strategy', 'Test description',
        10.0, 20.0, 2.0, 0.85
    );
    
    RAISE NOTICE 'Test data inserted successfully!';
    RAISE NOTICE 'Thread ID: %', test_thread_id;
    RAISE NOTICE 'Message ID: %', test_message_id;
    
    -- Cleanup test data
    DELETE FROM conversation_threads WHERE thread_id = test_thread_id;
    DELETE FROM optimization_recommendations WHERE strategy_id = 'test_strategy';
    
    RAISE NOTICE 'Test data cleaned up successfully!';
END $$;
