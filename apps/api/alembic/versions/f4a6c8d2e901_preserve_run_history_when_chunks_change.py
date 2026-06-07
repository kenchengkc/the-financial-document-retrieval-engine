"""preserve run history when chunks change

Revision ID: f4a6c8d2e901
Revises: 8b2d7f3a1c44
Create Date: 2026-06-07 02:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a6c8d2e901"
down_revision: str | None = "8b2d7f3a1c44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHUNK_REFERENCES = (
    ("retrieval_results", "fk_retrieval_results_chunk_id_chunks"),
    ("citations", "fk_citations_chunk_id_chunks"),
)


def upgrade() -> None:
    """Keep historical runs when reparsing removes their source chunks."""
    for table_name, constraint_name in _CHUNK_REFERENCES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(constraint_name, type_="foreignkey")
            batch_op.alter_column(
                "chunk_id",
                existing_type=sa.Integer(),
                nullable=True,
            )
            batch_op.create_foreign_key(
                constraint_name,
                "chunks",
                ["chunk_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    """Remove orphaned history before restoring required chunk references."""
    for table_name, _ in _CHUNK_REFERENCES:
        op.execute(sa.text(f"DELETE FROM {table_name} WHERE chunk_id IS NULL"))

    for table_name, constraint_name in _CHUNK_REFERENCES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(constraint_name, type_="foreignkey")
            batch_op.alter_column(
                "chunk_id",
                existing_type=sa.Integer(),
                nullable=False,
            )
            batch_op.create_foreign_key(
                constraint_name,
                "chunks",
                ["chunk_id"],
                ["id"],
            )
