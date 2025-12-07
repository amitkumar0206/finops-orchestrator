"""Create custom dashboards and cost allocation tables

Revision ID: 009
Revises: 008
Create Date: 2025-11-20 13:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

# revision identifiers, used by Alembic.
revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create dashboard_templates table
    op.create_table(
        'dashboard_templates',
        sa.Column('id', sa.UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('created_by', sa.UUID, sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('is_public', sa.Boolean, server_default='false'),
        sa.Column('is_default', sa.Boolean, server_default='false'),
        
        # Layout configuration
        sa.Column('layout', JSONB, nullable=False),  # Grid layout config
        sa.Column('widgets', JSONB, nullable=False),  # Array of widget configurations
        # Widget structure: {id, type, position, size, config: {query_params, chart_type, filters}}
        
        # Sharing and permissions
        sa.Column('shared_with_users', ARRAY(sa.UUID)),
        sa.Column('shared_with_roles', ARRAY(sa.UUID)),
        
        # Metadata
        sa.Column('tags', JSONB),
        sa.Column('refresh_interval_seconds', sa.Integer, server_default='300'),  # Auto-refresh every 5 min
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now())
    )
    
    # Create cost_allocation_rules table
    op.create_table(
        'cost_allocation_rules',
        sa.Column('id', sa.UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('priority', sa.Integer, nullable=False, server_default='100'),  # Lower = higher priority
        sa.Column('is_active', sa.Boolean, server_default='true'),
        
        # Rule definition
        sa.Column('match_conditions', JSONB, nullable=False),  # {tags: {...}, services: [...], accounts: [...]}
        sa.Column('allocation_strategy', sa.String(50), nullable=False),  # 'proportional', 'even_split', 'tagged'
        sa.Column('allocation_targets', JSONB, nullable=False),  # {business_units: {...}, cost_centers: {...}}
        
        # Metadata
        sa.Column('created_by', sa.UUID, sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now())
    )
    
    # Create chargeback_reports table
    op.create_table(
        'chargeback_reports',
        sa.Column('id', sa.UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('period_start', sa.Date, nullable=False),
        sa.Column('period_end', sa.Date, nullable=False),
        sa.Column('period_type', sa.String(50), nullable=False),  # 'daily', 'weekly', 'monthly', 'quarterly'
        
        # Chargeback data
        sa.Column('allocations', JSONB, nullable=False),  # Full allocation breakdown by business unit/cost center
        sa.Column('total_cost', sa.Numeric(15, 2), nullable=False),
        sa.Column('unallocated_cost', sa.Numeric(15, 2)),
        
        # Status
        sa.Column('status', sa.String(50), nullable=False, server_default='draft'),  # 'draft', 'published', 'finalized'
        sa.Column('published_at', sa.DateTime(timezone=True)),
        sa.Column('published_by', sa.UUID, sa.ForeignKey('users.id', ondelete='SET NULL')),
        
        # Metadata
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        
        # Unique constraint on period
        sa.UniqueConstraint('period_start', 'period_end', 'period_type', name='uq_chargeback_period')
    )
    
    # Create ticketing_integrations table
    op.create_table(
        'ticketing_integrations',
        sa.Column('id', sa.UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False),  # 'jira', 'servicenow', 'github', 'linear'
        sa.Column('is_active', sa.Boolean, server_default='true'),
        
        # Configuration
        sa.Column('base_url', sa.String(500), nullable=False),
        sa.Column('credentials', JSONB, nullable=False),  # Encrypted API keys, OAuth tokens
        sa.Column('project_key', sa.String(100)),  # Jira project key, ServiceNow table, etc.
        sa.Column('default_labels', ARRAY(sa.String(100))),
        sa.Column('field_mappings', JSONB),  # Custom field mappings
        
        # Automation rules
        sa.Column('auto_create_on', JSONB),  # {anomaly_detected: true, budget_exceeded: true, ...}
        sa.Column('template', sa.Text),  # Ticket description template
        
        # Metadata
        sa.Column('created_by', sa.UUID, sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('last_sync_at', sa.DateTime(timezone=True)),
        sa.Column('sync_status', sa.String(50)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now())
    )
    
    # Create tickets table (tracks created tickets)
    op.create_table(
        'tickets',
        sa.Column('id', sa.UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('integration_id', sa.UUID, sa.ForeignKey('ticketing_integrations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('external_id', sa.String(255), nullable=False),  # Ticket ID in external system
        sa.Column('external_url', sa.String(500)),
        
        # Trigger details
        sa.Column('trigger_type', sa.String(100), nullable=False),  # 'anomaly', 'budget_alert', 'manual'
        sa.Column('trigger_data', JSONB),  # Original event data
        
        # Status tracking
        sa.Column('status', sa.String(50)),  # Last known status from external system
        sa.Column('created_by', sa.UUID, sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        
        # Composite unique constraint
        sa.UniqueConstraint('integration_id', 'external_id', name='uq_ticket_external')
    )
    
    # Indexes for dashboard_templates
    op.create_index('idx_dashboard_templates_created_by', 'dashboard_templates', ['created_by'])
    op.create_index('idx_dashboard_templates_public', 'dashboard_templates', ['is_public'])
    op.create_index('idx_dashboard_templates_default', 'dashboard_templates', ['is_default'])
    op.create_index('idx_dashboard_templates_tags', 'dashboard_templates', ['tags'], postgresql_using='gin')
    
    # Indexes for cost_allocation_rules
    op.create_index('idx_cost_allocation_rules_active', 'cost_allocation_rules', ['is_active'])
    op.create_index('idx_cost_allocation_rules_priority', 'cost_allocation_rules', ['priority'])
    
    # Indexes for chargeback_reports
    op.create_index('idx_chargeback_reports_period', 'chargeback_reports', ['period_start', 'period_end'])
    op.create_index('idx_chargeback_reports_status', 'chargeback_reports', ['status'])
    op.create_index('idx_chargeback_reports_published', 'chargeback_reports', ['published_at'])
    
    # Indexes for ticketing_integrations
    op.create_index('idx_ticketing_integrations_provider', 'ticketing_integrations', ['provider'])
    op.create_index('idx_ticketing_integrations_active', 'ticketing_integrations', ['is_active'])
    
    # Indexes for tickets
    op.create_index('idx_tickets_integration', 'tickets', ['integration_id'])
    op.create_index('idx_tickets_external_id', 'tickets', ['external_id'])
    op.create_index('idx_tickets_trigger_type', 'tickets', ['trigger_type'])
    op.create_index('idx_tickets_created_at', 'tickets', ['created_at'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_tickets_created_at')
    op.drop_index('idx_tickets_trigger_type')
    op.drop_index('idx_tickets_external_id')
    op.drop_index('idx_tickets_integration')
    op.drop_index('idx_ticketing_integrations_active')
    op.drop_index('idx_ticketing_integrations_provider')
    op.drop_index('idx_chargeback_reports_published')
    op.drop_index('idx_chargeback_reports_status')
    op.drop_index('idx_chargeback_reports_period')
    op.drop_index('idx_cost_allocation_rules_priority')
    op.drop_index('idx_cost_allocation_rules_active')
    op.drop_index('idx_dashboard_templates_tags')
    op.drop_index('idx_dashboard_templates_default')
    op.drop_index('idx_dashboard_templates_public')
    op.drop_index('idx_dashboard_templates_created_by')
    
    # Drop tables
    op.drop_table('tickets')
    op.drop_table('ticketing_integrations')
    op.drop_table('chargeback_reports')
    op.drop_table('cost_allocation_rules')
    op.drop_table('dashboard_templates')
