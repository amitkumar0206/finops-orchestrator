"""create query_intents table

Revision ID: 003
Revises: 002
Create Date: 2025-11-12 10:10:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Creates the query_intents table for storing query intent analysis results.
    
    This table tracks the interpretation and classification of user queries,
    including intent detection, query rewriting, and extracted dimensions for FinOps analysis.
    """
    # Create ENUM type for intent_type (with IF NOT EXISTS for idempotency)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE intent_type AS ENUM (
                'cost_analysis',
                'optimization_recommendation',
                'cost_anomaly_detection',
                'budget_tracking',
                'resource_utilization',
                'cost_allocation',
                'forecast_prediction',
                'spend_comparison',
                'service_breakdown',
                'tagging_compliance',
                'savings_opportunity',
                'rightsizing',
                'reserved_instance_analysis',
                'spot_instance_analysis',
                'general_query',
                'clarification_needed',
                'multi_intent'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create query_intents table
    op.create_table(
        'query_intents',
        # Primary key
        sa.Column(
            'id',
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text('gen_random_uuid()'),
            comment='Primary key, auto-generated UUID for the intent record'
        ),
        # Foreign key to conversation_threads
        sa.Column(
            'thread_id',
            UUID(as_uuid=True),
            sa.ForeignKey('conversation_threads.thread_id', ondelete='CASCADE'),
            nullable=False,
            comment='Foreign key reference to the parent conversation thread'
        ),
        # Foreign key to conversation_messages
        sa.Column(
            'message_id',
            UUID(as_uuid=True),
            sa.ForeignKey('conversation_messages.id', ondelete='CASCADE'),
            nullable=False,
            comment='Foreign key reference to the specific message this intent analysis is for'
        ),
        # Original user query
        sa.Column(
            'original_query',
            sa.Text,
            nullable=False,
            comment='The original user query text as received'
        ),
        # Rewritten/optimized query
        sa.Column(
            'rewritten_query',
            sa.Text,
            nullable=True,
            comment='The rewritten or optimized version of the query for better processing'
        ),
        # Intent classification
        sa.Column(
            'intent_type',
            sa.Text(),
            nullable=False,
            comment='The classified intent type of the query'
        ),
        # Confidence score
        sa.Column(
            'intent_confidence',
            sa.Numeric(3, 2),
            nullable=False,
            comment='Confidence score for the intent classification (0.00 to 1.00)'
        ),
        # Extracted dimensions for FinOps queries
        sa.Column(
            'extracted_dimensions',
            JSONB,
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
            comment='JSONB field storing extracted dimensions like time_range, services, accounts, regions, tags, cost_thresholds, etc.'
        ),
        # Timestamp tracking
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when the intent analysis was performed'
        ),
        # Check constraint for confidence score range
        sa.CheckConstraint(
            'intent_confidence >= 0.00 AND intent_confidence <= 1.00',
            name='ck_intent_confidence_range'
        ),
        comment='Table for storing query intent analysis and extracted dimensions for FinOps queries'
    )
    
    # Alter column to use ENUM type (after table creation to avoid type recreation issues)
    op.execute("ALTER TABLE query_intents ALTER COLUMN intent_type TYPE intent_type USING intent_type::intent_type")
    
    # Create indexes for performance optimization
    
    # Index on thread_id for thread-specific queries
    op.create_index(
        'idx_query_intents_thread_id',
        'query_intents',
        ['thread_id']
    )
    
    # Index on message_id for message-specific queries
    op.create_index(
        'idx_query_intents_message_id',
        'query_intents',
        ['message_id']
    )
    
    # Index on intent_type for analytics and filtering
    op.create_index(
        'idx_query_intents_type',
        'query_intents',
        ['intent_type']
    )
    
    # Composite index for intent_type + confidence for quality analysis
    op.create_index(
        'idx_query_intents_type_confidence',
        'query_intents',
        ['intent_type', 'intent_confidence']
    )
    
    # Index on confidence score for low-confidence query analysis
    op.create_index(
        'idx_query_intents_confidence',
        'query_intents',
        ['intent_confidence']
    )
    
    # Index on created_at for chronological queries
    op.create_index(
        'idx_query_intents_created_at',
        'query_intents',
        ['created_at']
    )
    
    # GIN index on extracted_dimensions JSONB for efficient JSON queries
    op.create_index(
        'idx_query_intents_dimensions_gin',
        'query_intents',
        ['extracted_dimensions'],
        postgresql_using='gin'
    )
    
    # Full-text search index on original_query
    op.execute("""
        CREATE INDEX idx_query_intents_original_query_fts 
        ON query_intents 
        USING gin(to_tsvector('english', original_query));
    """)
    
    # Full-text search index on rewritten_query
    op.execute("""
        CREATE INDEX idx_query_intents_rewritten_query_fts 
        ON query_intents 
        USING gin(to_tsvector('english', COALESCE(rewritten_query, '')));
    """)
    
    # Composite index for thread + intent type for conversation analysis
    op.create_index(
        'idx_query_intents_thread_type',
        'query_intents',
        ['thread_id', 'intent_type']
    )


def downgrade() -> None:
    """
    Drops the query_intents table and related objects.
    """
    # Drop indexes
    op.drop_index('idx_query_intents_thread_type', table_name='query_intents')
    op.execute("DROP INDEX IF EXISTS idx_query_intents_rewritten_query_fts")
    op.execute("DROP INDEX IF EXISTS idx_query_intents_original_query_fts")
    op.drop_index('idx_query_intents_dimensions_gin', table_name='query_intents')
    op.drop_index('idx_query_intents_created_at', table_name='query_intents')
    op.drop_index('idx_query_intents_confidence', table_name='query_intents')
    op.drop_index('idx_query_intents_type_confidence', table_name='query_intents')
    op.drop_index('idx_query_intents_type', table_name='query_intents')
    op.drop_index('idx_query_intents_message_id', table_name='query_intents')
    op.drop_index('idx_query_intents_thread_id', table_name='query_intents')
    
    # Drop table
    op.drop_table('query_intents')
    
    # Drop ENUM type
    op.execute("DROP TYPE IF EXISTS intent_type")
