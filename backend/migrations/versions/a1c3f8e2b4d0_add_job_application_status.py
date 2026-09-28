"""add job application_status

Revision ID: a1c3f8e2b4d0
Revises: e47b5397b5cc
Create Date: 2026-09-27 22:05:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c3f8e2b4d0'
down_revision: Union[str, None] = 'e47b5397b5cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'application_status',
                sa.String(length=30),
                nullable=False,
                server_default='not_started',
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_column('application_status')
