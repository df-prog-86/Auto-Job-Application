"""add match score fields to job search results

Revision ID: h4e8c2f0d5b3
Revises: g3d7b1e9c4a2
Create Date: 2026-10-05 00:10:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h4e8c2f0d5b3'
down_revision: Union[str, None] = 'g3d7b1e9c4a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('job_search_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('description', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('match_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('match_summary', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('match_gaps', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('match_from_page', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('job_search_results', schema=None) as batch_op:
        batch_op.drop_column('match_from_page')
        batch_op.drop_column('match_gaps')
        batch_op.drop_column('match_summary')
        batch_op.drop_column('match_score')
        batch_op.drop_column('description')
