"""add fit score and note to job search results

Revision ID: l8c2a6d4e9f7
Revises: k7b1f5c3a8e6
Create Date: 2026-10-11 13:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'l8c2a6d4e9f7'
down_revision: Union[str, None] = 'k7b1f5c3a8e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('job_search_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fit_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('fit_note', sa.String(length=300), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('job_search_results', schema=None) as batch_op:
        batch_op.drop_column('fit_note')
        batch_op.drop_column('fit_score')
