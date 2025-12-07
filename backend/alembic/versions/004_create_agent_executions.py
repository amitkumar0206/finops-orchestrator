"""create agent_executions table

Revision ID: 004
Revises: 003
Create Date: 2025-11-12 10:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Creates the agent_executions table for tracking agent execution logs and performance.
    
    This table stores detailed information about each agent execution, including input/output,
    tools used, execution time, and status for monitoring and debugging purposes.
    """
    # Create ENUM types for agent_type and execution_status (with IF NOT EXISTS for idempotency)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE agent_type AS ENUM (
                'supervisor',
                'cost_analysis',
                'optimization',
                'infrastructure',
                'anomaly_detection',
                'forecasting',
                'recommendation',
                'report_generation',
                'query_rewriter',
                'intent_classifier',
                'data_retriever'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE execution_status AS ENUM (
                'success',
                'error',
                'partial',
                'timeout',
                'cancelled'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create agent_executions table
    op.create_table(
        'agent_executions',
        # Primary key
        sa.Column(
            'id',
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text('gen_random_uuid()'),
            comment='Primary key, auto-generated UUID for the agent execution record'
        ),
        # Foreign key to conversation_threads
        sa.Column(
            'thread_id',
            UUID(as_uuid=True),
            sa.ForeignKey('conversation_threads.thread_id', ondelete='CASCADE'),
            nullable=False,
            comment='Foreign key reference to the parent conversation thread'
        ),
        # Optional foreign key to conversation_messages (if execution is tied to a specific message)
        sa.Column(
            'message_id',
            UUID(as_uuid=True),
            sa.ForeignKey('conversation_messages.id', ondelete='SET NULL'),
            nullable=True,
            comment='Optional foreign key reference to the message that triggered this execution'
        ),
        # Agent identification
        sa.Column(
            'agent_name',
            sa.String(255),
            nullable=False,
            comment='Name of the agent that was executed (e.g., "CostAnalysisAgent", "OptimizationEngine")'
        ),
        # Agent type classification
        sa.Column(
            'agent_type',
            sa.Text(),
            nullable=False,
            comment='Type/category of the agent for classification and filtering'
        ),
        # Input query/request
        sa.Column(
            'input_query',
            sa.Text,
            nullable=False,
            comment='The input query or request sent to the agent'
        ),
        # Output response
        sa.Column(
            'output_response',
            JSONB,
            nullable=True,
            comment='The structured output response from the agent in JSONB format'
        ),
        # Tools/services used during execution
        sa.Column(
            'tools_used',
            JSONB,
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
            comment='Array of tools/services used during execution (e.g., ["athena_query", "llm_service", "vector_search"])'
        ),
        # Performance metrics
        sa.Column(
            'execution_time_ms',
            sa.Integer,
            nullable=False,
            comment='Total execution time in milliseconds'
        ),
        # Execution status
        sa.Column(
            'status',
            sa.Text(),
            nullable=False,
            comment='Execution status: success (completed successfully), error (failed), partial (partially completed), timeout (exceeded time limit), cancelled (user cancelled)'
        ),
        # Error details (if any)
        sa.Column(
            'error_message',
            sa.Text,
            nullable=True,
            comment='Error message if the execution failed'
        ),
        sa.Column(
            'error_stack_trace',
            sa.Text,
            nullable=True,
            comment='Stack trace for debugging if the execution failed'
        ),
        # Additional metadata
        sa.Column(
            'metadata',
            JSONB,
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
            comment='Additional metadata like model version, token usage, cost, parent execution ID for nested calls, etc.'
        ),
        # Timestamp tracking
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when the agent execution started'
        ),
        sa.Column(
            'completed_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='Timestamp when the agent execution completed'
        ),
        # Check constraint for execution_time_ms
        sa.CheckConstraint(
            'execution_time_ms >= 0',
            name='ck_execution_time_positive'
        ),
        comment='Table for tracking agent executions with performance metrics and status'
    )
    
    # Alter columns to use ENUM types (after table creation to avoid type recreation issues)
    op.execute("ALTER TABLE agent_executions ALTER COLUMN agent_type TYPE agent_type USING agent_type::agent_type")
    op.execute("ALTER TABLE agent_executions ALTER COLUMN status TYPE execution_status USING status::execution_status")
    
    # Create indexes for performance optimization
    
    # Index on thread_id for thread-specific queries
    op.create_index(
        'idx_agent_executions_thread_id',
        'agent_executions',
        ['thread_id']
    )
    
    # Index on message_id for message-specific queries
    op.create_index(
        'idx_agent_executions_message_id',
        'agent_executions',
        ['message_id']
    )
    
    # Index on agent_name for agent-specific analytics
    op.create_index(
        'idx_agent_executions_agent_name',
        'agent_executions',
        ['agent_name']
    )
    
    # Index on agent_type for type-based analytics
    op.create_index(
        'idx_agent_executions_agent_type',
        'agent_executions',
        ['agent_type']
    )
    
    # Index on status for error tracking and monitoring
    op.create_index(
        'idx_agent_executions_status',
        'agent_executions',
        ['status']
    )
    
    # Composite index for agent performance analysis
    op.create_index(
        'idx_agent_executions_agent_status',
        'agent_executions',
        ['agent_name', 'status']
    )
    
    # Index on execution_time_ms for performance analysis
    op.create_index(
        'idx_agent_executions_execution_time',
        'agent_executions',
        ['execution_time_ms']
    )
    
    # Composite index for slow execution queries
    op.create_index(
        'idx_agent_executions_type_time',
        'agent_executions',
        ['agent_type', 'execution_time_ms']
    )
    
    # Index on created_at for chronological queries (for chronological ordering and time-based analytics)
    op.create_index(
        'idx_agent_executions_created_at',
        'agent_executions',
        ['created_at']
    )
    
    # Index on completed_at for execution tracking (for tracking execution completion times)
    op.create_index(
        'idx_agent_executions_completed_at',
        'agent_executions',
        ['completed_at']
    )
    
    # Composite index for recent executions by status (for monitoring recent executions by status)
    op.create_index(
        'idx_agent_executions_status_created',
        'agent_executions',
        ['status', 'created_at']
    )
    
    # GIN index on tools_used JSONB for tool usage analysis (for efficient JSONB querying on tools used)
    op.create_index(
        'idx_agent_executions_tools_gin',
        'agent_executions',
        ['tools_used'],
        postgresql_using='gin'
    )
    
    # GIN index on metadata JSONB (for efficient JSONB querying on metadata)
    op.create_index(
        'idx_agent_executions_metadata_gin',
        'agent_executions',
        ['metadata'],
        postgresql_using='gin'
    )
    
    # Full-text search index on input_query
    op.execute("""
        CREATE INDEX idx_agent_executions_input_query_fts 
        ON agent_executions 
        USING gin(to_tsvector('english', input_query));
    """)
    
    # Partial index for failed executions (for error analysis)
    op.execute("""
        CREATE INDEX idx_agent_executions_failed 
        ON agent_executions (agent_name, created_at) 
        WHERE status IN ('error', 'timeout', 'cancelled');
    """)


