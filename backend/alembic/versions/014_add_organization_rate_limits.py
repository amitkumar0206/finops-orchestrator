"""Add organization rate limits for per-user fairness

Revision ID: 014
Revises: 013
Create Date: 2026-02-08 16:00:00.000000

This migration adds support for configurable per-user rate limits
within organizations to prevent resource hogging.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Create organization_rate_limits table for per-user rate limit configuration.

    Supports:
    - Per-organization customization (override defaults)
    - Per-role limits (owner, admin, member)
    - Per-endpoint limits (athena_export, ingest, etc.)
    """
    op.create_table(
        'organization_rate_limits',
        sa.Column('id', UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', UUID, sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('endpoint', sa.String(100), nullable=False),  # e.g., "athena_export", "ingest"
        sa.Column('user_role', sa.String(50), nullable=False),  # e.g., "owner", "admin", "member"
        sa.Column('requests_per_hour', sa.Integer, nullable=False),  # Per-user limit for this role
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('created_by', UUID, sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),

        # Unique constraint: One limit per (org, endpoint, role) combination
        sa.UniqueConstraint('organization_id', 'endpoint', 'user_role', name='uq_org_endpoint_role_limit')
    )

    # Indexes for efficient lookups
    op.create_index('idx_org_rate_limits_org', 'organization_rate_limits', ['organization_id'])
    op.create_index('idx_org_rate_limits_endpoint', 'organization_rate_limits', ['endpoint'])
    op.create_index('idx_org_rate_limits_lookup', 'organization_rate_limits',
                    ['organization_id', 'endpoint', 'user_role'])


def downgrade() -> None:
    """Remove organization rate limits table"""
    op.drop_index('idx_org_rate_limits_lookup', table_name='organization_rate_limits')
    op.drop_index('idx_org_rate_limits_endpoint', table_name='organization_rate_limits')
    op.drop_index('idx_org_rate_limits_org', table_name='organization_rate_limits')
    op.drop_table('organization_rate_limits')
