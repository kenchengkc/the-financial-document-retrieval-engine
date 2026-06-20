from __future__ import annotations

from argparse import Namespace

from scripts.ingest_company_facts_batch import selected_tickers
from scripts.ingestion_lock import ingestion_lock_is_busy, serialized_ingestion
from sqlalchemy import create_engine
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
