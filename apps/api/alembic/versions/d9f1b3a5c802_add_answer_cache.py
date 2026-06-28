"""add answer_cache table

Revision ID: d9f1b3a5c802
Revises: c8e0a2f4b701
Create Date: 2026-06-28 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9f1b3a5c802"
down_revision: str | None = "c8e0a2f4b701"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "answer_cache",
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("cache_key", name=op.f("pk_answer_cache")),
    )


def downgrade() -> None:
    op.drop_table("answer_cache")
