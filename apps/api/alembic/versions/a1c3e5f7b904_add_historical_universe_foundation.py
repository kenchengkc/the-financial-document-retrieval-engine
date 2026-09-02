"""add historical universe foundation

Revision ID: a1c3e5f7b904
Revises: f2a4c6e8b103
Create Date: 2026-08-29 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c3e5f7b904"
down_revision: str | None = "f2a4c6e8b103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "securities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column(
            "security_type",
            sa.String(length=32),
            nullable=False,
            server_default="common_stock",
        ),
        sa.Column("share_class", sa.String(length=64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_securities_company_id", "securities", ["company_id"], unique=False)
    op.create_index(
        "ix_securities_company_type",
        "securities",
        ["company_id", "security_type"],
        unique=False,
    )

    op.create_table(
        "security_identity_periods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("security_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text()),
        sa.Column("exchange", sa.String(length=64)),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "verification_status",
            sa.String(length=16),
            nullable=False,
            server_default="provisional",
        ),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_security_identity_period_valid_range",
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_security_identity_period_confidence",
        ),
        sa.CheckConstraint(
            "verification_status IN ('verified', 'provisional', 'rejected')",
            name="ck_security_identity_period_verification_status",
        ),
        sa.ForeignKeyConstraint(["security_id"], ["securities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "security_id",
            "symbol",
            "effective_from",
            name="uq_security_identity_period_start",
        ),
    )
    op.create_index(
        "ix_security_identity_symbol_effective",
        "security_identity_periods",
        ["symbol", "effective_from", "effective_to"],
        unique=False,
    )
    op.create_index(
        "ix_security_identity_security_effective",
        "security_identity_periods",
        ["security_id", "effective_from", "effective_to"],
        unique=False,
    )

    op.create_table(
        "universe_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("universe_code", sa.String(length=32), nullable=False),
        sa.Column("security_id", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("announced_at", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "verification_status",
            sa.String(length=16),
            nullable=False,
            server_default="provisional",
        ),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_universe_membership_valid_range",
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_universe_membership_confidence",
        ),
        sa.CheckConstraint(
            "verification_status IN ('verified', 'provisional', 'rejected')",
            name="ck_universe_membership_verification_status",
        ),
        sa.ForeignKeyConstraint(["security_id"], ["securities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "universe_code",
            "security_id",
            "effective_from",
            name="uq_universe_membership_period_start",
        ),
    )
    op.create_index(
        "ix_universe_membership_universe_effective",
        "universe_memberships",
        ["universe_code", "effective_from", "effective_to"],
        unique=False,
    )
    op.create_index(
        "ix_universe_membership_security_effective",
        "universe_memberships",
        ["security_id", "effective_from", "effective_to"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_universe_membership_security_effective",
        table_name="universe_memberships",
    )
    op.drop_index(
        "ix_universe_membership_universe_effective",
        table_name="universe_memberships",
    )
    op.drop_table("universe_memberships")

    op.drop_index(
        "ix_security_identity_security_effective",
        table_name="security_identity_periods",
    )
    op.drop_index(
        "ix_security_identity_symbol_effective",
        table_name="security_identity_periods",
    )
    op.drop_table("security_identity_periods")

    op.drop_index("ix_securities_company_type", table_name="securities")
    op.drop_index("ix_securities_company_id", table_name="securities")
    op.drop_table("securities")