def downgrade() -> None:
    """
    Drops the agent_executions table and related objects.
    """
    # Drop indexes
    op.execute("DROP INDEX IF EXISTS idx_agent_executions_failed")
    op.execute("DROP INDEX IF EXISTS idx_agent_executions_input_query_fts")
    op.drop_index('idx_agent_executions_metadata_gin', table_name='agent_executions')
    op.drop_index('idx_agent_executions_tools_gin', table_name='agent_executions')
    op.drop_index('idx_agent_executions_status_created', table_name='agent_executions')
    op.drop_index('idx_agent_executions_completed_at', table_name='agent_executions')
    op.drop_index('idx_agent_executions_created_at', table_name='agent_executions')
    op.drop_index('idx_agent_executions_type_time', table_name='agent_executions')
    op.drop_index('idx_agent_executions_execution_time', table_name='agent_executions')
    op.drop_index('idx_agent_executions_agent_status', table_name='agent_executions')
    op.drop_index('idx_agent_executions_status', table_name='agent_executions')
    op.drop_index('idx_agent_executions_agent_type', table_name='agent_executions')
    op.drop_index('idx_agent_executions_agent_name', table_name='agent_executions')
    op.drop_index('idx_agent_executions_message_id', table_name='agent_executions')
    op.drop_index('idx_agent_executions_thread_id', table_name='agent_executions')
    
    # Drop table
    op.drop_table('agent_executions')
    
    # Drop ENUM types
    op.execute("DROP TYPE IF EXISTS execution_status")
    op.execute("DROP TYPE IF EXISTS agent_type")
