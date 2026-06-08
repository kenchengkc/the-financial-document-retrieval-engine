from __future__ import annotations

from pydantic import BaseModel, Field


class CoverageResponse(BaseModel):
    catalog_count: int = Field(description="NASDAQ/NYSE companies in the ingestion catalog")
    sp500_catalog_count: int = Field(description="S&P 500 names present in the catalog")
    indexed_count: int = Field(description="Companies with embedded chunks searchable via RAG")
    sp500_indexed_count: int = Field(description="S&P 500 companies currently indexed")
    document_count: int
    chunk_count: int
    indexed_tickers: list[str]


class CompanySummary(BaseModel):
    ticker: str
    cik: str
    name: str
    exchange: str | None
    document_count: int
    chunk_count: int
    indexed: bool


class CompaniesResponse(BaseModel):
    total: int
    companies: list[CompanySummary]
