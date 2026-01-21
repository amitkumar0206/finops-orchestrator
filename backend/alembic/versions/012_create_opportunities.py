"""Create opportunities table for AWS optimization signals

Revision ID: 012
Revises: 011
Create Date: 2026-01-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Creates the opportunities table for tracking AWS optimization opportunities.
    This table stores optimization signals from various AWS sources like:
    - Cost Explorer recommendations
    - Trusted Advisor checks
    - Compute Optimizer suggestions
    - Custom CUR-based analysis
    """

    # Create ENUM types for opportunity status and source
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE opportunity_status AS ENUM (
                'open',
                'accepted',
                'in_progress',
                'implemented',
                'dismissed',
                'expired',
                'invalid'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE opportunity_source AS ENUM (
                'cost_explorer',
                'trusted_advisor',
                'compute_optimizer',
                'cur_analysis',
                'custom',
                'manual'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE opportunity_category AS ENUM (
                'rightsizing',
                'idle_resources',
                'reserved_instances',
                'savings_plans',
                'storage_optimization',
                'data_transfer',
                'licensing',
                'architecture',
                'scheduling',
                'spot_instances',
                'other'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Create the opportunities table
    op.create_table(
        'opportunities',
        # Primary key
        sa.Column(
            'id',
            UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text('gen_random_uuid()'),
            primary_key=True,
            comment='Primary key UUID for the opportunity'
        ),

        # Organization/tenant scoping
        sa.Column(
            'organization_id',
            UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=True,
            comment='Organization this opportunity belongs to (multi-tenant support)'
        ),
        sa.Column(
            'account_id',
            sa.String(20),
            nullable=False,
            comment='AWS account ID where the opportunity was identified'
        ),

        # Core opportunity fields
        sa.Column(
            'title',
            sa.String(500),
            nullable=False,
            comment='Human-readable title summarizing the opportunity'
        ),
        sa.Column(
            'description',
            sa.Text(),
            nullable=False,
            comment='Detailed description of the optimization opportunity'
        ),
        sa.Column(
            'category',
            sa.Text(),
            nullable=False,
            comment='Category of optimization (rightsizing, idle_resources, etc.)'
        ),
        sa.Column(
            'source',
            sa.Text(),
            nullable=False,
            comment='Source of the opportunity signal'
        ),
        sa.Column(
            'source_id',
            sa.String(255),
            nullable=True,
            comment='External identifier from the source system (e.g., Trusted Advisor check ID)'
        ),

        # Affected resources
        sa.Column(
            'service',
            sa.String(100),
            nullable=False,
            comment='AWS service affected (EC2, RDS, S3, etc.)'
        ),
        sa.Column(
            'resource_id',
            sa.String(512),
            nullable=True,
            comment='AWS resource ID (ARN or identifier)'
        ),
        sa.Column(
            'resource_name',
            sa.String(255),
            nullable=True,
            comment='Human-readable resource name or tag'
        ),
        sa.Column(
            'resource_type',
            sa.String(100),
            nullable=True,
            comment='Resource type (e.g., m5.xlarge, db.r5.large)'
        ),
        sa.Column(
            'region',
            sa.String(50),
            nullable=True,
            comment='AWS region where the resource is located'
        ),
        sa.Column(
            'affected_resources',
            JSONB,
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
            comment='Array of affected resource details for multi-resource opportunities'
        ),

        # Savings estimation
        sa.Column(
            'estimated_monthly_savings',
            sa.Numeric(precision=15, scale=2),
            nullable=True,
            comment='Estimated monthly savings in USD'
        ),
        sa.Column(
            'estimated_annual_savings',
            sa.Numeric(precision=15, scale=2),
            nullable=True,
            comment='Estimated annual savings in USD'
        ),
        sa.Column(
            'savings_percentage',
            sa.Numeric(precision=5, scale=2),
            nullable=True,
            comment='Percentage savings relative to current cost'
        ),
        sa.Column(
            'current_monthly_cost',
            sa.Numeric(precision=15, scale=2),
            nullable=True,
            comment='Current monthly cost of the resource(s)'
        ),
        sa.Column(
            'projected_monthly_cost',
            sa.Numeric(precision=15, scale=2),
            nullable=True,
            comment='Projected monthly cost after optimization'
        ),
        sa.Column(
            'savings_currency',
            sa.String(3),
            nullable=False,
            server_default='USD',
            comment='Currency for savings amounts'
        ),

        # Implementation details
        sa.Column(
            'effort_level',
            sa.String(20),
            nullable=True,
            comment='Effort level: low, medium, high'
        ),
        sa.Column(
            'risk_level',
            sa.String(20),
            nullable=True,
            comment='Risk level: low, medium, high'
        ),
        sa.Column(
            'implementation_steps',
            JSONB,
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
            comment='Array of step-by-step implementation instructions'
        ),
        sa.Column(
            'prerequisites',
            JSONB,
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
            comment='Array of prerequisites before implementation'
        ),

        # Evidence and validation
        sa.Column(
            'evidence',
            JSONB,
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
            comment='Evidence data including API traces, CUR validation SQL, metrics'
        ),
        sa.Column(
            'api_trace',
            JSONB,
            nullable=True,
            comment='API call trace that identified this opportunity'
        ),
        sa.Column(
            'cur_validation_sql',
            sa.Text(),
            nullable=True,
            comment='SQL query to validate savings from CUR data'
        ),
        sa.Column(
            'deep_link',
            sa.String(2048),
            nullable=True,
            comment='Deep link to AWS console for the resource'
        ),
        sa.Column(
            'confidence_score',
            sa.Numeric(precision=3, scale=2),
            nullable=True,
            comment='Confidence score for the recommendation (0.00-1.00)'
        ),

        # Status tracking
        sa.Column(
            'status',
            sa.Text(),
            nullable=False,
            comment='Current status of the opportunity'
        ),
        sa.Column(
            'status_reason',
            sa.Text(),
            nullable=True,
            comment='Reason for status change (e.g., dismissal reason)'
        ),
        sa.Column(
            'status_changed_by',
            sa.String(255),
            nullable=True,
            comment='User who changed the status'
        ),
        sa.Column(
            'status_changed_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='Timestamp when status was last changed'
        ),

        # Priority and scoring
        sa.Column(
            'priority_score',
            sa.Integer(),
            nullable=True,
            comment='Calculated priority score (1-100) based on savings, effort, and confidence'
        ),
        sa.Column(
            'tags',
            JSONB,
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
            comment='Array of tags for categorization and filtering'
        ),

        # Additional metadata
        sa.Column(
            'metadata',
            JSONB,
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
            comment='Additional metadata as JSONB for flexible storage'
        ),
        sa.Column(
            'raw_signal',
            JSONB,
            nullable=True,
            comment='Raw signal data from the source system'
        ),

        # Timestamps
        sa.Column(
            'first_detected_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='When the opportunity was first detected'
        ),
        sa.Column(
            'last_seen_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='When the opportunity was last seen/validated'
        ),
        sa.Column(
            'expires_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='When the opportunity expires (for time-sensitive recommendations)'
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Record creation timestamp'
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Record update timestamp'
        ),

        # Check constraints
        sa.CheckConstraint(
            'estimated_monthly_savings IS NULL OR estimated_monthly_savings >= 0',
            name='ck_opportunities_savings_positive'
        ),
        sa.CheckConstraint(
            'confidence_score IS NULL OR (confidence_score >= 0.00 AND confidence_score <= 1.00)',
            name='ck_opportunities_confidence_range'
        ),
        sa.CheckConstraint(
            'priority_score IS NULL OR (priority_score >= 1 AND priority_score <= 100)',
            name='ck_opportunities_priority_range'
        ),
        sa.CheckConstraint(
            'savings_percentage IS NULL OR (savings_percentage >= 0.00 AND savings_percentage <= 100.00)',
            name='ck_opportunities_savings_pct_range'
        ),

        comment='Stores AWS optimization opportunities from various signal sources'
    )

    # Convert ENUM columns after table creation
    op.execute("ALTER TABLE opportunities ALTER COLUMN category TYPE opportunity_category USING category::opportunity_category")
    op.execute("ALTER TABLE opportunities ALTER COLUMN category SET DEFAULT 'other'::opportunity_category")

    op.execute("ALTER TABLE opportunities ALTER COLUMN source TYPE opportunity_source USING source::opportunity_source")
    op.execute("ALTER TABLE opportunities ALTER COLUMN source SET DEFAULT 'custom'::opportunity_source")

    op.execute("ALTER TABLE opportunities ALTER COLUMN status TYPE opportunity_status USING status::opportunity_status")
    op.execute("ALTER TABLE opportunities ALTER COLUMN status SET DEFAULT 'open'::opportunity_status")

    # Create indexes for common query patterns

    # Organization scoping
    op.create_index(
        'idx_opportunities_organization_id',
        'opportunities',
        ['organization_id']
    )

    # Account filtering
    op.create_index(
        'idx_opportunities_account_id',
        'opportunities',
        ['account_id']
    )

    # Status filtering (most common filter)
    op.create_index(
        'idx_opportunities_status',
        'opportunities',
        ['status']
    )

    # Service filtering
    op.create_index(
        'idx_opportunities_service',
        'opportunities',
        ['service']
    )

    # Category filtering
    op.create_index(
        'idx_opportunities_category',
        'opportunities',
        ['category']
    )

    # Source filtering
    op.create_index(
        'idx_opportunities_source',
        'opportunities',
        ['source']
    )

    # Source ID for deduplication
    op.create_index(
        'idx_opportunities_source_id',
        'opportunities',
        ['source', 'source_id'],
        unique=True,
        postgresql_where=sa.text("source_id IS NOT NULL")
    )

    # Resource lookup
    op.create_index(
        'idx_opportunities_resource_id',
        'opportunities',
        ['resource_id']
    )

    # Region filtering
    op.create_index(
        'idx_opportunities_region',
        'opportunities',
        ['region']
    )

    # Priority ordering
    op.create_index(
        'idx_opportunities_priority',
        'opportunities',
        ['priority_score'],
        postgresql_ops={'priority_score': 'DESC NULLS LAST'}
    )

    # Savings ordering
    op.create_index(
        'idx_opportunities_savings',
        'opportunities',
        ['estimated_monthly_savings'],
        postgresql_ops={'estimated_monthly_savings': 'DESC NULLS LAST'}
    )

    # Date filtering
    op.create_index(
        'idx_opportunities_first_detected',
        'opportunities',
        ['first_detected_at']
    )

    op.create_index(
        'idx_opportunities_last_seen',
        'opportunities',
        ['last_seen_at']
    )

    op.create_index(
        'idx_opportunities_expires_at',
        'opportunities',
        ['expires_at']
    )

    # Composite index for common list view query
    op.create_index(
        'idx_opportunities_list_query',
        'opportunities',
        ['organization_id', 'status', 'priority_score']
    )

    # Composite index for open opportunities by savings
    op.execute("""
        CREATE INDEX idx_opportunities_open_by_savings
        ON opportunities (estimated_monthly_savings DESC NULLS LAST)
        WHERE status = 'open'::opportunity_status;
    """)

    # Composite index for account + status
    op.create_index(
        'idx_opportunities_account_status',
        'opportunities',
        ['account_id', 'status']
    )

    # GIN indexes for JSONB columns
    op.create_index(
        'idx_opportunities_tags_gin',
        'opportunities',
        ['tags'],
        postgresql_using='gin'
    )

    op.create_index(
        'idx_opportunities_metadata_gin',
        'opportunities',
        ['metadata'],
        postgresql_using='gin'
    )

    op.create_index(
        'idx_opportunities_affected_resources_gin',
        'opportunities',
        ['affected_resources'],
        postgresql_using='gin'
    )

    # Full-text search on title and description
    op.execute("""
        CREATE INDEX idx_opportunities_title_fts
        ON opportunities
        USING gin(to_tsvector('english', title));
    """)

    op.execute("""
        CREATE INDEX idx_opportunities_description_fts
        ON opportunities
        USING gin(to_tsvector('english', description));
    """)

    # Create trigger for updated_at
    op.execute("""
        CREATE OR REPLACE FUNCTION update_opportunities_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    op.execute("""
        CREATE TRIGGER trigger_opportunities_updated_at
        BEFORE UPDATE ON opportunities
        FOR EACH ROW
        EXECUTE FUNCTION update_opportunities_updated_at();
    """)

    # Create trigger for automatic priority score calculation
    op.execute("""
        CREATE OR REPLACE FUNCTION calculate_opportunity_priority()
        RETURNS TRIGGER AS $$
        DECLARE
            savings_factor NUMERIC;
            effort_factor NUMERIC;
            confidence_factor NUMERIC;
            calculated_priority INTEGER;
        BEGIN
            -- Normalize savings (max 50 points based on monthly savings)
            -- $100+ savings = 50 points, scaling down
            IF NEW.estimated_monthly_savings IS NOT NULL AND NEW.estimated_monthly_savings > 0 THEN
                savings_factor := LEAST(NEW.estimated_monthly_savings / 2, 50);
            ELSE
                savings_factor := 0;
            END IF;

            -- Effort factor (max 25 points, inverse - lower effort = higher score)
            CASE NEW.effort_level
                WHEN 'low' THEN effort_factor := 25;
                WHEN 'medium' THEN effort_factor := 15;
                WHEN 'high' THEN effort_factor := 5;
                ELSE effort_factor := 10;
            END CASE;

            -- Confidence factor (max 25 points)
            IF NEW.confidence_score IS NOT NULL THEN
                confidence_factor := NEW.confidence_score * 25;
            ELSE
                confidence_factor := 12.5; -- Default to medium confidence
            END IF;

            -- Calculate total priority (1-100)
            calculated_priority := GREATEST(LEAST((savings_factor + effort_factor + confidence_factor)::INTEGER, 100), 1);

            NEW.priority_score := calculated_priority;
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    op.execute("""
        CREATE TRIGGER trigger_calculate_opportunity_priority
        BEFORE INSERT OR UPDATE OF estimated_monthly_savings, effort_level, confidence_score
        ON opportunities
        FOR EACH ROW
        EXECUTE FUNCTION calculate_opportunity_priority();
    """)

    # Create trigger for status change tracking
    op.execute("""
        CREATE OR REPLACE FUNCTION track_opportunity_status_change()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.status IS DISTINCT FROM NEW.status THEN
                NEW.status_changed_at = CURRENT_TIMESTAMP;
            END IF;
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    op.execute("""
        CREATE TRIGGER trigger_track_status_change
        BEFORE UPDATE ON opportunities
        FOR EACH ROW
        EXECUTE FUNCTION track_opportunity_status_change();
    """)


def downgrade() -> None:
    """
    Drops the opportunities table and related objects.
    """
    # Drop triggers and functions
    op.execute("DROP TRIGGER IF EXISTS trigger_track_status_change ON opportunities")
    op.execute("DROP TRIGGER IF EXISTS trigger_calculate_opportunity_priority ON opportunities")
    op.execute("DROP TRIGGER IF EXISTS trigger_opportunities_updated_at ON opportunities")

    op.execute("DROP FUNCTION IF EXISTS track_opportunity_status_change()")
    op.execute("DROP FUNCTION IF EXISTS calculate_opportunity_priority()")
    op.execute("DROP FUNCTION IF EXISTS update_opportunities_updated_at()")

    # Drop indexes
    op.execute("DROP INDEX IF EXISTS idx_opportunities_description_fts")
    op.execute("DROP INDEX IF EXISTS idx_opportunities_title_fts")
    op.execute("DROP INDEX IF EXISTS idx_opportunities_affected_resources_gin")
    op.execute("DROP INDEX IF EXISTS idx_opportunities_metadata_gin")
    op.execute("DROP INDEX IF EXISTS idx_opportunities_tags_gin")
    op.execute("DROP INDEX IF EXISTS idx_opportunities_account_status")
    op.execute("DROP INDEX IF EXISTS idx_opportunities_open_by_savings")
    op.drop_index('idx_opportunities_list_query', table_name='opportunities')
    op.drop_index('idx_opportunities_expires_at', table_name='opportunities')
    op.drop_index('idx_opportunities_last_seen', table_name='opportunities')
    op.drop_index('idx_opportunities_first_detected', table_name='opportunities')
    op.drop_index('idx_opportunities_savings', table_name='opportunities')
    op.drop_index('idx_opportunities_priority', table_name='opportunities')
    op.drop_index('idx_opportunities_region', table_name='opportunities')
    op.drop_index('idx_opportunities_resource_id', table_name='opportunities')
    op.drop_index('idx_opportunities_source_id', table_name='opportunities')
    op.drop_index('idx_opportunities_source', table_name='opportunities')
    op.drop_index('idx_opportunities_category', table_name='opportunities')
    op.drop_index('idx_opportunities_service', table_name='opportunities')
    op.drop_index('idx_opportunities_status', table_name='opportunities')
    op.drop_index('idx_opportunities_account_id', table_name='opportunities')
    op.drop_index('idx_opportunities_organization_id', table_name='opportunities')

    # Drop table
    op.drop_table('opportunities')

    # Drop ENUM types
    op.execute("DROP TYPE IF EXISTS opportunity_category")
    op.execute("DROP TYPE IF EXISTS opportunity_source")
    op.execute("DROP TYPE IF EXISTS opportunity_status")
