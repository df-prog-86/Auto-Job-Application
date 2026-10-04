"""add job search results

Revision ID: e8b1c4d7a2f9
Revises: d5a2b9c4e1f7
Create Date: 2026-10-04 17:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8b1c4d7a2f9'
down_revision: Union[str, None] = 'd5a2b9c4e1f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'job_search_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('company', sa.String(length=300), nullable=False),
        sa.Column('location', sa.String(length=300), nullable=True),
        sa.Column('work_type', sa.String(length=30), nullable=True),
        sa.Column('salary_text', sa.String(length=200), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('url', sa.String(length=1000), nullable=False),
        sa.Column('url_key', sa.String(length=1000), nullable=False),
        sa.Column('grounded', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='new'),
        sa.Column('job_id', sa.Integer(), nullable=True),
        sa.Column('criteria', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('job_search_results', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_job_search_results_url'), ['url'], unique=False)
        batch_op.create_index(batch_op.f('ix_job_search_results_url_key'), ['url_key'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('job_search_results', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_job_search_results_url_key'))
        batch_op.drop_index(batch_op.f('ix_job_search_results_url'))
    op.drop_table('job_search_results')
