"""create conversation_messages table

Revision ID: 002
Revises: 001
Create Date: 2025-11-12 10:05:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import text as sa_text

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Creates the conversation_messages table for storing individual messages within threads.
    
    This table stores all messages in a conversation, including user queries, assistant responses,
    system messages, and tool call records. Messages are ordered using ordering_index.
    """
    # Create ENUM types for role and message_type (with IF NOT EXISTS for idempotency)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE message_role AS ENUM ('user', 'assistant', 'system');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE message_type AS ENUM ('query', 'context', 'response', 'tool_call');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create conversation_messages table
    op.create_table(
        'conversation_messages',
        # Primary key
        sa.Column(
            'id',
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text('gen_random_uuid()'),
            comment='Primary key, auto-generated UUID for the message'
        ),
        # Foreign key to conversation_threads
        sa.Column(
            'thread_id',
            UUID(as_uuid=True),
            sa.ForeignKey('conversation_threads.thread_id', ondelete='CASCADE'),
            nullable=False,
            comment='Foreign key reference to the parent conversation thread'
        ),
        # Message role (who sent the message)
        sa.Column(
            'role',
            sa.Text(),
            nullable=False,
            comment='Role of the message sender: user (end user), assistant (AI agent), or system (system-generated)'
        ),
        # Message content
        sa.Column(
            'content',
            sa.Text,
            nullable=False,
            comment='The actual text content of the message'
        ),
        # Message type classification
        sa.Column(
            'message_type',
            sa.Text(),
            nullable=False,
            comment='Type of message: query (user question), context (system context), response (assistant answer), or tool_call (tool execution)'
        ),
        # Flexible metadata storage
        sa.Column(
            'metadata',
            JSONB,
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
            comment='Flexible JSONB field for storing message metadata like tokens used, model version, execution time, etc.'
        ),
        # Ordering within the conversation
        sa.Column(
            'ordering_index',
            sa.Integer,
            nullable=False,
            comment='Integer index for maintaining message order within a conversation thread'
        ),
        # Timestamp tracking
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when the message was created'
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
            comment='Timestamp when the message was last updated'
        ),
        # Unique constraint to prevent duplicate ordering within a thread
        sa.UniqueConstraint('thread_id', 'ordering_index', name='uq_thread_ordering'),
        comment='Table for storing individual messages within conversation threads'
    )
    
    # Alter columns to use ENUM types (after table creation to avoid type recreation issues)
    op.execute("ALTER TABLE conversation_messages ALTER COLUMN role TYPE message_role USING role::message_role")
    op.execute("ALTER TABLE conversation_messages ALTER COLUMN message_type TYPE message_type USING message_type::message_type")
    
    # Create indexes for performance optimization
    
    # Index on thread_id for fast thread-specific queries
    op.create_index(
        'idx_conversation_messages_thread_id',
        'conversation_messages',
        ['thread_id']
    )
    
    # Composite index for thread + ordering (most common query pattern)
    op.create_index(
        'idx_conversation_messages_thread_ordering',
        'conversation_messages',
        ['thread_id', 'ordering_index']
    )
    
    # Index on role for filtering messages by sender
    op.create_index(
        'idx_conversation_messages_role',
        'conversation_messages',
        ['role']
    )
    
    # Index on message_type for analytics
    op.create_index(
        'idx_conversation_messages_type',
        'conversation_messages',
        ['message_type']
    )
    
    # Composite index for thread + role queries
    op.create_index(
        'idx_conversation_messages_thread_role',
        'conversation_messages',
        ['thread_id', 'role']
    )
    
    # Index on created_at for chronological queries
    op.create_index(
        'idx_conversation_messages_created_at',
        'conversation_messages',
        ['created_at']
    )
    
    # GIN index on metadata JSONB for efficient JSON queries
    op.create_index(
        'idx_conversation_messages_metadata_gin',
        'conversation_messages',
        ['metadata'],
        postgresql_using='gin'
    )
    
    # Full-text search index on content
    op.execute("""
        CREATE INDEX idx_conversation_messages_content_fts 
        ON conversation_messages 
        USING gin(to_tsvector('english', content));
    """)
    
    # Create trigger to automatically update updated_at timestamp
    op.execute("""
        CREATE OR REPLACE FUNCTION update_conversation_messages_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    
    op.execute("""
        CREATE TRIGGER trigger_conversation_messages_updated_at
        BEFORE UPDATE ON conversation_messages
        FOR EACH ROW
        EXECUTE FUNCTION update_conversation_messages_updated_at();
    """)
    
    # Create trigger to update parent thread's updated_at when message is added/updated
    op.execute("""
        CREATE OR REPLACE FUNCTION update_parent_thread_timestamp()
        RETURNS TRIGGER AS $$
        BEGIN
            UPDATE conversation_threads 
            SET updated_at = CURRENT_TIMESTAMP 
            WHERE thread_id = NEW.thread_id;
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    
    op.execute("""
        CREATE TRIGGER trigger_update_parent_thread
        AFTER INSERT OR UPDATE ON conversation_messages
        FOR EACH ROW
        EXECUTE FUNCTION update_parent_thread_timestamp();
    """)


def downgrade() -> None:
    """
    Drops the conversation_messages table and related objects.
    """
    # Drop triggers and functions
    op.execute("DROP TRIGGER IF EXISTS trigger_update_parent_thread ON conversation_messages")
    op.execute("DROP TRIGGER IF EXISTS trigger_conversation_messages_updated_at ON conversation_messages")
    op.execute("DROP FUNCTION IF EXISTS update_parent_thread_timestamp()")
    op.execute("DROP FUNCTION IF EXISTS update_conversation_messages_updated_at()")
    
    # Drop indexes
    op.execute("DROP INDEX IF EXISTS idx_conversation_messages_content_fts")
    op.drop_index('idx_conversation_messages_metadata_gin', table_name='conversation_messages')
    op.drop_index('idx_conversation_messages_created_at', table_name='conversation_messages')
    op.drop_index('idx_conversation_messages_thread_role', table_name='conversation_messages')
    op.drop_index('idx_conversation_messages_type', table_name='conversation_messages')
    op.drop_index('idx_conversation_messages_role', table_name='conversation_messages')
    op.drop_index('idx_conversation_messages_thread_ordering', table_name='conversation_messages')
    op.drop_index('idx_conversation_messages_thread_id', table_name='conversation_messages')
    
    # Drop table
    op.drop_table('conversation_messages')
    
    # Drop ENUM types
    op.execute("DROP TYPE IF EXISTS message_type")
    op.execute("DROP TYPE IF EXISTS message_role")
