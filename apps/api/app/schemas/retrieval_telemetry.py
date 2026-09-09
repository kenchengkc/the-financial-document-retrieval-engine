from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LatencyDistribution(BaseModel):
    sample_size: int
    p50_ms: int | None
    p95_ms: int | None
    mean_ms: float | None
    min_ms: int | None
    max_ms: int | None


class RetrievalVariantTelemetry(BaseModel):
    retriever_variant: str
    latency: LatencyDistribution


class AnswerTelemetry(BaseModel):
    latency: LatencyDistribution
    abstention_rate: float | None = Field(ge=0.0, le=1.0)
    mean_confidence: float | None


class RetrievalTelemetryResponse(BaseModel):
    """Content-free aggregates over independent latest-N persisted run samples."""

    generated_at: datetime
    sample_limit: int = Field(
        description=(
            "Maximum rows selected independently from retrieval_runs and answer_runs; "
            "this is not a fixed time-window sample."
        )
    )
    retrieval_runs_observed: int
    answer_runs_observed: int
    earliest_observed_at: datetime | None
    latest_observed_at: datetime | None
    retrieval_latency: LatencyDistribution
    retrieval_variants: list[RetrievalVariantTelemetry]
    answers: AnswerTelemetry
