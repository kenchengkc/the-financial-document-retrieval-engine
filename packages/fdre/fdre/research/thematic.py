from __future__ import annotations

from pydantic import BaseModel, Field

from fdre.retrieval.query import RetrievalCandidate, SearchFilters


class ThematicScanRequest(BaseModel):
    query: str = Field(min_length=1)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    issuers: int = Field(default=10, ge=2, le=100)
    results_per_issuer: int = Field(default=2, ge=1, le=10)


class ThematicIssuerResult(BaseModel):
    ticker: str
    company_name: str | None
    evidence: list[RetrievalCandidate]


class ThematicScanResponse(BaseModel):
    query: str
    filters: SearchFilters
    issuer_count: int
    issuers: list[ThematicIssuerResult]
    latency_ms: int


def diversify_candidates_by_issuer(
    candidates: list[RetrievalCandidate],
    *,
    issuer_limit: int,
    results_per_issuer: int,
) -> list[ThematicIssuerResult]:
    grouped: dict[str, list[RetrievalCandidate]] = {}
    names: dict[str, str | None] = {}
    for candidate in candidates:
        ticker = candidate.metadata.get("ticker")
        if not isinstance(ticker, str) or not ticker:
            continue
        if ticker not in grouped and len(grouped) >= issuer_limit:
            continue
        evidence = grouped.setdefault(ticker, [])
        if len(evidence) >= results_per_issuer:
            continue
        evidence.append(candidate)
        company_name = candidate.metadata.get("company_name")
        names[ticker] = company_name if isinstance(company_name, str) else None
    return [
        ThematicIssuerResult(
            ticker=ticker,
            company_name=names[ticker],
            evidence=evidence,
        )
        for ticker, evidence in grouped.items()
    ]
