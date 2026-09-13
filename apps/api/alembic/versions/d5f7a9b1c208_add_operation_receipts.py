"""add durable operation receipts

Revision ID: d5f7a9b1c208
Revises: c4e6f8a0b207
Create Date: 2026-09-13 13:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5f7a9b1c208"
down_revision: str | None = "c4e6f8a0b207"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operation_receipts",
        sa.Column("operation_id", sa.String(length=128), nullable=False),
        sa.Column("operation_type", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("operation_id"),
    )
    op.create_index(
        "ix_operation_receipts_type_created",
        "operation_receipts",
        ["operation_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_operation_receipts_type_created",
        table_name="operation_receipts",
    )
    op.drop_table("operation_receipts")
