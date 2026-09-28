"""simplify job evaluation to a single resume-vs-job comparison

Drops the earlier four-stage qualification pipeline's columns/table
(hard_filter_result, required_coverage, preferred_score, domain_alignment,
seniority_alignment, preference_alignment, disqualifiers, and the
job_requirements table entirely) and adds a plain-language `summary`
column, per product direction to simplify scoring down to a direct
resume-vs-job-posting comparison. `gaps` keeps its column (JSON) but now
holds a flat list of strings instead of {requirement, type} objects --
existing scored jobs should be re-scored ("Re-score match") to get the new
shape; old rows are not migrated in place since the qualification pipeline
is fully re-run on demand, never averaged/merged.

Revision ID: b7d4e9a1c3f6
Revises: a1c3f8e2b4d0
Create Date: 2026-09-27 23:10:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d4e9a1c3f6'
down_revision: Union[str, None] = 'a1c3f8e2b4d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('job_evaluations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('summary', sa.Text(), nullable=False, server_default=''))
        batch_op.drop_column('hard_filter_result')
        batch_op.drop_column('required_coverage')
        batch_op.drop_column('preferred_score')
        batch_op.drop_column('domain_alignment')
        batch_op.drop_column('seniority_alignment')
        batch_op.drop_column('preference_alignment')
        batch_op.drop_column('disqualifiers')

    op.drop_table('job_requirements')


def downgrade() -> None:
    op.create_table(
        'job_requirements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('requirement_type', sa.String(length=50), nullable=False),
        sa.Column('normalized_requirement', sa.String(length=500), nullable=False),
        sa.Column('is_required', sa.Boolean(), nullable=False),
        sa.Column('source_text', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('weight', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    with op.batch_alter_table('job_evaluations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('hard_filter_result', sa.String(length=20), nullable=False, server_default='PASS'))
        batch_op.add_column(sa.Column('required_coverage', sa.Float(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('preferred_score', sa.Float(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('domain_alignment', sa.Float(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('seniority_alignment', sa.Float(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('preference_alignment', sa.Float(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('disqualifiers', sa.JSON(), nullable=False, server_default='[]'))
        batch_op.drop_column('summary')
