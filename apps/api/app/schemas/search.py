from __future__ import annotations

from pydantic import BaseModel, Field

from fdre.retrieval.query import RetrievalCandidate, SearchFilters


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int = Field(default=10, ge=1, le=100)


class SearchResponse(BaseModel):
    query: str
    rewritten_queries: list[str]
    filters: SearchFilters
    results: list[RetrievalCandidate]
    latency_ms: int
