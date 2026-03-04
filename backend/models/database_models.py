"""
SQLAlchemy database models for the FinOps platform
"""

import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Boolean, Float, ForeignKey, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB, INET

Base = declarative_base()


class User(Base):
    """SQLAlchemy model for user accounts"""
    __tablename__ = "users"

    # From migration 008 (10 columns)
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, server_default="true", nullable=False)
    is_admin = Column(Boolean, server_default="false", nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    last_login_ip = Column(INET, nullable=True)
    preferences = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # From migration 011 (1 column)
    default_organization_id = Column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)

    # From migration 013 (4 columns)
    password_hash = Column(String(128), nullable=True)
    password_salt = Column(String(64), nullable=True)
    password_hash_version = Column(Integer, server_default="2", nullable=False)
    password_updated_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<User(id='{self.id}', email='{self.email}')>"


class Conversation(Base):
    """SQLAlchemy model for conversation storage"""
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, nullable=True, index=True)
    title = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Serialized conversation context data
    context_data = Column(JSON, nullable=False)  # Stores the full ConversationContext.to_dict() output

    # Relationships
    queries = relationship("Query", back_populates="conversation", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Conversation(id='{self.id}', user_id='{self.user_id}', title='{self.title}')>"


class Query(Base):
    """SQLAlchemy model for query tracking"""
    __tablename__ = "queries"

    id = Column(String, primary_key=True, index=True)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=True, index=True)
    query = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    execution_time = Column(Float, nullable=False)
    success = Column(Boolean, default=True, nullable=False)
    error = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Agent usage tracking
    agents_used = Column(JSON, nullable=True)  # List of AgentType enums

    # Additional metadata
    query_metadata = Column(JSON, nullable=True)

    # Relationships
    conversation = relationship("Conversation", back_populates="queries")

    def __repr__(self):
        return f"<Query(id='{self.id}', conversation_id='{self.conversation_id}', success={self.success})>"