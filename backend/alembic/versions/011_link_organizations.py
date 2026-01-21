"""Link organizations to existing tables and enhance audit logging

Revision ID: 011
Revises: 010
Create Date: 2026-01-21 10:05:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Link aws_accounts to organizations
    # First rename organization_id (AWS organization ID) to aws_organization_id
    op.alter_column(
        'aws_accounts',
        'organization_id',
        new_column_name='aws_organization_id'
    )

    # Add tenant_org_id column to link accounts to tenant organizations
    op.add_column(
        'aws_accounts',
        sa.Column('tenant_org_id', UUID, sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True)
    )
    op.create_index('idx_aws_accounts_tenant_org', 'aws_accounts', ['tenant_org_id'])

    # Add default organization to users
    op.add_column(
        'users',
        sa.Column('default_organization_id', UUID, sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True)
    )
    op.create_index('idx_users_default_org', 'users', ['default_organization_id'])

    # Enhance audit_logs with scope context
    op.add_column(
        'audit_logs',
        sa.Column('organization_id', UUID, sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True)
    )
    op.add_column(
        'audit_logs',
        sa.Column('saved_view_id', UUID, sa.ForeignKey('saved_views.id', ondelete='SET NULL'), nullable=True)
    )
    op.add_column(
        'audit_logs',
        sa.Column('scope_context', JSONB, nullable=True)
    )
    op.create_index('idx_audit_logs_org', 'audit_logs', ['organization_id'])
    op.create_index('idx_audit_logs_view', 'audit_logs', ['saved_view_id'])
    op.create_index('idx_audit_logs_scope', 'audit_logs', ['scope_context'], postgresql_using='gin')

    # Add organization and view to conversation_threads
    op.add_column(
        'conversation_threads',
        sa.Column('organization_id', UUID, sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True)
    )
    op.add_column(
        'conversation_threads',
        sa.Column('saved_view_id', UUID, sa.ForeignKey('saved_views.id', ondelete='SET NULL'), nullable=True)
    )
    op.create_index('idx_conversation_threads_org', 'conversation_threads', ['organization_id'])
    op.create_index('idx_conversation_threads_view', 'conversation_threads', ['saved_view_id'])


def downgrade() -> None:
    # Drop indexes from conversation_threads
    op.drop_index('idx_conversation_threads_view')
    op.drop_index('idx_conversation_threads_org')

    # Drop columns from conversation_threads
    op.drop_column('conversation_threads', 'saved_view_id')
    op.drop_column('conversation_threads', 'organization_id')

    # Drop indexes from audit_logs
    op.drop_index('idx_audit_logs_scope')
    op.drop_index('idx_audit_logs_view')
    op.drop_index('idx_audit_logs_org')

    # Drop columns from audit_logs
    op.drop_column('audit_logs', 'scope_context')
    op.drop_column('audit_logs', 'saved_view_id')
    op.drop_column('audit_logs', 'organization_id')

    # Drop from users
    op.drop_index('idx_users_default_org')
    op.drop_column('users', 'default_organization_id')

    # Drop from aws_accounts
    op.drop_index('idx_aws_accounts_tenant_org')
    op.drop_column('aws_accounts', 'tenant_org_id')

    # Rename aws_organization_id back to organization_id
    op.alter_column(
        'aws_accounts',
        'aws_organization_id',
        new_column_name='organization_id'
    )
