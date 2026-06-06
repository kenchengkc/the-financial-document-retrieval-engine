from __future__ import annotations

import math
import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.models import Chunk
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
        vector = func.to_tsvector("english", Chunk.chunk_text)
        parsed_query = func.plainto_tsquery("english", query)
        score = func.ts_rank_cd(vector, parsed_query).label("sparse_score")
        rows = session.execute(
            select(Chunk, score)
            .where(vector.op("@@")(parsed_query))
            .order_by(score.desc())
            .limit(max(limit * 5, limit))
        ).all()
        hits = [
            SparseHit(chunk=chunk, score=float(row_score))
            for chunk, row_score in rows
            if chunk_matches_filters(chunk, filters)
        ]
        return hits[:limit]

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
