"""add research experiments

Revision ID: a6b8c0d2e501
Revises: f5a7b9c1d401
Create Date: 2026-06-12 03:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a6b8c0d2e501"
down_revision: str | None = "f5a7b9c1d401"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_experiments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_key", sa.String(length=64), nullable=False),
        sa.Column("experiment_type", sa.String(length=64), nullable=False),
        sa.Column("dataset_version", sa.String(length=128), nullable=False),
        sa.Column("feature_version", sa.String(length=128), nullable=False),
        sa.Column("code_sha", sa.String(length=64), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("results_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_experiments")),
    )
    op.create_index(
        "ix_research_experiments_experiment_key",
        "research_experiments",
        ["experiment_key"],
        unique=True,
    )
    op.create_index(
        "ix_research_experiments_experiment_type",
        "research_experiments",
        ["experiment_type"],
    )
    op.create_index(
        "ix_research_experiments_dataset_version",
        "research_experiments",
        ["dataset_version"],
    )
    op.create_index(
        "ix_research_experiments_feature_version",
        "research_experiments",
        ["feature_version"],
    )
    op.create_index(
        "ix_research_experiments_code_sha",
        "research_experiments",
        ["code_sha"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_experiments_code_sha",
        table_name="research_experiments",
    )
    op.drop_index(
        "ix_research_experiments_feature_version",
        table_name="research_experiments",
    )
    op.drop_index(
        "ix_research_experiments_dataset_version",
        table_name="research_experiments",
    )
    op.drop_index(
        "ix_research_experiments_experiment_type",
        table_name="research_experiments",
    )
    op.drop_index(
        "ix_research_experiments_experiment_key",
        table_name="research_experiments",
    )
    op.drop_table("research_experiments")
