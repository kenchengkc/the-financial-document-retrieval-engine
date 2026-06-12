"""add reproducible eval fields

Revision ID: d3e5f7a9b201
Revises: c2d4e6f8a101
Create Date: 2026-06-12 01:25:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3e5f7a9b201"
down_revision: str | None = "c2d4e6f8a101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("eval_questions") as batch_op:
        batch_op.add_column(sa.Column("question_key", sa.String(length=128)))
        batch_op.add_column(sa.Column("split", sa.String(length=32)))
        batch_op.add_column(sa.Column("category", sa.String(length=64)))
        batch_op.add_column(sa.Column("relevant_evidence_json", sa.JSON()))
        batch_op.add_column(sa.Column("should_abstain", sa.Boolean()))
        batch_op.add_column(sa.Column("reviewed_by", sa.String(length=128)))
        batch_op.create_index("ix_eval_questions_question_key", ["question_key"], unique=True)
        batch_op.create_index("ix_eval_questions_split", ["split"])
        batch_op.create_index("ix_eval_questions_category", ["category"])


def downgrade() -> None:
    with op.batch_alter_table("eval_questions") as batch_op:
        batch_op.drop_index("ix_eval_questions_category")
        batch_op.drop_index("ix_eval_questions_split")
        batch_op.drop_index("ix_eval_questions_question_key")
        batch_op.drop_column("reviewed_by")
        batch_op.drop_column("should_abstain")
        batch_op.drop_column("relevant_evidence_json")
        batch_op.drop_column("category")
        batch_op.drop_column("split")
        batch_op.drop_column("question_key")
