from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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
