"""
SQLAlchemy database models for the FinOps platform
"""

from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Boolean, Float, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


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