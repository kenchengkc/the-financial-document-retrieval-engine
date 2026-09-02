"""add historical universe membership evidence

Revision ID: b2d4f6a8c105
Revises: a1c3e5f7b904
Create Date: 2026-08-29 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2d4f6a8c105"
down_revision: str | None = "a1c3e5f7b904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "universe_membership_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("universe_code", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("effective_at", sa.Date(), nullable=False),
        sa.Column("announced_at", sa.Date()),
        sa.Column(
            "effective_session",
            sa.String(length=16),
            nullable=False,
            server_default="unspecified",
        ),
        sa.Column("raw_symbol", sa.String(length=32), nullable=False),
        sa.Column("raw_name", sa.Text()),
        sa.Column("raw_cik", sa.String(length=16)),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("source_record_id", sa.String(length=256)),
        sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_record_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "event_type IN ('addition', 'removal')",
            name="ck_universe_membership_evidence_event_type",
        ),
        sa.CheckConstraint(
            "effective_session IN ('before_open', 'after_close', 'unspecified')",
            name="ck_universe_membership_evidence_effective_session",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidence_id"),
    )
    op.create_index(
        "ix_universe_membership_evidence_universe_effective",
        "universe_membership_evidence",
        ["universe_code", "effective_at"],
        unique=False,
    )
    op.create_index(
        "ix_universe_membership_evidence_symbol_effective",
        "universe_membership_evidence",
        ["raw_symbol", "effective_at"],
        unique=False,
    )
    op.create_index(
        "ix_universe_membership_evidence_source_observed",
        "universe_membership_evidence",
        ["source", "source_observed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_universe_membership_evidence_source_observed",
        table_name="universe_membership_evidence",
    )
    op.drop_index(
        "ix_universe_membership_evidence_symbol_effective",
        table_name="universe_membership_evidence",
    )
    op.drop_index(
        "ix_universe_membership_evidence_universe_effective",
        table_name="universe_membership_evidence",
    )
    op.drop_table("universe_membership_evidence")
