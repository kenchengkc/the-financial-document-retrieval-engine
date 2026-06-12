from __future__ import annotations

import math
import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.models import Chunk, Company, Document, DocumentElement
from fdre.retrieval.query import SearchFilters, chunk_matches_filters

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True, slots=True)
class SparseHit:
    chunk: Chunk
    score: float


class PostgresFullTextIndexer:
    """Use PostgreSQL full-text ranking with an offline SQLite fallback."""

    def search(
        self,
        session: Session,
        query: str,
        *,
        filters: SearchFilters,
        limit: int,
    ) -> list[SparseHit]:
        if session.get_bind().dialect.name == "postgresql":
            return self._search_postgres(session, query, filters=filters, limit=limit)
        return self._search_in_memory(session, query, filters=filters, limit=limit)

    def _search_postgres(
        self,
        session: Session,
        query: str,
        *,
        filters: SearchFilters,
        limit: int,
    ) -> list[SparseHit]:
        tsquery = build_sparse_tsquery(query)
        if not tsquery:
            return []
        parsed_query = func.to_tsquery("english", tsquery)
        score = func.ts_rank_cd(Chunk.search_vector, parsed_query).label("sparse_score")
        statement = (
            select(Chunk, score)
            .join(Document, Document.id == Chunk.document_id)
            .join(Company, Company.id == Document.company_id)
            .join(DocumentElement, DocumentElement.id == Chunk.element_id)
            .where(Chunk.search_vector.op("@@")(parsed_query))
        )
        if filters.tickers:
            statement = statement.where(Company.ticker.in_(filters.tickers))
        if filters.ciks:
            statement = statement.where(Company.cik.in_(filters.ciks))
        if filters.form_types:
            statement = statement.where(Document.form_type.in_(filters.form_types))
        if filters.filing_date_from:
            statement = statement.where(Document.filing_date >= filters.filing_date_from)
        if filters.filing_date_to:
            statement = statement.where(Document.filing_date <= filters.filing_date_to)
        if filters.sections:
            statement = statement.where(Chunk.section.in_(filters.sections))
        if filters.element_types:
            statement = statement.where(DocumentElement.element_type.in_(filters.element_types))
        if filters.chunk_types:
            statement = statement.where(Chunk.chunk_type.in_(filters.chunk_types))

        rows = session.execute(
            statement.order_by(score.desc(), Chunk.id).limit(limit)
        ).all()
        return [
            SparseHit(chunk=chunk, score=float(row_score))
            for chunk, row_score in rows
        ]

    def _search_in_memory(
        self,
        session: Session,
        query: str,
        *,
        filters: SearchFilters,
        limit: int,
    ) -> list[SparseHit]:
        query_tokens = set(TOKEN_PATTERN.findall(query.casefold()))
        if not query_tokens:
            return []
        hits: list[SparseHit] = []
        for chunk in session.scalars(select(Chunk).order_by(Chunk.id)):
            if not chunk_matches_filters(chunk, filters):
                continue
            text_tokens = TOKEN_PATTERN.findall(chunk.chunk_text.casefold())
            frequencies = {token: text_tokens.count(token) for token in query_tokens}
            if not any(frequencies.values()):
                continue
            score = sum(math.log1p(count) for count in frequencies.values()) / len(
                query_tokens
            )
            hits.append(SparseHit(chunk=chunk, score=score))
        return sorted(hits, key=lambda hit: (-hit.score, hit.chunk.id))[:limit]


def build_sparse_tsquery(query: str) -> str:
    """Build an OR query so partial lexical matches remain retrievable."""

    tokens = dict.fromkeys(TOKEN_PATTERN.findall(query.casefold()))
    return " | ".join(tokens)
