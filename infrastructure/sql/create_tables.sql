-- Database schema for FinOps Intelligence Platform
-- Create tables for conversation context and query tracking

-- Conversations table
CREATE TABLE IF NOT EXISTS conversations (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR,
    title VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    context_data JSONB NOT NULL
);

-- Create index on user_id for faster lookups
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);

-- Create index on updated_at for cleanup operations
CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at);

-- Queries table
CREATE TABLE IF NOT EXISTS queries (
    id VARCHAR PRIMARY KEY,
    conversation_id VARCHAR REFERENCES conversations(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    response TEXT NOT NULL,
    execution_time FLOAT NOT NULL,
    success BOOLEAN DEFAULT TRUE NOT NULL,
    error TEXT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Create index on conversation_id for faster lookups
CREATE INDEX IF NOT EXISTS idx_queries_conversation_id ON queries(conversation_id);

-- Create index on timestamp for time-based queries
CREATE INDEX IF NOT EXISTS idx_queries_timestamp ON queries(timestamp);

-- Create index on success for filtering failed queries
CREATE INDEX IF NOT EXISTS idx_queries_success ON queries(success);