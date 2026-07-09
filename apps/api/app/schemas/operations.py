from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class UnchunkedDocument(BaseModel):
    document_id: int
    ticker: str
    accession_number: str
    form_type: str
    filing_date: date | None = None
    local_path: str | None = None
    element_count: int = 0
    reason: str


class DataQualityReport(BaseModel):
    generated_at: datetime
    company_count: int
    document_count: int
    chunk_count: int
    embedding_count: int
    stale_after_days: int
    stale_tickers: list[str]
    missing_expected_filings: list[str]
    duplicate_accession_groups: int
    documents_without_chunks: int
    unchunked_documents: list[UnchunkedDocument] = Field(default_factory=list)
    chunks_without_embeddings: int
    facts_without_documents: int
    freshness_ratio: float
    document_chunk_coverage: float
    embedding_coverage: float
    recent_ingestion_success_rate: float | None
    latest_ingestion_completed_at: datetime | None

    @property
    def healthy(self) -> bool:
        return (
            self.duplicate_accession_groups == 0
            and self.documents_without_chunks == 0
            and self.chunks_without_embeddings == 0
            and self.facts_without_documents == 0
        )
