"""store embeddings with pgvector

Revision ID: 8b2d7f3a1c44
Revises: e60bbbb80e8c
Create Date: 2026-06-07 11:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "8b2d7f3a1c44"
down_revision: str | None = "e60bbbb80e8c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Move portable JSON vectors into native pgvector storage."""
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        vector_type: sa.types.TypeEngine[object] = Vector()
    else:
        vector_type = sa.JSON()

    op.add_column("embeddings", sa.Column("vector", vector_type, nullable=True))
    if dialect == "postgresql":
        op.execute("UPDATE embeddings SET vector = vector_json::text::vector")
        op.alter_column("embeddings", "vector", existing_type=Vector(), nullable=False)
        op.drop_column("embeddings", "vector_json")
    else:
        op.execute("UPDATE embeddings SET vector = vector_json")
        with op.batch_alter_table("embeddings") as batch_op:
            batch_op.alter_column(
                "vector",
                existing_type=sa.JSON(),
                nullable=False,
            )
            batch_op.drop_column("vector_json")

    if dialect == "postgresql":
        op.create_unique_constraint(
            "uq_embeddings_chunk_provider_model",
            "embeddings",
            ["chunk_id", "provider", "model"],
        )
    else:
        with op.batch_alter_table("embeddings") as batch_op:
            batch_op.create_unique_constraint(
                "uq_embeddings_chunk_provider_model",
                ["chunk_id", "provider", "model"],
            )


def downgrade() -> None:
    """Restore JSON vector storage."""
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.drop_constraint(
            "uq_embeddings_chunk_provider_model",
            "embeddings",
            type_="unique",
        )
    else:
        with op.batch_alter_table("embeddings") as batch_op:
            batch_op.drop_constraint(
                "uq_embeddings_chunk_provider_model",
                type_="unique",
            )
    op.add_column("embeddings", sa.Column("vector_json", sa.JSON(), nullable=True))
    if dialect == "postgresql":
        op.execute("UPDATE embeddings SET vector_json = vector::text::json")
        op.alter_column(
            "embeddings",
            "vector_json",
            existing_type=sa.JSON(),
            nullable=False,
        )
        op.drop_column("embeddings", "vector")
    else:
        op.execute("UPDATE embeddings SET vector_json = vector")
        with op.batch_alter_table("embeddings") as batch_op:
            batch_op.alter_column(
                "vector_json",
                existing_type=sa.JSON(),
                nullable=False,
            )
            batch_op.drop_column("vector")
