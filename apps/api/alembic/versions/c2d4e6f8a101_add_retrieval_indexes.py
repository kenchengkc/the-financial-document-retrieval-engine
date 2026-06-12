"""add retrieval indexes

Revision ID: c2d4e6f8a101
Revises: f4a6c8d2e901
Create Date: 2026-06-12 00:35:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision: str = "c2d4e6f8a101"
down_revision: str | None = "f4a6c8d2e901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BTREE_INDEXES = (
    (
        "ix_documents_company_form_filing_date",
        "documents",
        ("company_id", "form_type", "filing_date"),
    ),
    (
        "ix_chunks_document_section_type",
        "chunks",
        ("document_id", "section", "chunk_type"),
    ),
    (
        "ix_embeddings_provider_model_dimensions_chunk",
        "embeddings",
        ("provider", "model", "dimensions", "chunk_id"),
    ),
)


def upgrade() -> None:
    """Add indexed lexical and Voyage ANN retrieval paths."""
    bind = op.get_bind()
    dialect = bind.dialect.name
    inspector = sa.inspect(bind)
    chunk_columns = {column["name"] for column in inspector.get_columns("chunks")}
    if dialect != "postgresql":
        if "search_vector" not in chunk_columns:
            op.add_column("chunks", sa.Column("search_vector", sa.Text(), nullable=True))
        chunk_indexes = {
            index["name"] for index in sa.inspect(bind).get_indexes("chunks")
        }
        if "ix_chunks_search_vector_gin" not in chunk_indexes:
            op.create_index(
                "ix_chunks_search_vector_gin",
                "chunks",
                ["search_vector"],
            )
        for index_name, table_name, columns in _BTREE_INDEXES:
            existing_indexes = {
                index["name"] for index in sa.inspect(bind).get_indexes(table_name)
            }
            if index_name not in existing_indexes:
                op.create_index(index_name, table_name, list(columns))
        return

    if "search_vector" not in chunk_columns:
        op.add_column("chunks", sa.Column("search_vector", TSVECTOR(), nullable=True))
    op.execute(
        """
        UPDATE chunks
        SET search_vector = to_tsvector('english', coalesce(chunk_text, ''))
        WHERE search_vector IS NULL
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fdre_chunks_search_vector_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.search_vector :=
                to_tsvector('english', coalesce(NEW.chunk_text, ''));
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgname = 'trg_chunks_search_vector_update'
                  AND tgrelid = 'chunks'::regclass
            ) THEN
                CREATE TRIGGER trg_chunks_search_vector_update
                BEFORE INSERT OR UPDATE OF chunk_text ON chunks
                FOR EACH ROW
                EXECUTE FUNCTION fdre_chunks_search_vector_update();
            END IF;
        END
        $$
        """
    )

    index_statements = [
        (
            "ix_chunks_search_vector_gin",
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_chunks_search_vector_gin
            ON chunks USING gin (search_vector)
            """,
        ),
        *[
            (
                index_name,
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name} "
                f"ON {table_name} ({', '.join(columns)})",
            )
            for index_name, table_name, columns in _BTREE_INDEXES
        ],
        (
            "ix_embeddings_voyage_512_hnsw",
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_embeddings_voyage_512_hnsw
            ON embeddings
            USING hnsw ((vector::halfvec(512)) halfvec_cosine_ops)
            WITH (m = 16, ef_construction = 64)
            WHERE provider = 'voyage'
              AND model = 'voyage-4-large'
              AND dimensions = 512
            """,
        ),
    ]
    invalid_indexes = {
        index_name
        for index_name, _ in index_statements
        if _postgres_index_validity(bind, index_name) is False
    }
    with op.get_context().autocommit_block():
        for index_name, statement in index_statements:
            if index_name in invalid_indexes:
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")
            op.execute(statement)


def downgrade() -> None:
    """Remove retrieval-specific indexes and lexical maintenance."""
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_embeddings_voyage_512_hnsw")
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_chunks_search_vector_gin")
            for index_name, _, _ in reversed(_BTREE_INDEXES):
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")
        op.execute("DROP TRIGGER IF EXISTS trg_chunks_search_vector_update ON chunks")
        op.execute("DROP FUNCTION IF EXISTS fdre_chunks_search_vector_update()")
    else:
        for index_name, table_name, _ in reversed(_BTREE_INDEXES):
            op.drop_index(index_name, table_name=table_name)
        op.drop_index("ix_chunks_search_vector_gin", table_name="chunks")
    op.drop_column("chunks", "search_vector")


def _postgres_index_validity(bind: sa.engine.Connection, index_name: str) -> bool | None:
    return bind.execute(
        sa.text(
            """
            SELECT index_state.indisvalid
            FROM pg_index AS index_state
            JOIN pg_class AS index_class ON index_class.oid = index_state.indexrelid
            JOIN pg_namespace AS namespace ON namespace.oid = index_class.relnamespace
            WHERE namespace.nspname = current_schema()
              AND index_class.relname = :index_name
            """
        ),
        {"index_name": index_name},
    ).scalar_one_or_none()
