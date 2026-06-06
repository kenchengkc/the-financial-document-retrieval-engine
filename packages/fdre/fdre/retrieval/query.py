from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

RouteName = Literal["text", "tables", "financial_facts"]


class SearchFilters(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    ciks: list[str] = Field(default_factory=list)
    form_types: list[str] = Field(default_factory=list)
    filing_date_from: date | None = None
    filing_date_to: date | None = None
    sections: list[str] = Field(default_factory=list)
    element_types: list[str] = Field(default_factory=list)
    chunk_types: list[str] = Field(default_factory=list)


class SearchQuery(BaseModel):
    query: str = Field(min_length=1)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int = Field(default=10, ge=1, le=100)


class PreprocessedQuery(BaseModel):
    original_query: str
    rewritten_queries: list[str]
    filters: SearchFilters
    routes: list[RouteName]


class RetrievalCandidate(BaseModel):
    chunk_id: int
    text: str
    metadata: dict[str, Any]
    dense_score: float | None = None
    sparse_score: float | None = None
    hybrid_score: float | None = None
    rerank_score: float | None = None
    rank: int | None = None


def chunk_matches_filters(chunk: Any, filters: SearchFilters) -> bool:
    metadata = chunk.metadata_json or {}
    if filters.tickers and metadata.get("ticker") not in filters.tickers:
        return False
    if filters.ciks and metadata.get("cik") not in filters.ciks:
        return False
    if filters.form_types and metadata.get("form_type") not in filters.form_types:
        return False
    if filters.sections and chunk.section not in filters.sections:
        return False
    if filters.element_types and metadata.get("element_type") not in filters.element_types:
        return False
    if filters.chunk_types and chunk.chunk_type not in filters.chunk_types:
        return False
    filing_date = metadata.get("filing_date")
    parsed_date = date.fromisoformat(filing_date) if isinstance(filing_date, str) else None
    if filters.filing_date_from and (
        parsed_date is None or parsed_date < filters.filing_date_from
    ):
        return False
    return not (
        filters.filing_date_to
        and (parsed_date is None or parsed_date > filters.filing_date_to)
    )
