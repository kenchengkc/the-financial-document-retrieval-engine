from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean

from fdre.evals.datasets import EvalQuestion, evidence_fingerprint
from fdre.evals.metrics import (
    issuer_precision_at_k,
    issuer_recall_at_k,
    max_issuer_evidence_share,
)
from fdre.research.screen import ResearchScreenResponse


@dataclass(frozen=True, slots=True)
class CrossSectionalOutcome:
    question: EvalQuestion
    response: ResearchScreenResponse


@dataclass(frozen=True, slots=True)
class CrossSectionalQuestionMetrics:
    question_id: str
    task_type: str
    expected_tickers: tuple[str, ...]
    returned_tickers: tuple[str, ...]
    missed_tickers: tuple[str, ...]
    false_positive_tickers: tuple[str, ...]
    issuer_recall_at_k: dict[int, float]
    issuer_precision_at_k: dict[int, float]
    evidence_recall_at_k: dict[int, float]
    max_issuer_evidence_share: float
    pit_leakage: bool
    zero_result_correct: bool | None
    latency_ms: int
    semantic_search_calls: int


@dataclass(frozen=True, slots=True)
class CrossSectionalMetrics:
    question_count: int
    ks: tuple[int, ...]
    issuer_recall_at_k: dict[int, float]
    issuer_precision_at_k: dict[int, float]
    evidence_recall_at_k: dict[int, float]
    mean_max_issuer_evidence_share: float
    pit_leakage_rate: float
    zero_result_accuracy: float | None
    latency_p50_ms: float
    latency_p95_ms: float
    mean_semantic_search_calls: float
    max_semantic_search_calls: int
    per_question: tuple[CrossSectionalQuestionMetrics, ...]


def evaluate_cross_sectional_outcomes(
    outcomes: list[CrossSectionalOutcome],
    *,
    ks: tuple[int, ...] = (5, 10, 20),
) -> CrossSectionalMetrics:
    normalized_ks = _normalize_ks(ks)
    per_question = tuple(
        _evaluate_question(outcome, ks=normalized_ks) for outcome in outcomes
    )
    if not per_question:
        return CrossSectionalMetrics(
            question_count=0,
            ks=normalized_ks,
            issuer_recall_at_k={k: 0.0 for k in normalized_ks},
            issuer_precision_at_k={k: 0.0 for k in normalized_ks},
            evidence_recall_at_k={k: 0.0 for k in normalized_ks},
            mean_max_issuer_evidence_share=0.0,
            pit_leakage_rate=0.0,
            zero_result_accuracy=None,
            latency_p50_ms=0.0,
            latency_p95_ms=0.0,
            mean_semantic_search_calls=0.0,
            max_semantic_search_calls=0,
            per_question=(),
        )

    zero_results = [
        metric.zero_result_correct
        for metric in per_question
        if metric.zero_result_correct is not None
    ]
    latencies = [float(metric.latency_ms) for metric in per_question]
    semantic_calls = [metric.semantic_search_calls for metric in per_question]
    return CrossSectionalMetrics(
        question_count=len(per_question),
        ks=normalized_ks,
        issuer_recall_at_k={
            k: mean(metric.issuer_recall_at_k[k] for metric in per_question)
            for k in normalized_ks
        },
        issuer_precision_at_k={
            k: mean(metric.issuer_precision_at_k[k] for metric in per_question)
            for k in normalized_ks
        },
        evidence_recall_at_k={
            k: mean(metric.evidence_recall_at_k[k] for metric in per_question)
            for k in normalized_ks
        },
        mean_max_issuer_evidence_share=mean(
            metric.max_issuer_evidence_share for metric in per_question
        ),
        pit_leakage_rate=mean(float(metric.pit_leakage) for metric in per_question),
        zero_result_accuracy=(
            mean(float(value) for value in zero_results) if zero_results else None
        ),
        latency_p50_ms=_percentile(latencies, 50),
        latency_p95_ms=_percentile(latencies, 95),
        mean_semantic_search_calls=mean(semantic_calls),
        max_semantic_search_calls=max(semantic_calls),
        per_question=per_question,
    )


def _evaluate_question(
    outcome: CrossSectionalOutcome,
    *,
    ks: tuple[int, ...],
) -> CrossSectionalQuestionMetrics:
    question = outcome.question
    response = outcome.response
    expected = tuple(_unique_tickers(question.expected_tickers))
    returned = tuple(_unique_tickers(row.ticker for row in response.rows))
    expected_set = set(expected)
    returned_set = set(returned)
    evidence_tickers = [
        row.ticker
        for row in response.rows
        for _candidate in row.evidence
    ]
    zero_result_correct = None
    if not expected:
        zero_result_correct = not returned
    return CrossSectionalQuestionMetrics(
        question_id=question.question_id or "",
        task_type=question.resolved_task_type,
        expected_tickers=expected,
        returned_tickers=returned,
        missed_tickers=tuple(sorted(expected_set - returned_set)),
        false_positive_tickers=tuple(
            ticker for ticker in returned if ticker not in expected_set
        ),
        issuer_recall_at_k={
            k: issuer_recall_at_k(returned, expected_set, k) for k in ks
        },
        issuer_precision_at_k={
            k: issuer_precision_at_k(returned, expected_set, k) for k in ks
        },
        evidence_recall_at_k={
            k: _evidence_recall_at_k(question, response, k) for k in ks
        },
        max_issuer_evidence_share=max_issuer_evidence_share(evidence_tickers),
        pit_leakage=_has_pit_leakage(response),
        zero_result_correct=zero_result_correct,
        latency_ms=response.latency_ms,
        semantic_search_calls=response.manifest.semantic_search_calls,
    )


def _evidence_recall_at_k(
    question: EvalQuestion,
    response: ResearchScreenResponse,
    k: int,
) -> float:
    if not question.relevant_evidence:
        return 0.0
    matched: set[int] = set()
    for row in response.rows[:k]:
        for candidate in row.evidence:
            fingerprint = evidence_fingerprint(candidate.text)
            for index, reference in enumerate(question.relevant_evidence):
                if reference.accession_number != row.accession_number:
                    continue
                if reference.ticker is not None and _normalize_ticker(reference.ticker) != _normalize_ticker(row.ticker):
                    continue
                if reference.content_fingerprint == fingerprint:
                    matched.add(index)
    return len(matched) / len(question.relevant_evidence)


def _has_pit_leakage(response: ResearchScreenResponse) -> bool:
    as_of = response.plan.as_of
    manifest_time = response.manifest.max_information_timestamp
    if manifest_time is not None and manifest_time > as_of:
        return True
    return any(
        row.available_at > as_of or row.max_source_available_at > as_of
        for row in response.rows
    )


def _normalize_ks(ks: tuple[int, ...]) -> tuple[int, ...]:
    if not ks:
        raise ValueError("ks must not be empty")
    if any(k <= 0 for k in ks):
        raise ValueError("ks must contain positive integers")
    return tuple(sorted(set(ks)))


def _unique_tickers(tickers: object) -> list[str]:
    return list(
        dict.fromkeys(
            _normalize_ticker(ticker)
            for ticker in tickers  # type: ignore[union-attr]
        )
    )


def _normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
