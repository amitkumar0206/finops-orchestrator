"""create conversation_threads table

Revision ID: 001
Revises: 
Create Date: 2025-11-12 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Creates the conversation_threads table for storing conversation thread metadata.
    
    This table serves as the parent table for all conversation-related data,
    tracking individual conversation threads with their metadata and activity status.
    """
    # Create conversation_threads table
    op.create_table(
        'conversation_threads',
        # Primary key - UUID for distributed system compatibility
        sa.Column(
            'thread_id',
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text('gen_random_uuid()'),
            comment='Primary key, auto-generated UUID for the conversation thread'
        ),
        # User identification
        sa.Column(
            'user_id',
            sa.String(255),
            nullable=False,
            comment='Identifier for the user who owns this conversation thread'
        ),
        # Thread title for display/search
        sa.Column(
            'title',
            sa.String(500),
            nullable=True,
            comment='Human-readable title for the conversation, auto-generated from first message or user-defined'
        ),
        # Timestamp tracking
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when the conversation thread was created'
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when the conversation thread was last updated'
        ),
        # Flexible metadata storage
        sa.Column(
            'metadata',
            JSONB,
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
            comment='Flexible JSONB field for storing thread metadata like tags, categories, user preferences, etc.'
        ),
        # Soft delete flag
        sa.Column(
            'is_active',
            sa.Boolean,
            nullable=False,
            server_default=sa.text('true'),
            comment='Flag indicating if the thread is active (true) or archived/deleted (false)'
        ),
        comment='Main table for storing conversation threads with metadata and activity tracking'
    )
    
    # Create indexes for performance optimization
    
    # Index on user_id for fast user-specific queries
    op.create_index(
        'idx_conversation_threads_user_id',
        'conversation_threads',
        ['user_id']
    )
    
    # Composite index for user + active status queries (most common query pattern)
    op.create_index(
        'idx_conversation_threads_user_active',
        'conversation_threads',
        ['user_id', 'is_active']
    )
    
    # Index on created_at for chronological ordering
    op.create_index(
        'idx_conversation_threads_created_at',
        'conversation_threads',
        ['created_at']
    )
    
    # Index on updated_at for retrieving recently active threads
    op.create_index(
        'idx_conversation_threads_updated_at',
        'conversation_threads',
        ['updated_at']
    )
    
    # Composite index for active threads ordered by last update
    op.create_index(
        'idx_conversation_threads_active_updated',
        'conversation_threads',
        ['is_active', 'updated_at']
    )
    
    # GIN index on metadata JSONB for efficient JSON queries
    op.create_index(
        'idx_conversation_threads_metadata_gin',
        'conversation_threads',
        ['metadata'],
        postgresql_using='gin'
    )
    
    # Create trigger to automatically update updated_at timestamp
    op.execute("""
        CREATE OR REPLACE FUNCTION update_conversation_threads_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    
    op.execute("""
        CREATE TRIGGER trigger_conversation_threads_updated_at
        BEFORE UPDATE ON conversation_threads
        FOR EACH ROW
        EXECUTE FUNCTION update_conversation_threads_updated_at();
    """)


def downgrade() -> None:
    """
    Drops the conversation_threads table and related objects.
    """
    # Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS trigger_conversation_threads_updated_at ON conversation_threads")
    op.execute("DROP FUNCTION IF EXISTS update_conversation_threads_updated_at()")
    
    # Drop indexes (will be automatically dropped with table, but explicit for clarity)
    op.drop_index('idx_conversation_threads_metadata_gin', table_name='conversation_threads')
    op.drop_index('idx_conversation_threads_active_updated', table_name='conversation_threads')
    op.drop_index('idx_conversation_threads_updated_at', table_name='conversation_threads')
    op.drop_index('idx_conversation_threads_created_at', table_name='conversation_threads')
    op.drop_index('idx_conversation_threads_user_active', table_name='conversation_threads')
    op.drop_index('idx_conversation_threads_user_id', table_name='conversation_threads')
    
    # Drop table
    op.drop_table('conversation_threads')
