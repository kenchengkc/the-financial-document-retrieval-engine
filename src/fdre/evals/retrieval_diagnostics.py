from __future__ import annotations

import json
import math
from collections.abc import Iterable
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
from fdre.evals.metrics import recall_at_k
from fdre.retrieval.query import RetrievalCandidate


@dataclass(frozen=True, slots=True)
class RetrievalDevelopmentDiagnostic:
    question_id: str | None
    question: str
    category: str
    answer_type: str
    expected_tickers: tuple[str, ...]
    inferred_tickers: tuple[str, ...]
    unexpected_tickers: tuple[str, ...]
    expected_sections: tuple[str, ...]
    inferred_sections: tuple[str, ...]
    unexpected_sections: tuple[str, ...]
    candidate_pool_size: int
    final_result_count: int
    candidate_recall: float | None
    final_recall: float | None
    candidate_miss: bool | None
    rerank_loss: bool | None
    stage_timings_ms: dict[str, float]
    estimated_embedding_tokens: int
    reranker_candidate_count: int


def build_retrieval_development_diagnostic(
    question: EvalQuestion,
    *,
    inferred_tickers: list[str],
    inferred_sections: list[str],
    candidate_pool: list[RetrievalCandidate],
    final_candidates: list[RetrievalCandidate],
    final_k: int,
    stage_timings_ms: dict[str, float],
    estimated_embedding_tokens: int,
    reranker_candidate_count: int,
) -> RetrievalDevelopmentDiagnostic:
    candidate_recall = _evidence_recall_at_k(
        question,
        candidate_pool,
        k=len(candidate_pool),
    )
    final_recall = _evidence_recall_at_k(
        question,
        final_candidates,
        k=final_k,
    )
    unexpected_tickers = tuple(
        sorted(set(inferred_tickers) - set(question.expected_tickers))
    )
    unexpected_sections = tuple(
        sorted(set(inferred_sections) - set(question.expected_sections))
    )
    return RetrievalDevelopmentDiagnostic(
        question_id=question.question_id,
        question=question.question,
        category=question.category,
        answer_type=question.answer_type,
        expected_tickers=tuple(question.expected_tickers),
        inferred_tickers=tuple(inferred_tickers),
        unexpected_tickers=unexpected_tickers,
        expected_sections=tuple(question.expected_sections),
        inferred_sections=tuple(inferred_sections),
        unexpected_sections=unexpected_sections,
        candidate_pool_size=len(candidate_pool),
        final_result_count=len(final_candidates),
        candidate_recall=candidate_recall,
        final_recall=final_recall,
        candidate_miss=(candidate_recall < 1.0 if candidate_recall is not None else None),
        rerank_loss=(
            candidate_recall > final_recall
            if candidate_recall is not None and final_recall is not None
            else None
        ),
        stage_timings_ms=dict(stage_timings_ms),
        estimated_embedding_tokens=estimated_embedding_tokens,
        reranker_candidate_count=reranker_candidate_count,
    )


