"""add applied_at and applied_via to jobs

Revision ID: i5f9d3a1e6c4
Revises: h4e8c2f0d5b3
Create Date: 2026-10-06 23:50:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'i5f9d3a1e6c4'
down_revision: Union[str, None] = 'h4e8c2f0d5b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('applied_via', sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_column('applied_via')
        batch_op.drop_column('applied_at')
