from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from statistics import mean
from typing import Any

from fdre.evals.datasets import EvalQuestion, evidence_reference_matches
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
    relevant_evidence_count: int
    reviewed_condition_count: int
    issuer_recall_at_k: dict[int, float]
    issuer_precision_at_k: dict[int, float]
    evidence_recall_at_k: dict[int, float]
    condition_grounding_correct: bool | None
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
    condition_grounding_question_count: int
    condition_grounding_accuracy: float | None
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
    return aggregate_cross_sectional_question_metrics(
        per_question,
        ks=normalized_ks,
    )


def aggregate_cross_sectional_question_metrics(
    metrics: Iterable[CrossSectionalQuestionMetrics],
    *,
    ks: tuple[int, ...],
) -> CrossSectionalMetrics:
    normalized_ks = _normalize_ks(ks)
    per_question = tuple(metrics)
    if not per_question:
        return _empty_metrics(normalized_ks)

    ranked_questions = [metric for metric in per_question if metric.expected_tickers]
    evidence_questions = [
        metric for metric in per_question if metric.relevant_evidence_count > 0
    ]
    condition_results = [
        metric.condition_grounding_correct
        for metric in per_question
        if metric.condition_grounding_correct is not None
    ]
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
            k: (
                mean(metric.issuer_recall_at_k[k] for metric in ranked_questions)
                if ranked_questions
                else 0.0
            )
            for k in normalized_ks
        },
        issuer_precision_at_k={
            k: (
                mean(metric.issuer_precision_at_k[k] for metric in ranked_questions)
                if ranked_questions
                else 0.0
            )
            for k in normalized_ks
        },
        evidence_recall_at_k={
            k: (
                mean(metric.evidence_recall_at_k[k] for metric in evidence_questions)
                if evidence_questions
                else 0.0
            )
            for k in normalized_ks
        },
        condition_grounding_question_count=len(condition_results),
        condition_grounding_accuracy=(
            mean(float(value) for value in condition_results)
            if condition_results
            else None
        ),
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
        row.ticker for row in response.rows for _candidate in row.evidence
    ]
    expected_conditions = _expected_conditions(question)
    zero_result_correct = None if expected else not returned
    return CrossSectionalQuestionMetrics(
        question_id=question.question_id or "",
        task_type=question.resolved_task_type,
        expected_tickers=expected,
        returned_tickers=returned,
        missed_tickers=tuple(sorted(expected_set - returned_set)),
        false_positive_tickers=tuple(
            ticker for ticker in returned if ticker not in expected_set
        ),
        relevant_evidence_count=len(question.relevant_evidence),
        reviewed_condition_count=len(expected_conditions),
        issuer_recall_at_k={
            k: issuer_recall_at_k(returned, expected_set, k) for k in ks
        },
        issuer_precision_at_k={
            k: issuer_precision_at_k(returned, expected_set, k) for k in ks
        },
        evidence_recall_at_k={
            k: _evidence_recall_at_k(question, response, k) for k in ks
        },
        condition_grounding_correct=_condition_grounding_correct(
            question,
            response,
            expected_conditions=expected_conditions,
        ),
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
            candidate_section = candidate.metadata.get("section")
            section = str(candidate_section) if candidate_section is not None else None
            for index, reference in enumerate(question.relevant_evidence):
                if (
                    reference.ticker is not None
                    and _normalize_ticker(reference.ticker)
                    != _normalize_ticker(row.ticker)
                ):
                    continue
                if evidence_reference_matches(
                    reference,
                    accession_number=row.accession_number,
                    section=section,
                    text=candidate.text,
                ):
                    matched.add(index)
    return len(matched) / len(question.relevant_evidence)


def _expected_conditions(question: EvalQuestion) -> list[dict[str, Any]]:
    payload = question.metadata.get("expected_conditions")
    if not isinstance(payload, list):
        return []
    return [record for record in payload if isinstance(record, dict)]


def _condition_grounding_correct(
    question: EvalQuestion,
    response: ResearchScreenResponse,
    *,
    expected_conditions: list[dict[str, Any]],
) -> bool | None:
    if not expected_conditions:
        return None
    if len(question.expected_tickers) != 1:
        return False

    expected_ticker = _normalize_ticker(question.expected_tickers[0])
    gold_rows = [
        row for row in response.rows if _normalize_ticker(row.ticker) == expected_ticker
    ]
    if len(gold_rows) != 1:
        return False
    row = gold_rows[0]

    selected_accession = question.metadata.get("selected_accession")
    if isinstance(selected_accession, str) and row.accession_number != selected_accession:
        return False
    selected_prior_accession = question.metadata.get("selected_prior_accession")
    if (
        selected_prior_accession is not None
        and row.prior_accession_number != selected_prior_accession
    ):
        return False

    for expected in expected_conditions:
        matches = [
            condition
            for condition in row.conditions
            if condition.metric == expected.get("metric")
            and condition.operator == expected.get("operator")
            and condition.change_from_prior
            is bool(expected.get("change_from_prior", False))
            and _float_matches(condition.threshold, expected.get("threshold"))
        ]
        if len(matches) != 1:
            return False
        condition = matches[0]
        if condition.feature != expected.get("feature"):
            return False
        if condition.passed is not bool(expected.get("passed")):
            return False
        if not _optional_float_matches(
            condition.current_value,
            expected.get("current_value"),
        ):
            return False
        if not _optional_float_matches(
            condition.prior_value,
            expected.get("prior_value"),
        ):
            return False
        if not _optional_float_matches(
            condition.observed_value,
            expected.get("observed_value"),
        ):
            return False
        if condition.current_lineage_id != expected.get("current_lineage_id"):
            return False
        if condition.prior_lineage_id != expected.get("prior_lineage_id"):
            return False
        if condition.source_accessions != expected.get("source_accessions"):
            return False
    return True


def _float_matches(actual: float, expected: Any) -> bool:
    if isinstance(expected, bool) or not isinstance(expected, (int, float)):
        return False
    return math.isclose(actual, float(expected), rel_tol=1e-9, abs_tol=1e-12)


def _optional_float_matches(actual: float | None, expected: Any) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    return _float_matches(actual, expected)


def _has_pit_leakage(response: ResearchScreenResponse) -> bool:
    as_of = response.plan.as_of
    manifest_time = response.manifest.max_information_timestamp
    if manifest_time is not None and manifest_time > as_of:
        return True
    return any(
        row.available_at > as_of or row.max_source_available_at > as_of
        for row in response.rows
    )


def _empty_metrics(ks: tuple[int, ...]) -> CrossSectionalMetrics:
    return CrossSectionalMetrics(
        question_count=0,
        ks=ks,
        issuer_recall_at_k=dict.fromkeys(ks, 0.0),
        issuer_precision_at_k=dict.fromkeys(ks, 0.0),
        evidence_recall_at_k=dict.fromkeys(ks, 0.0),
        condition_grounding_question_count=0,
        condition_grounding_accuracy=None,
        mean_max_issuer_evidence_share=0.0,
        pit_leakage_rate=0.0,
        zero_result_accuracy=None,
        latency_p50_ms=0.0,
        latency_p95_ms=0.0,
        mean_semantic_search_calls=0.0,
        max_semantic_search_calls=0,
        per_question=(),
    )


def _normalize_ks(ks: tuple[int, ...]) -> tuple[int, ...]:
    if not ks:
        raise ValueError("ks must not be empty")
    if any(k <= 0 for k in ks):
        raise ValueError("ks must contain positive integers")
    return tuple(sorted(set(ks)))


def _unique_tickers(tickers: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(_normalize_ticker(ticker) for ticker in tickers))


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
