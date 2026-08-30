"""allow historical issuers without current tickers

Revision ID: a7c9e1f3b205
Revises: f2a4c6e8b103
Create Date: 2026-08-30 19:20:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7c9e1f3b205"
down_revision: str | None = "f2a4c6e8b103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("companies") as batch_op:
        batch_op.alter_column("ticker", existing_type=None, nullable=True)


def downgrade() -> None:
    # Historical-only issuers deliberately carry ticker=NULL. A downgrade is unsafe until those
    # rows are removed or assigned a real current ticker, so fail rather than inventing identity.
    raise RuntimeError(
        "cannot make companies.ticker non-null while historical-only issuer rows may exist"
    )
