from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.models import (
    Chunk,
    Company,
    Document,
    DocumentElement,
    Embedding,
    FinancialFact,
    IngestionRun,
)
from apps.api.app.schemas.operations import DataQualityReport, UnchunkedDocument


def start_ingestion_run(
    session: Session,
    *,
    run_key: str,
    pipeline: str,
    config: dict[str, Any],
) -> IngestionRun:
    run = IngestionRun(
        run_key=run_key,
        pipeline=pipeline,
        status="running",
        config_json=config,
        stage_counts_json={},
        failures_json=[],
        provider_usage_json={},
        estimated_cost_usd=Decimal(0),
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def finish_ingestion_run(
    session: Session,
    *,
    run_key: str,
    status: str,
    stage_counts: dict[str, Any],
    failures: list[dict[str, Any]],
    retry_count: int,
    latency_ms: int,
    provider_usage: dict[str, Any],
    estimated_cost_usd: Decimal,
) -> IngestionRun:
    run = session.scalar(
        select(IngestionRun).where(IngestionRun.run_key == run_key)
    )
    if run is None:
        raise ValueError(f"Ingestion run {run_key} does not exist")
    run.status = status
    run.stage_counts_json = stage_counts
    run.failures_json = failures
    run.retry_count = retry_count
    run.latency_ms = latency_ms
    run.provider_usage_json = provider_usage
    run.estimated_cost_usd = estimated_cost_usd
    run.completed_at = datetime.now(UTC)
    session.commit()
    session.refresh(run)
    return run


def build_data_quality_report(
    session: Session,
    *,
    stale_after_days: int = 150,
) -> DataQualityReport:
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=stale_after_days)
    company_count = session.scalar(select(func.count()).select_from(Company)) or 0
    document_count = session.scalar(select(func.count()).select_from(Document)) or 0
    chunk_count = session.scalar(select(func.count()).select_from(Chunk)) or 0
    embedding_count = session.scalar(
        select(func.count(func.distinct(Embedding.chunk_id))).select_from(Embedding)
    ) or 0
    latest_by_company = session.execute(
        select(
            Company.ticker,
            func.max(Document.available_at).label("latest_available_at"),
        )
        .outerjoin(Document, Document.company_id == Company.id)
        .group_by(Company.id)
        .order_by(Company.ticker)
    ).all()
    stale_tickers = [
        row.ticker
        for row in latest_by_company
        if row.latest_available_at is None
        or _as_utc(row.latest_available_at) < cutoff
    ]
    form_rows = session.execute(
        select(Company.ticker, Document.form_type)
        .join(Document, Document.company_id == Company.id)
        .where(Document.form_type.in_(["10-K", "10-Q"]))
        .distinct()
    ).all()
    forms_by_ticker: dict[str, set[str]] = {}
    for ticker, form_type in form_rows:
        forms_by_ticker.setdefault(ticker, set()).add(form_type)
    missing_expected = [
        f"{row.ticker}:{form_type}"
        for row in latest_by_company
        for form_type in ("10-K", "10-Q")
        if form_type not in forms_by_ticker.get(row.ticker, set())
    ]
    duplicate_accession_groups = len(
        session.execute(
            select(Document.accession_number)
            .group_by(Document.accession_number)
            .having(func.count(Document.id) > 1)
        ).all()
    )
    element_count = func.count(DocumentElement.id).label("element_count")
    unchunked_rows = session.execute(
        select(
            Document.id.label("document_id"),
            Company.ticker,
            Document.accession_number,
            Document.form_type,
            Document.filing_date,
            Document.local_path,
            element_count,
        )
        .join(Company, Company.id == Document.company_id)
        .outerjoin(DocumentElement, DocumentElement.document_id == Document.id)
        .where(~Document.chunks.any())
        .group_by(
            Document.id,
            Company.ticker,
            Document.accession_number,
            Document.form_type,
            Document.filing_date,
            Document.local_path,
        )
        .order_by(Company.ticker, Document.accession_number)
        .limit(100)
    ).all()
    unchunked_documents = [
        UnchunkedDocument(
            document_id=int(row.document_id),
            ticker=row.ticker,
            accession_number=row.accession_number,
            form_type=row.form_type,
            filing_date=row.filing_date,
            local_path=row.local_path,
            element_count=int(row.element_count or 0),
            reason=_unchunked_reason(
                local_path=row.local_path,
                element_count=int(row.element_count or 0),
            ),
        )
        for row in unchunked_rows
    ]
    documents_without_chunks = session.scalar(
        select(func.count())
        .select_from(Document)
        .where(~Document.chunks.any())
    ) or 0
    chunks_without_embeddings = session.scalar(
        select(func.count())
        .select_from(Chunk)
        .where(~Chunk.embeddings.any())
    ) or 0
    facts_without_documents = session.scalar(
        select(func.count())
        .select_from(FinancialFact)
        .where(FinancialFact.document_id.is_(None))
    ) or 0
    recent_runs = list(
        session.scalars(
            select(IngestionRun)
            .where(IngestionRun.completed_at.is_not(None))
            .order_by(IngestionRun.completed_at.desc())
            .limit(20)
        )
    )
    success_rate = (
        sum(run.status == "completed" for run in recent_runs) / len(recent_runs)
        if recent_runs
        else None
    )
    return DataQualityReport(
        generated_at=now,
        company_count=company_count,
        document_count=document_count,
        chunk_count=chunk_count,
        embedding_count=embedding_count,
        stale_after_days=stale_after_days,
        stale_tickers=stale_tickers,
        missing_expected_filings=missing_expected,
        duplicate_accession_groups=duplicate_accession_groups,
        documents_without_chunks=documents_without_chunks,
        unchunked_documents=unchunked_documents,
        chunks_without_embeddings=chunks_without_embeddings,
        facts_without_documents=facts_without_documents,
        freshness_ratio=(
            (company_count - len(stale_tickers)) / company_count
            if company_count
            else 1.0
        ),
        document_chunk_coverage=(
            (document_count - documents_without_chunks) / document_count
            if document_count
            else 1.0
        ),
        embedding_coverage=(
            embedding_count / chunk_count if chunk_count else 1.0
        ),
        recent_ingestion_success_rate=success_rate,
        latest_ingestion_completed_at=(
            recent_runs[0].completed_at if recent_runs else None
        ),
    )


def _unchunked_reason(*, local_path: str | None, element_count: int) -> str:
    if not local_path:
        return "missing_local_path"
    if element_count == 0:
        return "no_parsed_elements"
    return "elements_present_not_chunked"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
