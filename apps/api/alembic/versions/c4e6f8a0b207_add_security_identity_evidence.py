"""add durable historical-universe SEC identity evidence

Revision ID: c4e6f8a0b207
Revises: a7c9e1f3b205
Create Date: 2026-09-03 06:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e6f8a0b207"
down_revision: str | None = "a7c9e1f3b205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_identity_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("security_identity_period_id", sa.Integer(), nullable=False),
        sa.Column("cik", sa.String(length=10), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("accession_number", sa.String(length=32), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("form_type", sa.String(length=16), nullable=False),
        sa.Column("concept_name", sa.String(length=128), nullable=False),
        sa.Column("context_ref", sa.String(length=256)),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("decision_hash", sa.String(length=64), nullable=False),
        sa.Column("state_decision_hash", sa.String(length=64), nullable=False),
        sa.Column("state_lineage_id", sa.String(length=64), nullable=False),
        sa.Column("projection_plan_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["security_identity_period_id"],
            ["security_identity_periods.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidence_id"),
    )
    op.create_index(
        "ix_security_identity_evidence_identity",
        "security_identity_evidence",
        ["security_identity_period_id"],
        unique=False,
    )
    op.create_index(
        "ix_security_identity_evidence_accession",
        "security_identity_evidence",
        ["accession_number"],
        unique=False,
    )
    op.create_index(
        "ix_security_identity_evidence_plan",
        "security_identity_evidence",
        ["projection_plan_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_security_identity_evidence_plan",
        table_name="security_identity_evidence",
    )
    op.drop_index(
        "ix_security_identity_evidence_accession",
        table_name="security_identity_evidence",
    )
    op.drop_index(
        "ix_security_identity_evidence_identity",
        table_name="security_identity_evidence",
    )
    op.drop_table("security_identity_evidence")
