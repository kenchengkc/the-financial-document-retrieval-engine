from __future__ import annotations

import threading
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.models import Chunk, Company, Document, Embedding
from apps.api.app.schemas.companies import CompaniesResponse, CompanySummary, CoverageResponse
from fdre.ingestion.ticker_map import catalog_company_count, sp500_primary_tickers

_DEMO_TICKERS = frozenset({"EXMPL"})
# The corpus only changes when ingest runs (daily), but these aggregates cost
# ~10s of Neon compute over 2.7M embedding rows. Cache them long enough that
# sparse traffic actually hits the cache instead of always paying cold price.
_COVERAGE_CACHE_TTL_SECONDS = 900.0
_coverage_cache: dict[int, tuple[float, CoverageResponse]] = {}
_coverage_cache_lock = threading.Lock()
_COMPANIES_CACHE_TTL_SECONDS = 900.0
_companies_cache: dict[int, tuple[float, list[CompanySummary]]] = {}
_companies_cache_lock = threading.Lock()


def get_coverage(session: Session) -> CoverageResponse:
    bind = session.get_bind()
    cache_key = id(bind)
    now = time.monotonic()
    with _coverage_cache_lock:
        cached = _coverage_cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return cached[1].model_copy(deep=True)

    indexed_tickers = [
        ticker for ticker in _indexed_company_tickers(session) if ticker not in _DEMO_TICKERS
    ]
    sp500_catalog = set(sp500_primary_tickers())
    sp500_indexed = [ticker for ticker in indexed_tickers if ticker in sp500_catalog]

    document_count = session.scalar(select(func.count()).select_from(Document)) or 0
    chunk_count = session.scalar(
        select(func.count(func.distinct(Embedding.chunk_id))).select_from(Embedding)
    ) or 0

    response = CoverageResponse(
        catalog_count=catalog_company_count(),
        sp500_catalog_count=len(sp500_catalog),
        indexed_count=len(indexed_tickers),
        sp500_indexed_count=len(sp500_indexed),
        document_count=document_count,
        chunk_count=chunk_count,
        indexed_tickers=indexed_tickers,
    )
    with _coverage_cache_lock:
        _coverage_cache[cache_key] = (
            now + _COVERAGE_CACHE_TTL_SECONDS,
            response.model_copy(deep=True),
        )
    return response


def clear_coverage_cache() -> None:
    with _coverage_cache_lock:
        _coverage_cache.clear()
    with _companies_cache_lock:
        _companies_cache.clear()


def _indexed_company_tickers(session: Session) -> list[str]:
    embedded_chunk_exists = (
        select(1)
        .select_from(Chunk)
        .join(Embedding, Embedding.chunk_id == Chunk.id)
        .where(Chunk.document_id == Document.id)
        .exists()
    )
    indexed_company_ids = (
        select(Document.company_id)
        .where(embedded_chunk_exists)
        .distinct()
        .subquery()
    )
    statement = (
        select(Company.ticker)
        .join(indexed_company_ids, indexed_company_ids.c.company_id == Company.id)
        .order_by(Company.ticker)
    )
    return list(session.scalars(statement))


def list_companies(
    session: Session,
    *,
    indexed_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> CompaniesResponse:
    rows = _cached_company_rows(session)
    summaries = [
        CompanySummary(
            ticker=row.ticker,
            cik=row.cik,
            name=row.name,
            exchange=row.exchange,
            document_count=row.document_count,
            chunk_count=row.chunk_count,
            indexed=row.chunk_count > 0,
        )
        for row in rows
        if row.ticker not in _DEMO_TICKERS and (not indexed_only or row.chunk_count > 0)
    ]
    page = summaries[offset : offset + limit]
    return CompaniesResponse(total=len(summaries), companies=page)


def _cached_company_rows(session: Session) -> list[CompanySummary]:
    cache_key = id(session.get_bind())
    now = time.monotonic()
    with _companies_cache_lock:
        cached = _companies_cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return cached[1]
    rows = _indexed_company_rows(session)
    with _companies_cache_lock:
        _companies_cache[cache_key] = (now + _COMPANIES_CACHE_TTL_SECONDS, rows)
    return rows


def _indexed_company_rows(session: Session) -> list[CompanySummary]:
    statement = (
        select(
            Company.ticker,
            Company.cik,
            Company.name,
            Company.exchange,
            func.count(func.distinct(Document.id)).label("document_count"),
            func.count(func.distinct(Embedding.chunk_id)).label("chunk_count"),
        )
        .select_from(Company)
        .outerjoin(Document, Document.company_id == Company.id)
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .outerjoin(Embedding, Embedding.chunk_id == Chunk.id)
        .group_by(Company.id)
        .order_by(Company.ticker)
    )
    rows = session.execute(statement).all()
    return [
        CompanySummary(
            ticker=row.ticker,
            cik=row.cik,
            name=row.name,
            exchange=row.exchange,
            document_count=int(row.document_count or 0),
            chunk_count=int(row.chunk_count or 0),
            indexed=int(row.chunk_count or 0) > 0,
        )
        for row in rows
    ]
