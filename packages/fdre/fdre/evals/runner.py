from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from fdre.evals.datasets import EvalQuestion
from fdre.evals.metrics import (
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from fdre.retrieval.query import RetrievalCandidate

RetrieverVariant = Callable[[EvalQuestion], list[RetrievalCandidate]]


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
) -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "retrieval_eval.json"
    markdown_path = directory / "retrieval_eval.md"
    json_path.write_text(
        json.dumps([asdict(metric) for metric in metrics], indent=2, sort_keys=True)
        + "\n"
    )
    lines = [
        f"| Variant | Recall@{k} | Precision@{k} | MRR | nDCG@{k} | Table Recall@{k} |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        (
            f"| {metric.variant} | {metric.recall_at_k:.3f} | "
            f"{metric.precision_at_k:.3f} | {metric.mrr:.3f} | "
            f"{metric.ndcg_at_k:.3f} | {metric.table_recall_at_k:.3f} |"
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
        return VariantMetrics(name, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)

    recalls: list[float] = []
    precisions: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    section_hits: list[float] = []
    ticker_hits: list[float] = []
    table_recalls: list[float] = []
    for question in questions:
        candidates = retrieve(question)
        ranked_ids = [candidate.chunk_id for candidate in candidates]
        relevant_ids = set(question.relevant_chunk_ids)
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

    return VariantMetrics(
        variant=name,
        recall_at_k=_mean(recalls),
        precision_at_k=_mean(precisions),
        mrr=_mean(reciprocal_ranks),
        ndcg_at_k=_mean(ndcgs),
        section_hit_rate=_mean(section_hits),
        ticker_filter_accuracy=_mean(ticker_hits),
        table_recall_at_k=_mean(table_recalls),
        question_count=len(questions),
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
