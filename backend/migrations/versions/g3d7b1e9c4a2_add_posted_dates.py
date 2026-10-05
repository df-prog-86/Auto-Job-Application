"""add posted dates to jobs and job search results

Revision ID: g3d7b1e9c4a2
Revises: f2c9a6d3b8e1
Create Date: 2026-10-04 23:50:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g3d7b1e9c4a2'
down_revision: Union[str, None] = 'f2c9a6d3b8e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('posted_at', sa.Date(), nullable=True))
    with op.batch_alter_table('job_search_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('posted_at', sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('job_search_results', schema=None) as batch_op:
        batch_op.drop_column('posted_at')
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_column('posted_at')
