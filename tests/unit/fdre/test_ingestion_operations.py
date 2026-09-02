from __future__ import annotations

from argparse import Namespace
from typing import Any

from scripts.ingest_company_facts_batch import selected_tickers
from scripts.ingestion_lock import ingestion_lock_is_busy, serialized_ingestion
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Company, Document


def test_company_facts_selector_slices_research_universe() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    args = Namespace(tickers=None, universe="research50", offset=8, limit=2)

    with Session(engine) as session:
        assert selected_tickers(args, session) == ["AXP", "BA"]


def test_company_facts_selector_uses_indexed_companies() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    indexed_a = Company(ticker="AAA", cik="0000000001", name="Indexed A")
    indexed_a.documents.append(
        Document(source_type="sec", form_type="10-K", accession_number="aaa")
    )
    unindexed = Company(ticker="BBB", cik="0000000002", name="Unindexed")
    indexed_c = Company(ticker="CCC", cik="0000000003", name="Indexed C")
    indexed_c.documents.append(
        Document(source_type="sec", form_type="10-Q", accession_number="ccc")
    )

    with Session(engine) as session:
        session.add_all([indexed_c, unindexed, indexed_a])
        session.commit()
        args = Namespace(tickers=None, universe="indexed", offset=0, limit=10)

        assert selected_tickers(args, session) == ["AAA", "CCC"]


def test_ingestion_lock_helpers_are_noops_for_sqlite() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    assert not ingestion_lock_is_busy(engine)
    with serialized_ingestion(engine, skip_if_locked=True) as acquired:
        assert acquired


def test_serialized_ingestion_uses_autocommit_for_postgres_lock() -> None:
    engine = _FakePostgresEngine()

    with serialized_ingestion(engine, skip_if_locked=False) as acquired:  # type: ignore[arg-type]
        assert acquired

    assert engine.connection is not None
    assert engine.connection.execution_options_calls == [
        {"isolation_level": "AUTOCOMMIT"}
    ]
    assert any("pg_advisory_lock" in statement for statement in engine.connection.statements)
    assert any("pg_advisory_unlock" in statement for statement in engine.connection.statements)


def test_serialized_ingestion_release_failure_does_not_fail_completed_work(
    capsys: Any,
) -> None:
    engine = _FakePostgresEngine(fail_unlock=True)

    with serialized_ingestion(engine, skip_if_locked=False) as acquired:  # type: ignore[arg-type]
        assert acquired

    assert "release_ingestion_lock_failed" in capsys.readouterr().out


class _FakeDialect:
    name = "postgresql"


class _FakePostgresEngine:
    dialect = _FakeDialect()

    def __init__(self, *, fail_unlock: bool = False) -> None:
        self.connection: _FakePostgresConnection | None = None
        self.fail_unlock = fail_unlock

    def connect(self) -> _FakePostgresConnection:
        self.connection = _FakePostgresConnection(fail_unlock=self.fail_unlock)
        return self.connection


class _FakePostgresConnection:
    def __init__(self, *, fail_unlock: bool) -> None:
        self.execution_options_calls: list[dict[str, str]] = []
        self.fail_unlock = fail_unlock
        self.statements: list[str] = []

    def execution_options(self, **kwargs: str) -> _FakePostgresConnection:
        self.execution_options_calls.append(kwargs)
        return self

    def __enter__(self) -> _FakePostgresConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def scalar(self, statement: object, params: object | None = None) -> bool:
        del params
        statement_text = str(statement)
        self.statements.append(statement_text)
        if "pg_advisory_unlock" in statement_text and self.fail_unlock:
            raise SQLAlchemyError("terminated")
        return True

    def execute(self, statement: object, params: object | None = None) -> None:
        del params
        self.statements.append(str(statement))
