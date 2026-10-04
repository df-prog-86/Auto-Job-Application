"""add education gpa

Revision ID: d5a2b9c4e1f7
Revises: c3e8a5d2f7b1
Create Date: 2026-10-04 15:40:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5a2b9c4e1f7'
down_revision: Union[str, None] = 'c3e8a5d2f7b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('education', schema=None) as batch_op:
        batch_op.add_column(sa.Column('gpa', sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('education', schema=None) as batch_op:
        batch_op.drop_column('gpa')
