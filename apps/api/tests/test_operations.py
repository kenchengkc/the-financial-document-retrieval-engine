from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import (
    Chunk,
    Company,
    Document,
    DocumentElement,
    Embedding,
    ResearchMetricSnapshot,
)
from apps.api.app.services.operations_service import (
    build_data_quality_report,
    finish_ingestion_run,
    get_data_quality_report,
    start_ingestion_run,
)


def test_ingestion_manifest_and_quality_report() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    current = Company(ticker="CURR", cik="0000000001", name="Current Company")
    document = Document(
        company=current,
        source_type="sec",
        form_type="10-K",
        accession_number="current-accession",
        available_at=now,
    )
    element = DocumentElement(
        document=document,
        element_type="text",
        text="Current filing evidence.",
        reading_order=1,
    )
    chunk = Chunk(
        document=document,
        element=element,
        chunk_text=element.text or "",
        chunk_type="text",
    )
    chunk.embeddings.append(
        Embedding(
            provider="local_hash",
            model="local-hash-v1",
            dimensions=3,
            vector=[0.1, 0.2, 0.3],
        )
    )
    stale = Company(ticker="OLD", cik="0000000002", name="Stale Company")
    stale.documents.append(
        Document(
            source_type="sec",
            form_type="10-Q",
            accession_number="stale-accession",
            available_at=now - timedelta(days=300),
        )
    )

    with Session(engine) as session:
        session.add_all([current, stale])
        session.commit()
        start_ingestion_run(
            session,
            run_key="run-1",
            pipeline="ticker_batch",
            config={"tickers": ["CURR"]},
        )
        finished = finish_ingestion_run(
            session,
            run_key="run-1",
            status="completed",
            stage_counts={"index": {"status": "completed"}},
            failures=[],
            retry_count=1,
            latency_ms=123,
            provider_usage={"estimated_tokens": 10},
            estimated_cost_usd=Decimal("0.000001"),
        )
        report = build_data_quality_report(session, stale_after_days=150)
        cached_report = get_data_quality_report(session, stale_after_days=150)
        snapshot_keys = set(session.scalars(select(ResearchMetricSnapshot.metric_key)))

    assert finished.status == "completed"
    assert finished.retry_count == 1
    assert report.embedding_coverage == 1.0
    assert report.documents_without_chunks == 1
    assert len(report.unchunked_documents) == 1
    assert report.unchunked_documents[0].ticker == "OLD"
    assert report.unchunked_documents[0].reason == "missing_local_path"
    assert report.stale_tickers == ["OLD"]
    assert "CURR:10-Q" in report.missing_expected_filings
    assert report.recent_ingestion_success_rate == 1.0
    assert cached_report.model_dump(exclude={"generated_at"}) == report.model_dump(
        exclude={"generated_at"}
    )
    assert snapshot_keys == {
        "research-console:companies",
        "research-console:coverage",
        "research-console:quality:150",
    }
