"""Create multi-account management tables

Revision ID: 007
Revises: 006
Create Date: 2025-11-20 13:35:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create account_status enum
    op.execute("""
        CREATE TYPE account_status AS ENUM (
            'ACTIVE',
            'INACTIVE',
            'PENDING',
            'ERROR'
        )
    """)
    
    # Create aws_accounts table
    op.create_table(
        'aws_accounts',
        sa.Column('id', sa.UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('account_id', sa.String(12), nullable=False, unique=True),
        sa.Column('account_name', sa.String(255), nullable=False),
        sa.Column('account_email', sa.String(255)),
        sa.Column('organization_id', sa.String(34)),  # AWS Organization ID
        sa.Column('organizational_unit', sa.String(255)),
        
        # Account categorization
        sa.Column('environment', sa.String(50)),  # 'production', 'staging', 'development'
        sa.Column('business_unit', sa.String(100)),
        sa.Column('cost_center', sa.String(100)),
        sa.Column('tags', JSONB),
        
        # Access configuration
        sa.Column('role_arn', sa.String(500), nullable=False),  # Cross-account IAM role
        sa.Column('external_id', sa.String(255)),  # For added security
        sa.Column('status', sa.Enum('ACTIVE', 'INACTIVE', 'PENDING', 'ERROR', name='account_status'), nullable=False, server_default='PENDING'),
        
        # Data source configuration
        sa.Column('cur_database', sa.String(255)),
        sa.Column('cur_table', sa.String(255)),
        sa.Column('s3_bucket', sa.String(255)),
        sa.Column('region', sa.String(50), server_default='us-east-1'),
        
        # Validation
        sa.Column('last_validated_at', sa.DateTime(timezone=True)),
        sa.Column('validation_error', sa.Text),
        sa.Column('last_data_sync_at', sa.DateTime(timezone=True)),
        
        # Metadata
        sa.Column('created_by', sa.String(255)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now())
    )
    
    # Create account_permissions table (who can access which accounts)
    op.create_table(
        'account_permissions',
        sa.Column('id', sa.UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('account_id', sa.UUID, sa.ForeignKey('aws_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_email', sa.String(255), nullable=False),
        sa.Column('access_level', sa.String(50), nullable=False),  # 'read', 'write', 'admin'
        sa.Column('granted_by', sa.String(255)),
        sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        
        # Composite unique constraint
        sa.UniqueConstraint('account_id', 'user_email', name='uq_account_user_permission')
    )
    
    # Indexes for aws_accounts
    op.create_index('idx_aws_accounts_account_id', 'aws_accounts', ['account_id'])
    op.create_index('idx_aws_accounts_status', 'aws_accounts', ['status'])
    op.create_index('idx_aws_accounts_business_unit', 'aws_accounts', ['business_unit'])
    op.create_index('idx_aws_accounts_environment', 'aws_accounts', ['environment'])
    op.create_index('idx_aws_accounts_tags', 'aws_accounts', ['tags'], postgresql_using='gin')
    
    # Indexes for account_permissions
    op.create_index('idx_account_permissions_account', 'account_permissions', ['account_id'])
    op.create_index('idx_account_permissions_user', 'account_permissions', ['user_email'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_account_permissions_user')
    op.drop_index('idx_account_permissions_account')
    op.drop_index('idx_aws_accounts_tags')
    op.drop_index('idx_aws_accounts_environment')
    op.drop_index('idx_aws_accounts_business_unit')
    op.drop_index('idx_aws_accounts_status')
    op.drop_index('idx_aws_accounts_account_id')
    
    # Drop tables
    op.drop_table('account_permissions')
    op.drop_table('aws_accounts')
    
    # Drop enum
    op.execute('DROP TYPE account_status')
