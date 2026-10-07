"""add interviewing_at and followup_done_at to jobs

Revision ID: j6a0e4b2f7d5
Revises: i5f9d3a1e6c4
Create Date: 2026-10-07 00:10:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'j6a0e4b2f7d5'
down_revision: Union[str, None] = 'i5f9d3a1e6c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('interviewing_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('followup_done_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_column('followup_done_at')
        batch_op.drop_column('interviewing_at')