def write_retrieval_development_diagnostics(
    output_dir: str | Path,
    diagnostics: list[RetrievalDevelopmentDiagnostic],
    *,
    benchmark_metadata: dict[str, Any],
    final_k: int,
) -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "retrieval_development_diagnostics.json"
    markdown_path = directory / "retrieval_development_diagnostics.md"
    summary = summarize_retrieval_development_diagnostics(
        diagnostics,
        final_k=final_k,
    )
    payload = {
        "schema_version": "fdre-retrieval-development-diagnostics-v1",
        "benchmark": benchmark_metadata,
        "summary": summary,
        "questions": [asdict(item) for item in diagnostics],
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    table = summary["table_questions"]
    timing = summary["stage_latency_ms"]
    lines = [
        "# Retrieval development diagnostics",
        "",
        "This report is development-only diagnostic evidence. It does not change "
        "or replace the published historical benchmark contract.",
        "",
        f"- Questions: **{summary['question_count']}**",
        f"- Answerable questions: **{summary['answerable_question_count']}**",
        f"- Unexpected ticker-scope cases: "
        f"**{summary['unexpected_ticker_scope_count']}**",
        f"- Unexpected section-scope cases: "
        f"**{summary['unexpected_section_scope_count']}**",
        f"- Candidate-pool misses: **{summary['candidate_miss_count']}**",
        f"- Candidate-to-final rerank losses at K={final_k}: "
        f"**{summary['rerank_loss_count']}**",
        f"- Mean candidate-pool recall: **{summary['mean_candidate_recall']:.3f}**",
        f"- Mean final recall@{final_k}: **{summary['mean_final_recall']:.3f}**",
        "",
        "## Table questions",
        "",
        f"- Answerable table questions: **{table['answerable_question_count']}**",
        f"- Candidate-pool misses: **{table['candidate_miss_count']}**",
        f"- Rerank losses: **{table['rerank_loss_count']}**",
        f"- Mean candidate-pool recall: **{table['mean_candidate_recall']:.3f}**",
        f"- Mean final recall@{final_k}: **{table['mean_final_recall']:.3f}**",
        "",
        "## Stage latency",
        "",
        "| Stage | p50 ms | p95 ms |",
        "| --- | ---: | ---: |",
    ]
    for stage, values in sorted(timing.items()):
        lines.append(f"| {stage} | {values['p50']:.1f} | {values['p95']:.1f} |")
    provider_usage = summary["provider_usage"]
    lines.extend(
        [
            "",
            "## Provider usage",
            "",
            f"- Embedding query calls represented: "
            f"**{provider_usage['embedding_query_calls']}**",
            f"- Estimated embedding query tokens: "
            f"**{provider_usage['estimated_embedding_tokens']}**",
            f"- Reranker calls represented: **{provider_usage['reranker_calls']}**",
            f"- Candidate documents sent to reranking: "
            f"**{provider_usage['reranker_candidate_documents']}**",
            "",
            "Query-only scope fields are compared with benchmark labels only to expose "
            "false positive scope. Empty inference is not treated as an entity-resolution "
            "error when the query never names the labeled issuer or section.",
        ]
    )
    markdown_path.write_text("\n".join(lines) + "\n")
    return json_path, markdown_path


def summarize_retrieval_development_diagnostics(
    diagnostics: list[RetrievalDevelopmentDiagnostic],
    *,
    final_k: int,
) -> dict[str, Any]:
    answerable = [item for item in diagnostics if item.candidate_recall is not None]
    table_answerable = [item for item in answerable if item.answer_type == "table"]
    timing_names = sorted(
        {name for item in diagnostics for name in item.stage_timings_ms}
    )
    return {
        "final_k": final_k,
        "question_count": len(diagnostics),
        "answerable_question_count": len(answerable),
        "unexpected_ticker_scope_count": sum(
            bool(item.unexpected_tickers) for item in diagnostics
        ),
        "unexpected_section_scope_count": sum(
            bool(item.unexpected_sections) for item in diagnostics
        ),
        "candidate_miss_count": sum(
            item.candidate_miss is True for item in answerable
        ),
        "rerank_loss_count": sum(item.rerank_loss is True for item in answerable),
        "mean_candidate_recall": _mean_optional(
            item.candidate_recall for item in answerable
        ),
        "mean_final_recall": _mean_optional(item.final_recall for item in answerable),
        "table_questions": {
            "answerable_question_count": len(table_answerable),
            "candidate_miss_count": sum(
                item.candidate_miss is True for item in table_answerable
            ),
            "rerank_loss_count": sum(
                item.rerank_loss is True for item in table_answerable
            ),
            "mean_candidate_recall": _mean_optional(
                item.candidate_recall for item in table_answerable
            ),
            "mean_final_recall": _mean_optional(
                item.final_recall for item in table_answerable
            ),
        },
        "stage_latency_ms": {
            name: _latency_summary(
                [
                    item.stage_timings_ms[name]
                    for item in diagnostics
                    if name in item.stage_timings_ms
                ]
            )
            for name in timing_names
        },
        "provider_usage": {
            "embedding_query_calls": len(diagnostics),
            "estimated_embedding_tokens": sum(
                item.estimated_embedding_tokens for item in diagnostics
            ),
            "reranker_calls": sum(
                item.reranker_candidate_count > 0 for item in diagnostics
            ),
            "reranker_candidate_documents": sum(
                item.reranker_candidate_count for item in diagnostics
            ),
        },
    }


def _evidence_recall_at_k(
    question: EvalQuestion,
    candidates: list[RetrievalCandidate],
    *,
    k: int,
) -> float | None:
    ranked, relevant = _evidence_labels(question, candidates)
    if not relevant:
        return None
    return recall_at_k(ranked, relevant, k)


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
        section_ok = not reference_section or not section or section == reference_section
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


def _mean_optional(values: Iterable[float | None]) -> float:
    materialized = [value for value in values if value is not None]
    return sum(materialized) / len(materialized) if materialized else 0.0


def _latency_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0}
    return {
        "p50": median(values),
        "p95": _percentile(values, 0.95),
    }


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, int(math.ceil(quantile * len(ordered)) - 1)),
    )
    return ordered[index]
