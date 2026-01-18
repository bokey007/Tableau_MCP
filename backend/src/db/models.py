# =============================================================================
# Database Models
# =============================================================================
"""SQLAlchemy models for activity tracking and user management."""

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column


def utcnow() -> datetime:
    """Get current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


# =============================================================================
# Enums
# =============================================================================

class FeedbackType(str, PyEnum):
    """Feedback type enum."""
    LIKE = "like"
    DISLIKE = "dislike"
    NEUTRAL = "neutral"


class ActivityType(str, PyEnum):
    """Activity type enum."""
    QUERY = "query"
    FEEDBACK = "feedback"
    VIEW_DATASOURCE = "view_datasource"
    VIEW_METADATA = "view_metadata"
    EXPORT = "export"
    LOGIN = "login"
    LOGOUT = "logout"
    ERROR = "error"


class QueryStatus(str, PyEnum):
    """Query execution status."""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"


# =============================================================================
# User Model
# =============================================================================

class User(Base):
    """User model for tracking users."""
    
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    display_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    queries = relationship("Query", back_populates="user", cascade="all, delete-orphan")
    activities = relationship("ActivityLog", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}')>"


# =============================================================================
# Session Model
# =============================================================================

class Session(Base):
    """User session model."""
    
    __tablename__ = "sessions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_token = Column(String(255), unique=True, nullable=False)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="sessions")
    queries = relationship("Query", back_populates="session", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index("ix_sessions_active", "user_id", "is_active"),
    )
    
    def __repr__(self) -> str:
        return f"<Session(id={self.id}, user_id={self.user_id})>"


# =============================================================================
# Query Model
# =============================================================================

class Query(Base):
    """Query model for tracking all user queries."""
    
    __tablename__ = "queries"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Query details
    question = Column(Text, nullable=False)
    datasource_id = Column(String(100), nullable=True, index=True)
    datasource_name = Column(String(255), nullable=True)
    
    # Query type classification
    intent = Column(String(50), nullable=True)  # chat, data_query, comparison, anomaly, storytelling
    query_type = Column(String(50), nullable=True)  # standard, comparison, anomaly, storytelling
    context_scope = Column(String(20), nullable=True)  # filtered, global
    
    # Generated query
    generated_query = Column(JSON, nullable=True)
    
    # Response
    response_text = Column(Text, nullable=True)
    response_data = Column(JSON, nullable=True)  # Raw query result (limited)
    analyzed_data = Column(JSON, nullable=True)  # What LLM analyzed (for debugging)
    visualization_config = Column(JSON, nullable=True)
    
    # Status and performance
    status = Column(Enum(QueryStatus), default=QueryStatus.PENDING, index=True)
    error_message = Column(Text, nullable=True)
    execution_time_ms = Column(Float, nullable=True)
    row_count = Column(Integer, nullable=True)
    
    # Favorites
    is_favorite = Column(Boolean, default=False, index=True)
    favorite_label = Column(String(255), nullable=True)  # User-defined label for favorite
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="queries")
    session = relationship("Session", back_populates="queries")
    feedback = relationship("QueryFeedback", back_populates="query", uselist=False, cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index("ix_queries_user_created", "user_id", "created_at"),
        Index("ix_queries_status_created", "status", "created_at"),
        Index("ix_queries_user_favorite", "user_id", "is_favorite"),
    )
    
    def __repr__(self) -> str:
        return f"<Query(id={self.id}, status='{self.status}')>"


# =============================================================================
# Query Feedback Model
# =============================================================================

class QueryFeedback(Base):
    """User feedback on query responses (like/dislike)."""
    
    __tablename__ = "query_feedback"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_id = Column(UUID(as_uuid=True), ForeignKey("queries.id", ondelete="CASCADE"), nullable=False, unique=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Feedback
    feedback_type = Column(Enum(FeedbackType), nullable=False)
    rating = Column(Integer, nullable=True)  # 1-5 scale (optional)
    comment = Column(Text, nullable=True)
    
    # Categories for detailed feedback
    accuracy_rating = Column(Integer, nullable=True)  # 1-5
    usefulness_rating = Column(Integer, nullable=True)  # 1-5
    completeness_rating = Column(Integer, nullable=True)  # 1-5
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    
    # Relationships
    query = relationship("Query", back_populates="feedback")
    
    def __repr__(self) -> str:
        return f"<QueryFeedback(id={self.id}, type='{self.feedback_type}')>"


# =============================================================================
# Activity Log Model
# =============================================================================

class ActivityLog(Base):
    """Comprehensive activity logging."""
    
    __tablename__ = "activity_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    
    # Activity details
    activity_type = Column(Enum(ActivityType), nullable=False, index=True)
    description = Column(Text, nullable=True)
    
    # Related resources
    resource_type = Column(String(50), nullable=True)  # query, datasource, etc.
    resource_id = Column(String(100), nullable=True)
    
    # Request details
    endpoint = Column(String(255), nullable=True)
    method = Column(String(10), nullable=True)
    request_data = Column(JSON, nullable=True)
    response_status = Column(Integer, nullable=True)
    
    # Performance
    duration_ms = Column(Float, nullable=True)
    
    # Client info
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Extra data
    extra_data = Column(JSON, nullable=True)
    
    # Timestamp
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    
    # Relationships
    user = relationship("User", back_populates="activities")
    
    # Indexes
    __table_args__ = (
        Index("ix_activity_type_created", "activity_type", "created_at"),
        Index("ix_activity_user_created", "user_id", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"<ActivityLog(id={self.id}, type='{self.activity_type}')>"


# =============================================================================
# Usage Statistics Model (Aggregated)
# =============================================================================

class UsageStatistics(Base):
    """Aggregated usage statistics by day."""
    
    __tablename__ = "usage_statistics"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(DateTime(timezone=True), nullable=False, index=True, unique=True)
    
    # Query statistics
    total_queries = Column(Integer, default=0)
    successful_queries = Column(Integer, default=0)
    failed_queries = Column(Integer, default=0)
    
    # Feedback statistics
    total_feedback = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    dislikes = Column(Integer, default=0)
    
    # User statistics
    active_users = Column(Integer, default=0)
    new_users = Column(Integer, default=0)
    total_sessions = Column(Integer, default=0)
    
    # Performance
    avg_execution_time_ms = Column(Float, nullable=True)
    
    # Datasource usage (JSON map of datasource_id -> count)
    datasource_usage = Column(JSON, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    
    def __repr__(self) -> str:
        return f"<UsageStatistics(date={self.date})>"
