"""Create RBAC and audit logging tables

Revision ID: 008
Revises: 007
Create Date: 2025-11-20 13:40:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY, INET

# revision identifiers, used by Alembic.
revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create roles table
    op.create_table(
        'roles',
        sa.Column('id', sa.UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('description', sa.Text),
        sa.Column('is_system_role', sa.Boolean, server_default='false'),  # Cannot be deleted
        sa.Column('permissions', ARRAY(sa.String(100)), nullable=False),  # List of permission strings
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now())
    )
    
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('full_name', sa.String(255)),
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('is_admin', sa.Boolean, server_default='false'),
        sa.Column('last_login_at', sa.DateTime(timezone=True)),
        sa.Column('last_login_ip', INET),
        sa.Column('preferences', JSONB),  # UI preferences, default dashboards, etc.
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now())
    )
    
    # Create user_roles junction table
    op.create_table(
        'user_roles',
        sa.Column('id', sa.UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.UUID, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role_id', sa.UUID, sa.ForeignKey('roles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('granted_by', sa.UUID, sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        
        # Composite unique constraint
        sa.UniqueConstraint('user_id', 'role_id', name='uq_user_role')
    )
    
    # Create audit_logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.UUID, sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('user_email', sa.String(255)),  # Denormalized for deleted users
        
        # Action details
        sa.Column('action', sa.String(100), nullable=False),  # 'query_executed', 'report_created', etc.
        sa.Column('resource_type', sa.String(100)),  # 'scheduled_report', 'dashboard', etc.
        sa.Column('resource_id', sa.UUID),
        sa.Column('description', sa.Text),
        
        # Request context
        sa.Column('ip_address', INET),
        sa.Column('user_agent', sa.String(500)),
        sa.Column('request_id', sa.UUID),
        sa.Column('session_id', sa.String(255)),
        
        # Results
        sa.Column('status', sa.String(50), nullable=False),  # 'success', 'failure', 'denied'
        sa.Column('error_message', sa.Text),
        sa.Column('details', JSONB),  # Full action details
        
        # Metadata
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
    )
    
    # Indexes for roles
    op.create_index('idx_roles_name', 'roles', ['name'])
    op.create_index('idx_roles_system', 'roles', ['is_system_role'])
    
    # Indexes for users
    op.create_index('idx_users_email', 'users', ['email'])
    op.create_index('idx_users_active', 'users', ['is_active'])
    op.create_index('idx_users_admin', 'users', ['is_admin'])
    
    # Indexes for user_roles
    op.create_index('idx_user_roles_user', 'user_roles', ['user_id'])
    op.create_index('idx_user_roles_role', 'user_roles', ['role_id'])
    op.create_index('idx_user_roles_expires', 'user_roles', ['expires_at'])
    
    # Indexes for audit_logs
    op.create_index('idx_audit_logs_user', 'audit_logs', ['user_id'])
    op.create_index('idx_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('idx_audit_logs_resource', 'audit_logs', ['resource_type', 'resource_id'])
    op.create_index('idx_audit_logs_created_at', 'audit_logs', ['created_at'])
    op.create_index('idx_audit_logs_status', 'audit_logs', ['status'])
    op.create_index('idx_audit_logs_details', 'audit_logs', ['details'], postgresql_using='gin')
    
    # Insert default system roles
    op.execute("""
        INSERT INTO roles (name, description, is_system_role, permissions) VALUES
        ('admin', 'Full system administrator', true, ARRAY[
            'view_all_accounts',
            'manage_accounts',
            'view_all_dashboards',
            'create_dashboards',
            'edit_dashboards',
            'delete_dashboards',
            'view_reports',
            'create_reports',
            'edit_reports',
            'delete_reports',
            'manage_users',
            'manage_roles',
            'view_audit_logs',
            'execute_queries'
        ]),
        ('analyst', 'Cost analyst with read/write access', true, ARRAY[
            'view_assigned_accounts',
            'view_all_dashboards',
            'create_dashboards',
            'edit_own_dashboards',
            'view_reports',
            'create_reports',
            'edit_own_reports',
            'execute_queries'
        ]),
        ('viewer', 'Read-only access to cost data', true, ARRAY[
            'view_assigned_accounts',
            'view_all_dashboards',
            'view_reports',
            'execute_queries'
        ])
    """)


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_audit_logs_details')
    op.drop_index('idx_audit_logs_status')
    op.drop_index('idx_audit_logs_created_at')
    op.drop_index('idx_audit_logs_resource')
    op.drop_index('idx_audit_logs_action')
    op.drop_index('idx_audit_logs_user')
    op.drop_index('idx_user_roles_expires')
    op.drop_index('idx_user_roles_role')
    op.drop_index('idx_user_roles_user')
    op.drop_index('idx_users_admin')
    op.drop_index('idx_users_active')
    op.drop_index('idx_users_email')
    op.drop_index('idx_roles_system')
    op.drop_index('idx_roles_name')
    
    # Drop tables
    op.drop_table('audit_logs')
    op.drop_table('user_roles')
    op.drop_table('users')
    op.drop_table('roles')
