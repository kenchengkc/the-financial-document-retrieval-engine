"""add research metric snapshots

Revision ID: e1f3a5c7d902
Revises: d9f1b3a5c802
Create Date: 2026-07-23 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f3a5c7d902"
down_revision: str | None = "d9f1b3a5c802"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_metric_snapshots",
        sa.Column("metric_key", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "metric_key",
            name=op.f("pk_research_metric_snapshots"),
        ),
    )


def downgrade() -> None:
    op.drop_table("research_metric_snapshots")
