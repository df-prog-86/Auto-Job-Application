"""add education degree abbreviation

Revision ID: f2c9a6d3b8e1
Revises: e8b1c4d7a2f9
Create Date: 2026-10-04 18:10:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2c9a6d3b8e1'
down_revision: Union[str, None] = 'e8b1c4d7a2f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('education', schema=None) as batch_op:
        batch_op.add_column(sa.Column('degree_short', sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('education', schema=None) as batch_op:
        batch_op.drop_column('degree_short')
