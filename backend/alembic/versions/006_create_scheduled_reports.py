"""Create scheduled reports tables

Revision ID: 006b
Revises: 006
Create Date: 2025-11-20 13:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

# revision identifiers, used by Alembic.
revision = '006b'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create report_frequency enum if not exists
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE report_frequency AS ENUM (
                'DAILY',
                'WEEKLY',
                'MONTHLY',
                'QUARTERLY',
                'CUSTOM_CRON'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create report_format enum if not exists
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE report_format AS ENUM (
                'PDF',
                'CSV',
                'EXCEL',
                'JSON',
                'HTML'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create delivery_method enum if not exists
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE delivery_method AS ENUM (
                'EMAIL',
                'WEBHOOK',
                'S3',
                'SLACK'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create scheduled_reports table
    op.create_table(
        'scheduled_reports',
        sa.Column('id', sa.UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        
        # Report configuration
        sa.Column('report_type', sa.String(100), nullable=False),  # 'cost_breakdown', 'trend_analysis', etc.
        sa.Column('report_template', sa.Text),  # Jinja2 template
        sa.Column('query_params', JSONB, nullable=False),  # Services, regions, accounts, time ranges
        
        # Scheduling
        sa.Column(
            'frequency',
            sa.Enum(
                'DAILY', 'WEEKLY', 'MONTHLY', 'QUARTERLY', 'CUSTOM_CRON',
                name='report_frequency',
                create_type=False  # prevent SQLAlchemy from auto-creating type if it already exists
            ),
            nullable=False
        ),
        sa.Column('cron_expression', sa.String(100)),  # For CUSTOM_CRON frequency
        sa.Column('timezone', sa.String(50), server_default='UTC'),
        sa.Column('next_run_at', sa.DateTime(timezone=True)),
        sa.Column('last_run_at', sa.DateTime(timezone=True)),
        
        # Delivery
        sa.Column(
            'format',
            sa.Enum('PDF', 'CSV', 'EXCEL', 'JSON', 'HTML', name='report_format', create_type=False),
            nullable=False
        ),
        sa.Column(
            'delivery_methods',
            ARRAY(sa.Enum('EMAIL', 'WEBHOOK', 'S3', 'SLACK', name='delivery_method', create_type=False)),
            nullable=False
        ),
        sa.Column('recipients', JSONB, nullable=False),  # {emails: [], webhooks: [], slack_channels: [], s3_paths: []}
        
        # Metadata
        sa.Column('tags', JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        
        # Constraints
        sa.CheckConstraint("frequency != 'CUSTOM_CRON' OR cron_expression IS NOT NULL", name='cron_required_for_custom')
    )
    
    # Create report_executions table
    op.create_table(
        'report_executions',
        sa.Column('id', sa.UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('scheduled_report_id', sa.UUID, sa.ForeignKey('scheduled_reports.id', ondelete='CASCADE'), nullable=False),
        
        # Execution details
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('status', sa.String(50), nullable=False),  # 'pending', 'running', 'completed', 'failed'
        sa.Column('error_message', sa.Text),
        
        # Results
        sa.Column('data_results', JSONB),  # Query results
        sa.Column('report_file_path', sa.String(500)),  # S3 path or local path
        sa.Column('file_size_bytes', sa.BigInteger),
        
        # Delivery tracking
        sa.Column('delivery_status', JSONB),  # {email: 'sent', webhook: 'failed', ...}
        sa.Column('delivery_attempts', sa.Integer, server_default='0'),
        
        # Performance metrics
        sa.Column('query_duration_ms', sa.Integer),
        sa.Column('generation_duration_ms', sa.Integer),
        sa.Column('total_duration_ms', sa.Integer),
        
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )
    
    # Indexes for scheduled_reports
    op.create_index('idx_scheduled_reports_active', 'scheduled_reports', ['is_active'])
    op.create_index('idx_scheduled_reports_next_run', 'scheduled_reports', ['next_run_at'])
    op.create_index('idx_scheduled_reports_created_by', 'scheduled_reports', ['created_by'])
    op.create_index('idx_scheduled_reports_frequency', 'scheduled_reports', ['frequency'])
    op.create_index('idx_scheduled_reports_tags', 'scheduled_reports', ['tags'], postgresql_using='gin')
    
    # Indexes for report_executions
    op.create_index('idx_report_executions_report_id', 'report_executions', ['scheduled_report_id'])
    op.create_index('idx_report_executions_status', 'report_executions', ['status'])
    op.create_index('idx_report_executions_started_at', 'report_executions', ['started_at'])
    op.create_index('idx_report_executions_completed_at', 'report_executions', ['completed_at'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_report_executions_completed_at')
    op.drop_index('idx_report_executions_started_at')
    op.drop_index('idx_report_executions_status')
    op.drop_index('idx_report_executions_report_id')
    op.drop_index('idx_scheduled_reports_tags')
    op.drop_index('idx_scheduled_reports_frequency')
    op.drop_index('idx_scheduled_reports_created_by')
    op.drop_index('idx_scheduled_reports_next_run')
    op.drop_index('idx_scheduled_reports_active')
    
    # Drop tables
    op.drop_table('report_executions')
    op.drop_table('scheduled_reports')
    
    # Drop enums (safe if exist)
    op.execute("DROP TYPE IF EXISTS delivery_method")
    op.execute("DROP TYPE IF EXISTS report_format")
    op.execute("DROP TYPE IF EXISTS report_frequency")
