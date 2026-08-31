"""allow historical issuers without current tickers

Revision ID: a7c9e1f3b205
Revises: f2a4c6e8b103
Create Date: 2026-08-30 19:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c9e1f3b205"
down_revision: str | None = "b2d4f6a8c105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("companies") as batch_op:
        batch_op.alter_column(
            "ticker",
            existing_type=sa.String(length=32),
            nullable=True,
        )


def downgrade() -> None:
    connection = op.get_bind()
    null_count = connection.scalar(
        sa.text("SELECT count(*) FROM companies WHERE ticker IS NULL")
    )
    if int(null_count or 0) > 0:
        raise RuntimeError(
            "cannot make companies.ticker non-null while historical-only issuer rows exist"
        )
    with op.batch_alter_table("companies") as batch_op:
        batch_op.alter_column(
            "ticker",
            existing_type=sa.String(length=32),
            nullable=False,
        )
