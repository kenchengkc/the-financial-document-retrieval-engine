from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, datetime
from statistics import fmean

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import AnswerRun, RetrievalRun
from apps.api.app.schemas.retrieval_telemetry import (
    AnswerTelemetry,
    LatencyDistribution,
    RetrievalTelemetryResponse,
    RetrievalVariantTelemetry,
)


def get_retrieval_telemetry(
    session: Session,
    *,
    sample_limit: int = 1000,
) -> RetrievalTelemetryResponse:
    """Aggregate bounded latest-N telemetry without selecting persisted user content."""

    retrieval_rows = session.execute(
        select(
            RetrievalRun.retriever_variant,
            RetrievalRun.latency_ms,
            RetrievalRun.created_at,
        )
        .where(RetrievalRun.latency_ms.is_not(None))
        .order_by(RetrievalRun.created_at.desc(), RetrievalRun.id.desc())
        .limit(sample_limit)
    ).all()
    answer_rows = session.execute(
        select(
            AnswerRun.latency_ms,
            AnswerRun.abstained,
            AnswerRun.confidence,
            AnswerRun.created_at,
        )
        .where(AnswerRun.latency_ms.is_not(None))
        .order_by(AnswerRun.created_at.desc(), AnswerRun.id.desc())
        .limit(sample_limit)
    ).all()

    retrieval_latencies = [int(row.latency_ms) for row in retrieval_rows]
    by_variant: dict[str, list[int]] = defaultdict(list)
    for row in retrieval_rows:
        by_variant[str(row.retriever_variant)].append(int(row.latency_ms))

    answer_latencies = [int(row.latency_ms) for row in answer_rows]
    confidences = [float(row.confidence) for row in answer_rows if row.confidence is not None]
    abstention_rate = (
        sum(bool(row.abstained) for row in answer_rows) / len(answer_rows)
        if answer_rows
        else None
    )

    timestamps = [_as_utc(row.created_at) for row in retrieval_rows] + [
        _as_utc(row.created_at) for row in answer_rows
    ]
    return RetrievalTelemetryResponse(
        generated_at=datetime.now(UTC),
        sample_limit=sample_limit,
        retrieval_runs_observed=len(retrieval_rows),
        answer_runs_observed=len(answer_rows),
        earliest_observed_at=min(timestamps) if timestamps else None,
        latest_observed_at=max(timestamps) if timestamps else None,
        retrieval_latency=_latency_distribution(retrieval_latencies),
        retrieval_variants=[
            RetrievalVariantTelemetry(
                retriever_variant=variant,
                latency=_latency_distribution(latencies),
            )
            for variant, latencies in sorted(by_variant.items())
        ],
        answers=AnswerTelemetry(
            latency=_latency_distribution(answer_latencies),
            abstention_rate=abstention_rate,
            mean_confidence=round(fmean(confidences), 6) if confidences else None,
        ),
    )


def _latency_distribution(values: list[int]) -> LatencyDistribution:
    if not values:
        return LatencyDistribution(
            sample_size=0,
            p50_ms=None,
            p95_ms=None,
            mean_ms=None,
            min_ms=None,
            max_ms=None,
        )
    ordered = sorted(values)
    return LatencyDistribution(
        sample_size=len(ordered),
        p50_ms=_nearest_rank(ordered, 0.50),
        p95_ms=_nearest_rank(ordered, 0.95),
        mean_ms=round(fmean(ordered), 3),
        min_ms=ordered[0],
        max_ms=ordered[-1],
    )


def _nearest_rank(ordered: list[int], percentile: float) -> int:
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
