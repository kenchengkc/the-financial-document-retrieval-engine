"""add PIT screen document index

Revision ID: f2a4c6e8b103
Revises: e1f3a5c7d902
Create Date: 2026-08-27 18:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a4c6e8b103"
down_revision: str | None = "e1f3a5c7d902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_documents_pit_screen_select",
        "documents",
        ["company_id", "form_type", "available_at", "id"],
        unique=False,
        postgresql_where=sa.text(
            "available_at IS NOT NULL AND period_end_date IS NOT NULL "
            "AND is_amendment IS false"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_documents_pit_screen_select", table_name="documents")
