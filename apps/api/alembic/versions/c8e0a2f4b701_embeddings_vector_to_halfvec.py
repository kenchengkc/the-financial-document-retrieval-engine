"""convert embeddings.vector from vector to halfvec

The HNSW index already operates on ``(vector)::halfvec(512)``, so search
precision is unchanged by this change; it only drops the *stored* column from
float32 to float16 (~2 bytes/dim), reclaiming ~3.4 GB. The ALTER rewrites the
embeddings table and rebuilds its indexes (the HNSW rebuild dominates), holding
an ACCESS EXCLUSIVE lock for the duration, so vector search is briefly offline
while it runs.

Revision ID: c8e0a2f4b701
Revises: b7c9d1e3f601
Create Date: 2026-06-27 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c8e0a2f4b701"
down_revision: str | None = "b7c9d1e3f601"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres-only: on SQLite (used in tests) the column is JSON via the model's
    # with_variant, so there is nothing to convert.
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("SET statement_timeout = 0")
    op.execute("ALTER TABLE embeddings ALTER COLUMN vector TYPE halfvec USING vector::halfvec")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("SET statement_timeout = 0")
    op.execute("ALTER TABLE embeddings ALTER COLUMN vector TYPE vector USING vector::vector")
