"""add pending_questions

Revision ID: c3e8a5d2f7b1
Revises: b7d4e9a1c3f6
Create Date: 2026-10-01 16:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e8a5d2f7b1'
down_revision: Union[str, None] = 'b7d4e9a1c3f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pending_questions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=500), nullable=False),
        sa.Column('question_key', sa.String(length=500), nullable=False),
        sa.Column('field_type', sa.String(length=30), nullable=False),
        sa.Column('options', sa.JSON(), nullable=False),
        sa.Column('required', sa.Boolean(), nullable=False),
        sa.Column('page_url', sa.String(length=1000), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('answer_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('pending_questions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pending_questions_job_id'), ['job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pending_questions_question_key'), ['question_key'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('pending_questions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_pending_questions_question_key'))
        batch_op.drop_index(batch_op.f('ix_pending_questions_job_id'))
    op.drop_table('pending_questions')
