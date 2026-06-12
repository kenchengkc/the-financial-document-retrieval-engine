"""add structured xbrl fields

Revision ID: f5a7b9c1d401
Revises: e4f6a8b0c301
Create Date: 2026-06-12 02:55:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5a7b9c1d401"
down_revision: str | None = "e4f6a8b0c301"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("financial_facts") as batch_op:
        batch_op.add_column(sa.Column("document_id", sa.Integer()))
        batch_op.add_column(sa.Column("fact_key", sa.String(length=64)))
        batch_op.add_column(sa.Column("taxonomy", sa.String(length=64)))
        batch_op.add_column(sa.Column("canonical_metric", sa.String(length=64)))
        batch_op.add_column(sa.Column("period_type", sa.String(length=16)))
        batch_op.add_column(sa.Column("frame", sa.String(length=32)))
        batch_op.add_column(sa.Column("filed_at", sa.Date()))
        batch_op.add_column(sa.Column("available_at", sa.DateTime(timezone=True)))
        batch_op.add_column(
            sa.Column(
                "is_amendment",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "is_restatement",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.create_foreign_key(
            "fk_financial_facts_document_id_documents",
            "documents",
            ["document_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_financial_facts_document_id", ["document_id"])
        batch_op.create_index("ix_financial_facts_canonical_metric", ["canonical_metric"])
        batch_op.create_index("ix_financial_facts_available_at", ["available_at"])
        batch_op.create_unique_constraint("uq_financial_facts_fact_key", ["fact_key"])
        batch_op.create_index(
            "ix_financial_facts_ticker_metric_period",
            ["ticker", "canonical_metric", "period_end"],
        )
        batch_op.create_index(
            "ix_financial_facts_document_metric",
            ["document_id", "canonical_metric"],
        )

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            UPDATE financial_facts AS fact
            SET document_id = document.id,
                available_at = document.available_at,
                taxonomy = 'us-gaap',
                period_type = CASE
                    WHEN fact.period_start IS NULL THEN 'instant'
                    ELSE 'duration'
                END,
                is_amendment = upper(coalesce(fact.form_type, '')) LIKE '%/A'
            FROM documents AS document
            WHERE document.accession_number = fact.accession_number
            """
        )


def downgrade() -> None:
    with op.batch_alter_table("financial_facts") as batch_op:
        batch_op.drop_index("ix_financial_facts_document_metric")
        batch_op.drop_index("ix_financial_facts_ticker_metric_period")
        batch_op.drop_constraint("uq_financial_facts_fact_key", type_="unique")
        batch_op.drop_index("ix_financial_facts_available_at")
        batch_op.drop_index("ix_financial_facts_canonical_metric")
        batch_op.drop_index("ix_financial_facts_document_id")
        batch_op.drop_constraint(
            "fk_financial_facts_document_id_documents",
            type_="foreignkey",
        )
        batch_op.drop_column("is_restatement")
        batch_op.drop_column("is_amendment")
        batch_op.drop_column("available_at")
        batch_op.drop_column("filed_at")
        batch_op.drop_column("frame")
        batch_op.drop_column("period_type")
        batch_op.drop_column("canonical_metric")
        batch_op.drop_column("taxonomy")
        batch_op.drop_column("fact_key")
        batch_op.drop_column("document_id")
