from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.models import Chunk, Company, Document, Embedding
from apps.api.app.schemas.companies import CompaniesResponse, CompanySummary, CoverageResponse
from fdre.ingestion.ticker_map import catalog_company_count, sp500_primary_tickers

_DEMO_TICKERS = frozenset({"EXMPL"})


def get_coverage(session: Session) -> CoverageResponse:
    indexed_rows = _indexed_company_rows(session)
    indexed_tickers = [row.ticker for row in indexed_rows if row.ticker not in _DEMO_TICKERS]
    sp500_catalog = set(sp500_primary_tickers())
    sp500_indexed = [ticker for ticker in indexed_tickers if ticker in sp500_catalog]

    document_count = session.scalar(select(func.count()).select_from(Document)) or 0
    chunk_count = session.scalar(
        select(func.count(func.distinct(Embedding.chunk_id))).select_from(Embedding)
    ) or 0

    return CoverageResponse(
        catalog_count=catalog_company_count(),
        sp500_catalog_count=len(sp500_catalog),
        indexed_count=len(indexed_tickers),
        sp500_indexed_count=len(sp500_indexed),
        document_count=document_count,
        chunk_count=chunk_count,
        indexed_tickers=indexed_tickers,
    )


def list_companies(
    session: Session,
    *,
    indexed_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> CompaniesResponse:
    rows = _indexed_company_rows(session)
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
