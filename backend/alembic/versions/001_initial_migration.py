"""Initial migration - create all tables

Revision ID: 001
Revises: 
Create Date: 2024-01-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('username', sa.String(100), unique=True, nullable=False, index=True),
        sa.Column('email', sa.String(255), unique=True, nullable=True),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    )
    
    # Create sessions table
    op.create_table(
        'sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('session_token', sa.String(255), unique=True, nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
    )
    op.create_index('ix_sessions_active', 'sessions', ['user_id', 'is_active'])
    
    # Create queries table
    op.create_table(
        'queries',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sessions.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('datasource_id', sa.String(100), nullable=True, index=True),
        sa.Column('datasource_name', sa.String(255), nullable=True),
        sa.Column('generated_query', postgresql.JSON(), nullable=True),
        sa.Column('response_text', sa.Text(), nullable=True),
        sa.Column('response_data', postgresql.JSON(), nullable=True),
        sa.Column('visualization_config', postgresql.JSON(), nullable=True),
        sa.Column('status', sa.String(20), default='pending', index=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('execution_time_ms', sa.Float(), nullable=True),
        sa.Column('row_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_queries_user_created', 'queries', ['user_id', 'created_at'])
    op.create_index('ix_queries_status_created', 'queries', ['status', 'created_at'])
    
    # Create query_feedback table
    op.create_table(
        'query_feedback',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('query_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('queries.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('feedback_type', sa.String(20), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('accuracy_rating', sa.Integer(), nullable=True),
        sa.Column('usefulness_rating', sa.Integer(), nullable=True),
        sa.Column('completeness_rating', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    
    # Create activity_logs table
    op.create_table(
        'activity_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column('activity_type', sa.String(50), nullable=False, index=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('resource_type', sa.String(50), nullable=True),
        sa.Column('resource_id', sa.String(100), nullable=True),
        sa.Column('endpoint', sa.String(255), nullable=True),
        sa.Column('method', sa.String(10), nullable=True),
        sa.Column('request_data', postgresql.JSON(), nullable=True),
        sa.Column('response_status', sa.Integer(), nullable=True),
        sa.Column('duration_ms', sa.Float(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('extra_data', postgresql.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, index=True),
    )
    op.create_index('ix_activity_type_created', 'activity_logs', ['activity_type', 'created_at'])
    op.create_index('ix_activity_user_created', 'activity_logs', ['user_id', 'created_at'])
    
    # Create usage_statistics table
    op.create_table(
        'usage_statistics',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('date', sa.DateTime(timezone=True), nullable=False, unique=True, index=True),
        sa.Column('total_queries', sa.Integer(), default=0),
        sa.Column('successful_queries', sa.Integer(), default=0),
        sa.Column('failed_queries', sa.Integer(), default=0),
        sa.Column('total_feedback', sa.Integer(), default=0),
        sa.Column('likes', sa.Integer(), default=0),
        sa.Column('dislikes', sa.Integer(), default=0),
        sa.Column('active_users', sa.Integer(), default=0),
        sa.Column('new_users', sa.Integer(), default=0),
        sa.Column('total_sessions', sa.Integer(), default=0),
        sa.Column('avg_execution_time_ms', sa.Float(), nullable=True),
        sa.Column('datasource_usage', postgresql.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('usage_statistics')
    op.drop_index('ix_activity_user_created')
    op.drop_index('ix_activity_type_created')
    op.drop_table('activity_logs')
    op.drop_table('query_feedback')
    op.drop_index('ix_queries_status_created')
    op.drop_index('ix_queries_user_created')
    op.drop_table('queries')
    op.drop_index('ix_sessions_active')
    op.drop_table('sessions')
    op.drop_table('users')
