"""add ingestion runs

Revision ID: b7c9d1e3f601
Revises: a6b8c0d2e501
Create Date: 2026-06-12 04:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c9d1e3f601"
down_revision: str | None = "a6b8c0d2e501"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_key", sa.String(length=64), nullable=False),
        sa.Column("pipeline", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("stage_counts_json", sa.JSON(), nullable=False),
        sa.Column("failures_json", sa.JSON(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("provider_usage_json", sa.JSON(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_runs")),
    )
    op.create_index("ix_ingestion_runs_run_key", "ingestion_runs", ["run_key"], unique=True)
    op.create_index("ix_ingestion_runs_pipeline", "ingestion_runs", ["pipeline"])
    op.create_index("ix_ingestion_runs_status", "ingestion_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_runs_status", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_pipeline", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_run_key", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
