from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any

from fdre.evals.datasets import (
    EvalQuestion,
    EvidenceReference,
    evidence_fingerprint,
    normalize_evidence_text,
)
from fdre.evals.metrics import (
    binary_precision_recall_f1,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from fdre.retrieval.query import RetrievalCandidate


@dataclass(frozen=True, slots=True)
class EvaluationOutcome:
    candidates: list[RetrievalCandidate]
    latency_ms: float = 0.0
    provider_cost_usd: float = 0.0
    abstained: bool = False
    citations: tuple[EvidenceReference, ...] = ()
    inferred_tickers: tuple[str, ...] = ()


RetrieverVariant = Callable[
    [EvalQuestion],
    list[RetrievalCandidate] | EvaluationOutcome,
]


@dataclass(frozen=True, slots=True)
class VariantMetrics:
    variant: str
    recall_at_k: float
    precision_at_k: float
    mrr: float
    ndcg_at_k: float
    section_hit_rate: float
    ticker_filter_accuracy: float
    table_recall_at_k: float
    citation_precision: float
    abstention_precision: float
    abstention_recall: float
    abstention_macro_f1: float
    entity_resolution_accuracy: float
    latency_p50_ms: float
    latency_p95_ms: float
    average_provider_cost_usd: float
    question_count: int


def evaluate_variants(
    questions: list[EvalQuestion],
    variants: dict[str, RetrieverVariant],
    *,
    k: int = 5,
) -> list[VariantMetrics]:
    return [
        _evaluate_variant(name, questions, retrieve, k=k)
        for name, retrieve in variants.items()
    ]


def write_eval_report(
    output_dir: str | Path,
    metrics: list[VariantMetrics],
    *,
    k: int,
    benchmark_metadata: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "retrieval_eval.json"
    markdown_path = directory / "retrieval_eval.md"
    payload = {
        "benchmark": benchmark_metadata or {},
        "metrics": [asdict(metric) for metric in metrics],
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    lines = [
        f"| Variant | Recall@{k} | MRR | nDCG@{k} | Table Recall@{k} | "
        "Citation precision | Abstention F1 | Entity accuracy | p95 ms | Cost/query |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        (
            f"| {metric.variant} | {metric.recall_at_k:.3f} | "
            f"{metric.mrr:.3f} | {metric.ndcg_at_k:.3f} | "
            f"{metric.table_recall_at_k:.3f} | {metric.citation_precision:.3f} | "
            f"{metric.abstention_macro_f1:.3f} | "
            f"{metric.entity_resolution_accuracy:.3f} | "
            f"{metric.latency_p95_ms:.1f} | ${metric.average_provider_cost_usd:.6f} |"
        )
        for metric in metrics
    )
    markdown_path.write_text("\n".join(lines) + "\n")
    return json_path, markdown_path


def _evaluate_variant(
    name: str,
    questions: list[EvalQuestion],
    retrieve: RetrieverVariant,
    *,
    k: int,
) -> VariantMetrics:
    if not questions:
        return VariantMetrics(
            name,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0,
        )

    recalls: list[float] = []
    precisions: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    section_hits: list[float] = []
    ticker_hits: list[float] = []
    table_recalls: list[float] = []
    citation_precisions: list[float] = []
    abstention_expected: list[bool] = []
    abstention_predicted: list[bool] = []
    entity_hits: list[float] = []
    latencies: list[float] = []
    provider_costs: list[float] = []
    for question in questions:
        retrieved = retrieve(question)
        outcome = (
            retrieved
            if isinstance(retrieved, EvaluationOutcome)
            else EvaluationOutcome(candidates=retrieved)
        )
        candidates = outcome.candidates
        ranked_ids, relevant_ids = _evidence_labels(question, candidates)
        recalls.append(recall_at_k(ranked_ids, relevant_ids, k))
        precisions.append(precision_at_k(ranked_ids, relevant_ids, k))
        reciprocal_ranks.append(reciprocal_rank(ranked_ids, relevant_ids))
        ndcgs.append(ndcg_at_k(ranked_ids, relevant_ids, k))
        returned_sections = {
            str(candidate.metadata.get("section"))
            for candidate in candidates[:k]
            if candidate.metadata.get("section")
        }
        returned_tickers = {
            str(candidate.metadata.get("ticker"))
            for candidate in candidates[:k]
            if candidate.metadata.get("ticker")
        }
        section_hits.append(
            float(
                not question.expected_sections
                or bool(returned_sections & set(question.expected_sections))
            )
        )
        ticker_hits.append(
            float(
                not question.expected_tickers
                or bool(returned_tickers & set(question.expected_tickers))
            )
        )
        if question.answer_type == "table":
            table_recalls.append(recall_at_k(ranked_ids, relevant_ids, k))
        expected_citations = {
            _reference_label(reference) for reference in question.relevant_evidence
        }
        returned_citations = {_reference_label(reference) for reference in outcome.citations}
        if returned_citations:
            citation_precisions.append(
                len(returned_citations & expected_citations) / len(returned_citations)
            )
        elif question.should_abstain:
            citation_precisions.append(1.0)
        else:
            citation_precisions.append(0.0)
        abstention_expected.append(question.should_abstain)
        abstention_predicted.append(outcome.abstained)
        entity_hits.append(
            float(set(outcome.inferred_tickers) == set(question.expected_tickers))
        )
        latencies.append(outcome.latency_ms)
        provider_costs.append(outcome.provider_cost_usd)

    abstention_precision, abstention_recall, abstention_f1 = binary_precision_recall_f1(
        abstention_expected,
        abstention_predicted,
    )

    return VariantMetrics(
        variant=name,
        recall_at_k=_mean(recalls),
        precision_at_k=_mean(precisions),
        mrr=_mean(reciprocal_ranks),
        ndcg_at_k=_mean(ndcgs),
        section_hit_rate=_mean(section_hits),
        ticker_filter_accuracy=_mean(ticker_hits),
        table_recall_at_k=_mean(table_recalls),
        citation_precision=_mean(citation_precisions),
        abstention_precision=abstention_precision,
        abstention_recall=abstention_recall,
        abstention_macro_f1=abstention_f1,
        entity_resolution_accuracy=_mean(entity_hits),
        latency_p50_ms=median(latencies),
        latency_p95_ms=_percentile(latencies, 0.95),
        average_provider_cost_usd=_mean(provider_costs),
        question_count=len(questions),
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _evidence_labels(
    question: EvalQuestion,
    candidates: list[RetrievalCandidate],
) -> tuple[list[str | int], set[str | int]]:
    if not question.relevant_evidence:
        return (
            [candidate.chunk_id for candidate in candidates],
            set(question.relevant_chunk_ids),
        )
    ranked: list[str | int] = [
        _candidate_reference_label(candidate, question.relevant_evidence)
        for candidate in candidates
    ]
    return ranked, {_reference_label(reference) for reference in question.relevant_evidence}


def _candidate_reference_label(
    candidate: RetrievalCandidate,
    relevant: list[EvidenceReference],
) -> str:
    accession = str(candidate.metadata.get("accession_number") or "")
    section = normalize_evidence_text(str(candidate.metadata.get("section") or ""))
    candidate_text = normalize_evidence_text(candidate.text)
    for reference in relevant:
        reference_section = normalize_evidence_text(reference.section or "")
        # Allow either side to omit section so quote-grounded labels still match
        # when parser section metadata is missing or inconsistent.
        section_ok = (
            not reference_section
            or not section
            or section == reference_section
        )
        if (
            accession == reference.accession_number
            and section_ok
            and reference.normalized_quote in candidate_text
        ):
            return _reference_label(reference)
    return f"unmatched:{candidate.chunk_id}:{evidence_fingerprint(candidate_text)}"


def _reference_label(reference: EvidenceReference) -> str:
    return (
        f"{reference.accession_number}:"
        f"{normalize_evidence_text(reference.section or '')}:"
        f"{reference.content_fingerprint}"
    )


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(math.ceil(quantile * len(ordered)) - 1)))
    return ordered[index]
