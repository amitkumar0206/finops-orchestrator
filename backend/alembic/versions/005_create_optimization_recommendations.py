"""deprecated no-op migration to preserve linear history

Revision ID: 005
Revises: 004
Create Date: 2025-11-12 10:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Creates optimization_recommendations table with indexes and triggers.
    """
    # Create ENUM types (with IF NOT EXISTS for idempotency)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE recommendation_status AS ENUM (
                'pending',
                'in_progress', 
                'completed',
                'dismissed',
                'expired'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE implementation_difficulty AS ENUM (
                'low',
                'medium',
                'high'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create the optimization_recommendations table
    op.create_table(
        'optimization_recommendations',
        # Primary key
        sa.Column(
            'id',
            sa.Integer(),
            nullable=False,
            primary_key=True,
            autoincrement=True,
            comment='Primary key for the optimization_recommendations table'
        ),
        # Foreign keys
        sa.Column(
            'thread_id',
            UUID(as_uuid=True),
            sa.ForeignKey('conversation_threads.thread_id', ondelete='CASCADE'),
            nullable=True,
            comment='Reference to conversation thread that triggered this recommendation'
        ),
        sa.Column(
            'agent_execution_id',
            UUID(as_uuid=True),
            sa.ForeignKey('agent_executions.id', ondelete='SET NULL'),
            nullable=True,
            comment='Reference to the agent execution that generated this recommendation'
        ),
        # Core recommendation fields
        sa.Column(
            'strategy_id',
            sa.String(255),
            nullable=False,
            comment='Unique identifier for the optimization strategy (e.g., "rightsizing-ec2", "unused-ebs")'
        ),
        sa.Column(
            'strategy_name',
            sa.String(500),
            nullable=False,
            comment='Human-readable name of the optimization strategy'
        ),
        sa.Column(
            'description',
            sa.Text(),
            nullable=False,
            comment='Detailed description of the optimization recommendation'
        ),
        sa.Column(
            'service',
            sa.String(100),
            nullable=False,
            comment='AWS service this recommendation applies to (e.g., "EC2", "RDS", "S3")'
        ),
        # Savings estimation
        sa.Column(
            'estimated_savings_min_percent',
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default=sa.text('0.00'),
            comment='Minimum estimated percentage savings (0.00-100.00)'
        ),
        sa.Column(
            'estimated_savings_max_percent',
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default=sa.text('0.00'),
            comment='Maximum estimated percentage savings (0.00-100.00)'
        ),
        sa.Column(
            'estimated_annual_savings_usd',
            sa.Numeric(precision=15, scale=2),
            nullable=True,
            comment='Estimated annual savings in USD'
        ),
        # Implementation details
        sa.Column(
            'recommendation_steps',
            JSONB,
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
            comment='JSON array of step-by-step implementation instructions'
        ),
        sa.Column(
            'implementation_effort_hours',
            sa.Integer(),
            nullable=False,
            server_default=sa.text('0'),
            comment='Estimated hours required to implement the recommendation'
        ),
        sa.Column(
            'implementation_difficulty',
            sa.Text(),
            nullable=False,
            comment='Difficulty level of implementing the recommendation'
        ),
        # Risk and confidence
        sa.Column(
            'confidence_score',
            sa.Numeric(precision=3, scale=2),
            nullable=False,
            server_default=sa.text('0.00'),
            comment='Confidence score for the recommendation (0.00-1.00)'
        ),
        sa.Column(
            'risk_level',
            sa.String(50),
            nullable=True,
            comment='Risk level associated with implementing the recommendation (e.g., "low", "medium", "high")'
        ),
        sa.Column(
            'validation_count',
            sa.Integer(),
            nullable=False,
            server_default=sa.text('0'),
            comment='Number of times this recommendation has been validated by agents or users'
        ),
        # Status and lifecycle
        sa.Column(
            'status',
            sa.Text(),
            nullable=False,
            comment='Current status of the recommendation'
        ),
        sa.Column(
            'priority_score',
            sa.Integer(),
            nullable=True,
            comment='Calculated priority score (1-100) based on savings, effort, and confidence'
        ),
        # Metadata and categorization
        sa.Column(
            'metadata',
            postgresql.JSONB(),
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
            comment='Additional metadata as JSONB for flexible storage'
        ),
        sa.Column(
            'tags',
            postgresql.JSONB(),
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
            comment='Array of tags for categorization (e.g., ["compute", "cost", "performance"])'
        ),
        # Timestamp tracking
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when the recommendation was created'
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when the recommendation was last updated'
        ),
        sa.Column(
            'expires_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='Optional expiration timestamp for time-sensitive recommendations'
        ),
        # Check constraints
        sa.CheckConstraint(
            'estimated_savings_min_percent >= 0.00 AND estimated_savings_min_percent <= 100.00',
            name='ck_savings_min_percent_range'
        ),
        sa.CheckConstraint(
            'estimated_savings_max_percent >= 0.00 AND estimated_savings_max_percent <= 100.00',
            name='ck_savings_max_percent_range'
        ),
        sa.CheckConstraint(
            'estimated_savings_max_percent >= estimated_savings_min_percent',
            name='ck_savings_max_gte_min'
        ),
        sa.CheckConstraint(
            'implementation_effort_hours >= 0',
            name='ck_effort_positive'
        ),
        sa.CheckConstraint(
            'confidence_score >= 0.00 AND confidence_score <= 1.00',
            name='ck_confidence_range'
        ),
        sa.CheckConstraint(
            'validation_count >= 0',
            name='ck_validation_count_positive'
        ),
        sa.CheckConstraint(
            'priority_score IS NULL OR (priority_score >= 1 AND priority_score <= 100)',
            name='ck_priority_score_range'
        ),
        comment='Table for storing FinOps optimization recommendations with savings estimates and implementation details'
    )
    
    # Alter columns to use ENUM types (after table creation to avoid type recreation issues)
    # First convert to ENUM type, then set defaults
    op.execute("ALTER TABLE optimization_recommendations ALTER COLUMN implementation_difficulty TYPE implementation_difficulty USING implementation_difficulty::implementation_difficulty")
    op.execute("ALTER TABLE optimization_recommendations ALTER COLUMN implementation_difficulty SET DEFAULT 'medium'::implementation_difficulty")
    
    op.execute("ALTER TABLE optimization_recommendations ALTER COLUMN status TYPE recommendation_status USING status::recommendation_status")
    op.execute("ALTER TABLE optimization_recommendations ALTER COLUMN status SET DEFAULT 'pending'::recommendation_status")
    
    # Create indexes for performance optimization
    
    # Index on thread_id for conversation-linked recommendations
    op.create_index(
        'idx_optimization_recommendations_thread_id',
        'optimization_recommendations',
        ['thread_id']
    )
    
    # Index on agent_execution_id for tracking recommendation sources
    op.create_index(
        'idx_optimization_recommendations_agent_exec',
        'optimization_recommendations',
        ['agent_execution_id']
    )
    
    # Index on service for service-specific recommendations
    op.create_index(
        'idx_optimization_recommendations_service',
        'optimization_recommendations',
        ['service']
    )
    
    # Index on strategy_id for strategy-specific queries
    op.create_index(
        'idx_optimization_recommendations_strategy_id',
        'optimization_recommendations',
        ['strategy_id']
    )
    
    # Composite index for service + strategy
    op.create_index(
        'idx_optimization_recommendations_service_strategy',
        'optimization_recommendations',
        ['service', 'strategy_id']
    )
    
    # Index on status for filtering active recommendations
    op.create_index(
        'idx_optimization_recommendations_status',
        'optimization_recommendations',
        ['status']
    )
    
    # Composite index for active recommendations by service
    op.create_index(
        'idx_optimization_recommendations_status_service',
        'optimization_recommendations',
        ['status', 'service']
    )
    
    # Index on implementation_difficulty for filtering by complexity
    op.create_index(
        'idx_optimization_recommendations_difficulty',
        'optimization_recommendations',
        ['implementation_difficulty']
    )
    
    # Index on confidence_score for quality filtering
    op.create_index(
        'idx_optimization_recommendations_confidence',
        'optimization_recommendations',
        ['confidence_score']
    )
    
    # Index on priority_score for prioritization
    op.create_index(
        'idx_optimization_recommendations_priority',
        'optimization_recommendations',
        ['priority_score']
    )
    
    # Composite index for high-value recommendations (high savings, low effort)
    op.create_index(
        'idx_optimization_recommendations_value',
        'optimization_recommendations',
        ['estimated_savings_max_percent', 'implementation_effort_hours']
    )
    
    # Index on created_at for chronological queries
    op.create_index(
        'idx_optimization_recommendations_created_at',
        'optimization_recommendations',
        ['created_at']
    )
    
    # Index on updated_at for tracking recent updates
    op.create_index(
        'idx_optimization_recommendations_updated_at',
        'optimization_recommendations',
        ['updated_at']
    )
    
    # Index on expires_at for expiring recommendations
    op.create_index(
        'idx_optimization_recommendations_expires_at',
        'optimization_recommendations',
        ['expires_at']
    )
    
    # GIN index on metadata JSONB
    op.create_index(
        'idx_optimization_recommendations_metadata_gin',
        'optimization_recommendations',
        ['metadata'],
        postgresql_using='gin'
    )
    
    # GIN index on tags JSONB
    op.create_index(
        'idx_optimization_recommendations_tags_gin',
        'optimization_recommendations',
        ['tags'],
        postgresql_using='gin'
    )
    
    # GIN index on recommendation_steps JSONB
    op.create_index(
        'idx_optimization_recommendations_steps_gin',
        'optimization_recommendations',
        ['recommendation_steps'],
        postgresql_using='gin'
    )
    
    # Full-text search index on description
    op.execute("""
        CREATE INDEX idx_optimization_recommendations_description_fts 
        ON optimization_recommendations 
        USING gin(to_tsvector('english', description));
    """)
    
    # Full-text search index on strategy_name
    op.execute("""
        CREATE INDEX idx_optimization_recommendations_strategy_name_fts 
        ON optimization_recommendations 
        USING gin(to_tsvector('english', strategy_name));
    """)
    
    # Partial index for pending/actionable, high-priority recommendations
    op.execute("""
        CREATE INDEX idx_optimization_recommendations_active_priority 
        ON optimization_recommendations (priority_score DESC, estimated_savings_max_percent DESC) 
        WHERE status IN ('pending', 'in_progress') AND priority_score IS NOT NULL;
    """)
    
    # Partial index for expiring recommendations
    op.execute("""
        CREATE INDEX idx_optimization_recommendations_expiring 
        ON optimization_recommendations (expires_at) 
        WHERE status IN ('pending', 'in_progress') AND expires_at IS NOT NULL;
    """)
    
    # Create trigger to automatically update updated_at timestamp
    op.execute("""
        CREATE OR REPLACE FUNCTION update_optimization_recommendations_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    
    op.execute("""
        CREATE TRIGGER trigger_optimization_recommendations_updated_at
        BEFORE UPDATE ON optimization_recommendations
        FOR EACH ROW
        EXECUTE FUNCTION update_optimization_recommendations_updated_at();
    """)
    
    # Create function to calculate priority score automatically
    op.execute("""
        CREATE OR REPLACE FUNCTION calculate_recommendation_priority()
        RETURNS TRIGGER AS $$
        DECLARE
            savings_factor NUMERIC;
            effort_factor NUMERIC;
            confidence_factor NUMERIC;
            calculated_priority INTEGER;
        BEGIN
            -- Normalize savings (max 40 points)
            savings_factor := LEAST(NEW.estimated_savings_max_percent * 0.4, 40);
            
            -- Normalize effort (max 30 points, inverse - lower effort = higher score)
            effort_factor := GREATEST(30 - (NEW.implementation_effort_hours * 0.5), 0);
            effort_factor := LEAST(effort_factor, 30);
            
            -- Normalize confidence (max 30 points)
            confidence_factor := NEW.confidence_score * 30;
            
            -- Calculate total priority (1-100)
            calculated_priority := GREATEST(LEAST((savings_factor + effort_factor + confidence_factor)::INTEGER, 100), 1);
            
            NEW.priority_score := calculated_priority;
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    
    op.execute("""
        CREATE TRIGGER trigger_calculate_priority
        BEFORE INSERT OR UPDATE OF estimated_savings_max_percent, implementation_effort_hours, confidence_score
        ON optimization_recommendations
        FOR EACH ROW
        EXECUTE FUNCTION calculate_recommendation_priority();
    """)


def downgrade() -> None:
    """
    Drops the optimization_recommendations table and related objects.
    """
    # Drop triggers and functions
    op.execute("DROP TRIGGER IF EXISTS trigger_calculate_priority ON optimization_recommendations")
    op.execute("DROP TRIGGER IF EXISTS trigger_optimization_recommendations_updated_at ON optimization_recommendations")
    op.execute("DROP FUNCTION IF EXISTS calculate_recommendation_priority()")
    op.execute("DROP FUNCTION IF EXISTS update_optimization_recommendations_updated_at()")
    
    # Drop indexes
    op.execute("DROP INDEX IF EXISTS idx_optimization_recommendations_expiring")
    op.execute("DROP INDEX IF EXISTS idx_optimization_recommendations_active_priority")
    op.execute("DROP INDEX IF EXISTS idx_optimization_recommendations_strategy_name_fts")
    op.execute("DROP INDEX IF EXISTS idx_optimization_recommendations_description_fts")
    op.drop_index('idx_optimization_recommendations_steps_gin', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_tags_gin', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_metadata_gin', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_expires_at', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_updated_at', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_created_at', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_value', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_priority', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_confidence', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_difficulty', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_status_service', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_status', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_service_strategy', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_strategy_id', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_service', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_agent_exec', table_name='optimization_recommendations')
    op.drop_index('idx_optimization_recommendations_thread_id', table_name='optimization_recommendations')
    
    # Drop table
    op.drop_table('optimization_recommendations')
    
    # Drop ENUM types
    op.execute("DROP TYPE IF EXISTS recommendation_status")
    op.execute("DROP TYPE IF EXISTS implementation_difficulty")
