"""Create organizations and multi-tenant support tables

Revision ID: 010
Revises: 009
Create Date: 2026-01-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY, UUID

# revision identifiers, used by Alembic.
revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create organizations table - core tenant table
    op.create_table(
        'organizations',
        sa.Column('id', UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False, unique=True),
        sa.Column('subscription_tier', sa.String(50), server_default='standard'),
        sa.Column('settings', JSONB, server_default='{}'),
        sa.Column('max_users', sa.Integer, server_default='50'),
        sa.Column('max_accounts', sa.Integer, server_default='100'),
        sa.Column('saved_view_default_expiration_days', sa.Integer, nullable=True),  # NULL = no expiration
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now())
    )

    # Create organization_members table - User-to-org mapping
    op.create_table(
        'organization_members',
        sa.Column('id', UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', UUID, sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(50), server_default='member'),  # 'owner', 'admin', 'member'
        sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('invited_by', UUID, sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),

        # Composite unique constraint
        sa.UniqueConstraint('organization_id', 'user_id', name='uq_org_user')
    )

    # Create saved_views table - User-configurable query scopes
    op.create_table(
        'saved_views',
        sa.Column('id', UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('organization_id', UUID, sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('created_by', UUID, sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('account_ids', ARRAY(UUID), nullable=False),  # Array of aws_accounts.id
        sa.Column('default_time_range', JSONB, nullable=True),
        sa.Column('filters', JSONB, server_default='{}'),
        sa.Column('is_default', sa.Boolean, server_default='false'),
        sa.Column('is_personal', sa.Boolean, server_default='false'),
        sa.Column('shared_with_users', ARRAY(UUID), nullable=True),
        sa.Column('shared_with_roles', ARRAY(UUID), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),

        # Unique constraint for view name within organization
        sa.UniqueConstraint('organization_id', 'name', name='uq_org_view_name')
    )

    # Create user_active_views table - Track which view each user has selected
    op.create_table(
        'user_active_views',
        sa.Column('user_id', UUID, sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('saved_view_id', UUID, sa.ForeignKey('saved_views.id', ondelete='SET NULL'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now())
    )

    # Indexes for organizations
    op.create_index('idx_organizations_slug', 'organizations', ['slug'])
    op.create_index('idx_organizations_active', 'organizations', ['is_active'])
    op.create_index('idx_organizations_tier', 'organizations', ['subscription_tier'])

    # Indexes for organization_members
    op.create_index('idx_org_members_org', 'organization_members', ['organization_id'])
    op.create_index('idx_org_members_user', 'organization_members', ['user_id'])
    op.create_index('idx_org_members_role', 'organization_members', ['role'])

    # Indexes for saved_views
    op.create_index('idx_saved_views_org', 'saved_views', ['organization_id'])
    op.create_index('idx_saved_views_created_by', 'saved_views', ['created_by'])
    op.create_index('idx_saved_views_default', 'saved_views', ['organization_id', 'is_default'])
    op.create_index('idx_saved_views_expires', 'saved_views', ['expires_at'])
    op.create_index('idx_saved_views_active', 'saved_views', ['is_active'])
    op.create_index('idx_saved_views_personal', 'saved_views', ['created_by', 'is_personal'])

    # GIN index for JSONB columns
    op.create_index('idx_organizations_settings', 'organizations', ['settings'], postgresql_using='gin')
    op.create_index('idx_saved_views_filters', 'saved_views', ['filters'], postgresql_using='gin')


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_saved_views_filters')
    op.drop_index('idx_organizations_settings')
    op.drop_index('idx_saved_views_personal')
    op.drop_index('idx_saved_views_active')
    op.drop_index('idx_saved_views_expires')
    op.drop_index('idx_saved_views_default')
    op.drop_index('idx_saved_views_created_by')
    op.drop_index('idx_saved_views_org')
    op.drop_index('idx_org_members_role')
    op.drop_index('idx_org_members_user')
    op.drop_index('idx_org_members_org')
    op.drop_index('idx_organizations_tier')
    op.drop_index('idx_organizations_active')
    op.drop_index('idx_organizations_slug')

    # Drop tables
    op.drop_table('user_active_views')
    op.drop_table('saved_views')
    op.drop_table('organization_members')
    op.drop_table('organizations')
