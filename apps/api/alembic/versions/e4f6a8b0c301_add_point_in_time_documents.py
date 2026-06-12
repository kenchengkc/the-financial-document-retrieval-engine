"""add point in time documents

Revision ID: e4f6a8b0c301
Revises: d3e5f7a9b201
Create Date: 2026-06-12 02:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4f6a8b0c301"
down_revision: str | None = "d3e5f7a9b201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("accepted_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("available_at", sa.DateTime(timezone=True)))
        batch_op.add_column(
            sa.Column(
                "is_amendment",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("amends_accession_number", sa.String(length=64)))
        batch_op.create_index("ix_documents_accepted_at", ["accepted_at"])
        batch_op.create_index("ix_documents_available_at", ["available_at"])
        batch_op.create_index("ix_documents_is_amendment", ["is_amendment"])
        batch_op.create_index(
            "ix_documents_amends_accession_number",
            ["amends_accession_number"],
        )
        batch_op.create_index(
            "ix_documents_company_form_period_available",
            ["company_id", "form_type", "period_end_date", "available_at"],
        )

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            UPDATE documents
            SET accepted_at = CASE
                    WHEN coalesce(metadata_json ->> 'acceptance_datetime', '') <> ''
                    THEN (metadata_json ->> 'acceptance_datetime')::timestamptz
                    WHEN filing_date IS NOT NULL
                    THEN filing_date::timestamp AT TIME ZONE 'UTC'
                    ELSE created_at
                END,
                available_at = CASE
                    WHEN coalesce(metadata_json ->> 'acceptance_datetime', '') <> ''
                    THEN (metadata_json ->> 'acceptance_datetime')::timestamptz
                    WHEN filing_date IS NOT NULL
                    THEN filing_date::timestamp AT TIME ZONE 'UTC'
                    ELSE created_at
                END,
                is_amendment = upper(form_type) LIKE '%/A'
            """
        )
        op.execute(
            """
            UPDATE documents AS amendment
            SET amends_accession_number = original.accession_number
            FROM documents AS original
            WHERE amendment.is_amendment
              AND original.company_id = amendment.company_id
              AND original.period_end_date = amendment.period_end_date
              AND upper(original.form_type) = replace(upper(amendment.form_type), '/A', '')
              AND NOT original.is_amendment
            """
        )
    else:
        op.execute(
            """
            UPDATE documents
            SET accepted_at = coalesce(filing_date, created_at),
                available_at = coalesce(filing_date, created_at),
                is_amendment = CASE
                    WHEN upper(form_type) LIKE '%/A' THEN 1
                    ELSE 0
                END
            """
        )


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_index("ix_documents_company_form_period_available")
        batch_op.drop_index("ix_documents_amends_accession_number")
        batch_op.drop_index("ix_documents_is_amendment")
        batch_op.drop_index("ix_documents_available_at")
        batch_op.drop_index("ix_documents_accepted_at")
        batch_op.drop_column("amends_accession_number")
        batch_op.drop_column("is_amendment")
        batch_op.drop_column("available_at")
        batch_op.drop_column("accepted_at")
