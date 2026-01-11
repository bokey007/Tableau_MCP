"""Add analyzed_data column to queries table

Revision ID: 002
Revises: 001
Create Date: 2026-01-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_add_analyzed_data'
down_revision: Union[str, None] = '001_initial_migration'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add analyzed_data column to queries table."""
    op.add_column(
        'queries',
        sa.Column('analyzed_data', sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    """Remove analyzed_data column from queries table."""
    op.drop_column('queries', 'analyzed_data')
