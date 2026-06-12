import json
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from apps.api.app import models  # noqa: F401
from apps.api.app.db import Base

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_TABLES = set(Base.metadata.tables)


def test_initial_migration_upgrades_and_downgrades(tmp_path: Path) -> None:
    database_path = tmp_path / "fdre.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    config = Config(REPO_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    migrated_tables = set(inspect(engine).get_table_names())
    assert not EXPECTED_TABLES - migrated_tables

    command.downgrade(config, "base")

    remaining_tables = set(inspect(engine).get_table_names())
    assert EXPECTED_TABLES.isdisjoint(remaining_tables)


def test_pgvector_migration_preserves_existing_embeddings(tmp_path: Path) -> None:
    database_path = tmp_path / "fdre-vectors.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    config = Config(REPO_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "e60bbbb80e8c")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO companies (id, ticker, cik, name, created_at, updated_at)
                VALUES (
                    1,
                    'NVDA',
                    '0001045810',
                    'NVIDIA Corporation',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO documents
                    (
                        id,
                        company_id,
                        source_type,
                        form_type,
                        accession_number,
                        created_at
                    )
                VALUES (
                    1,
                    1,
                    'sec',
                    '10-K',
                    '0001045810-25-000023',
                    CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO document_elements
                    (id, document_id, element_type, reading_order, created_at)
                VALUES (1, 1, 'text', 1, CURRENT_TIMESTAMP)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO chunks
                    (
                        id,
                        document_id,
                        element_id,
                        chunk_text,
                        chunk_type,
                        created_at
                    )
                VALUES (
                    1,
                    1,
                    1,
                    'AI demand increased.',
                    'text',
                    CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO embeddings
                    (
                        id,
                        chunk_id,
                        provider,
                        model,
                        dimensions,
                        vector_json,
                        created_at
                    )
                VALUES (
                    1,
                    1,
                    'local_hash',
                    'local-hash-v1',
                    3,
                    '[0.1, 0.2, 0.3]',
                    CURRENT_TIMESTAMP
                )
                """
            )
        )

    command.upgrade(config, "head")

    columns = {column["name"] for column in inspect(engine).get_columns("embeddings")}
    assert "vector" in columns
    assert "vector_json" not in columns
    with engine.connect() as connection:
        stored_vector = connection.scalar(text("SELECT vector FROM embeddings WHERE id = 1"))
    assert json.loads(stored_vector) == [0.1, 0.2, 0.3]

    unique_constraints = inspect(engine).get_unique_constraints("embeddings")
    assert any(
        constraint["column_names"] == ["chunk_id", "provider", "model"]
        for constraint in unique_constraints
    )


def test_retrieval_index_migration_recovers_from_partial_upgrade(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "fdre-partial-index.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    config = Config(REPO_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "f4a6c8d2e901")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE chunks ADD COLUMN search_vector TEXT"))
        connection.execute(
            text(
                "CREATE INDEX ix_chunks_search_vector_gin "
                "ON chunks (search_vector)"
            )
        )

    command.upgrade(config, "head")

    indexes = {
        index["name"]
        for index in inspect(engine).get_indexes("chunks")
    }
    assert "ix_chunks_search_vector_gin" in indexes


def test_chunk_rebuild_preserves_run_history(tmp_path: Path) -> None:
    database_path = tmp_path / "fdre-history.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    config = Config(REPO_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(
            text(
                """
                INSERT INTO companies (id, ticker, cik, name, created_at, updated_at)
                VALUES (
                    1,
                    'AMZN',
                    '0001018724',
                    'Amazon.com, Inc.',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO documents
                    (id, company_id, source_type, form_type, accession_number, created_at)
                VALUES (1, 1, 'sec', '10-K', '0001018724-26-000004', CURRENT_TIMESTAMP)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO document_elements
                    (id, document_id, element_type, text, reading_order, created_at)
                VALUES (
                    1,
                    1,
                    'text',
                    'Competition presents an ongoing risk.',
                    1,
                    CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO chunks
                    (
                        id,
                        document_id,
                        element_id,
                        chunk_text,
                        chunk_type,
                        created_at
                    )
                VALUES (
                    1,
                    1,
                    1,
                    'Competition presents an ongoing risk.',
                    'text',
                    CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO retrieval_runs
                    (id, query, retriever_variant, created_at)
                VALUES (1, 'Amazon risk factors', 'hybrid', CURRENT_TIMESTAMP)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO retrieval_results
                    (id, retrieval_run_id, chunk_id, rank, created_at)
                VALUES (1, 1, 1, 1, CURRENT_TIMESTAMP)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO answer_runs
                    (id, question, abstained, created_at)
                VALUES (1, 'What risks did Amazon report?', 0, CURRENT_TIMESTAMP)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO citations
                    (
                        id,
                        answer_run_id,
                        chunk_id,
                        claim_text,
                        citation_text,
                        created_at
                    )
                VALUES (
                    1,
                    1,
                    1,
                    'Amazon reported competition risk.',
                    'Competition presents an ongoing risk.',
                    CURRENT_TIMESTAMP
                )
                """
            )
        )

        connection.execute(text("DELETE FROM document_elements WHERE id = 1"))

        assert connection.scalar(text("SELECT COUNT(*) FROM chunks")) == 0
        assert connection.scalar(
            text("SELECT chunk_id FROM retrieval_results WHERE id = 1")
        ) is None
        assert connection.scalar(text("SELECT chunk_id FROM citations WHERE id = 1")) is None
        assert (
            connection.scalar(text("SELECT citation_text FROM citations WHERE id = 1"))
            == "Competition presents an ongoing risk."
        )


def test_postgres_retrieval_indexes_support_indexed_plans() -> None:
    database_url = os.getenv("FDRE_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("FDRE_POSTGRES_TEST_URL is not configured")

    config = Config(REPO_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    vector = "[" + ",".join(["0.01"] * 512) + "]"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO companies (id, ticker, cik, name, created_at, updated_at)
                VALUES (
                    1001,
                    'AAPL',
                    '0000320193',
                    'Apple Inc.',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (id) DO NOTHING
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO documents
                    (
                        id,
                        company_id,
                        source_type,
                        form_type,
                        accession_number,
                        created_at
                    )
                VALUES (
                    1001,
                    1001,
                    'sec',
                    '10-K',
                    '0000320193-26-000100',
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (id) DO NOTHING
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO document_elements
                    (id, document_id, element_type, reading_order, created_at)
                VALUES (1001, 1001, 'text', 1, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO NOTHING
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO chunks
                    (
                        id,
                        document_id,
                        element_id,
                        chunk_text,
                        chunk_type,
                        created_at
                    )
                VALUES (
                    1001,
                    1001,
                    1001,
                    'Apple data center power constraints increased operating risk.',
                    'text',
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (id) DO NOTHING
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO embeddings
                    (
                        id,
                        chunk_id,
                        provider,
                        model,
                        dimensions,
                        vector,
                        created_at
                    )
                VALUES (
                    1001,
                    1001,
                    'voyage',
                    'voyage-4-large',
                    512,
                    CAST(:vector AS vector),
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"vector": vector},
        )

        connection.execute(text("SET LOCAL enable_seqscan = off"))
        lexical_plan = "\n".join(
            row[0]
            for row in connection.execute(
                text(
                    """
                    EXPLAIN
                    SELECT id
                    FROM chunks
                    WHERE search_vector @@ plainto_tsquery('english', 'power constraints')
                    """
                )
            )
        )
        dense_plan = "\n".join(
            row[0]
            for row in connection.execute(
                text(
                    """
                    EXPLAIN
                    SELECT id
                    FROM embeddings
                    WHERE provider = 'voyage'
                      AND model = 'voyage-4-large'
                      AND dimensions = 512
                    ORDER BY (vector::halfvec(512))
                        <=> (CAST(:vector AS vector)::halfvec(512))
                    LIMIT 10
                    """
                ),
                {"vector": vector},
            )
        )

    assert "ix_chunks_search_vector_gin" in lexical_plan
    assert "ix_embeddings_voyage_512_hnsw" in dense_plan
