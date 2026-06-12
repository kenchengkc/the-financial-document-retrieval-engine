from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdre.evals.datasets import (
    EvalQuestion,
    EvidenceReference,
    evidence_fingerprint,
    load_jsonl_dataset,
    normalize_evidence_text,
    validate_reviewed_benchmark,
    write_jsonl_dataset,
)
from fdre.evals.metrics import (
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from fdre.evals.runner import EvaluationOutcome, evaluate_variants, write_eval_report
from fdre.retrieval.query import RetrievalCandidate


def test_retrieval_metrics() -> None:
    ranked = [3, 1, 2, 4]
    relevant = {1, 2}
    assert recall_at_k(ranked, relevant, 3) == 1.0
    assert precision_at_k(ranked, relevant, 2) == 0.5
    assert reciprocal_rank(ranked, relevant) == 0.5
    assert ndcg_at_k(ranked, relevant, 3) == pytest.approx(0.6934, rel=1e-3)


def test_dataset_and_eval_reports_round_trip(tmp_path: Path) -> None:
    dataset_path = tmp_path / "eval.jsonl"
    questions = [
        EvalQuestion(
            question="Find revenue table",
            expected_tickers=["NVDA"],
            expected_sections=["Financial Statements"],
            relevant_evidence=[
                EvidenceReference.from_quote(
                    accession_number="0001045810-26-000001",
                    section="Financial Statements",
                    quote="Revenue table",
                    ticker="NVDA",
                )
            ],
            answer_type="table",
        )
    ]
    write_jsonl_dataset(dataset_path, questions)
    loaded = load_jsonl_dataset(dataset_path)

    def retrieve(_question: EvalQuestion) -> list[RetrievalCandidate]:
        return [
            RetrievalCandidate(
                chunk_id=2,
                text="Revenue table",
                metadata={
                    "ticker": "NVDA",
                    "section": "Financial Statements",
                    "accession_number": "0001045810-26-000001",
                },
                hybrid_score=1.0,
                rank=1,
            )
        ]

    metrics = evaluate_variants(loaded, {"Hybrid": retrieve}, k=5)
    json_path, markdown_path = write_eval_report(tmp_path, metrics, k=5)

    assert metrics[0].recall_at_k == 1.0
    assert metrics[0].table_recall_at_k == 1.0
    assert json.loads(json_path.read_text())["metrics"][0]["variant"] == "Hybrid"
    assert "| Hybrid | 1.000" in markdown_path.read_text()


def test_stable_evidence_reference_normalizes_and_validates() -> None:
    reference = EvidenceReference.from_quote(
        accession_number="0000320193-25-000079",
        section="Risk Factors",
        quote="  Supply\nconstraints MAY affect operations. ",
        ticker="AAPL",
    )

    assert reference.normalized_quote == "supply constraints may affect operations."
    assert reference.content_fingerprint == evidence_fingerprint(
        "Supply constraints may affect operations."
    )
    assert normalize_evidence_text("  A\n B  ") == "a b"


def test_eval_records_latency_abstention_entity_and_cost() -> None:
    question = EvalQuestion(
        question="What did Apple disclose?",
        expected_tickers=["AAPL"],
        relevant_chunk_ids=[2],
    )

    metrics = evaluate_variants(
        [question],
        {
            "Hybrid": lambda _question: EvaluationOutcome(
                candidates=[
                    RetrievalCandidate(
                        chunk_id=2,
                        text="Apple disclosed supply risk.",
                        metadata={"ticker": "AAPL"},
                    )
                ],
                latency_ms=12.5,
                provider_cost_usd=0.00001,
                inferred_tickers=("AAPL",),
            )
        },
        k=10,
    )[0]

    assert metrics.recall_at_k == 1.0
    assert metrics.entity_resolution_accuracy == 1.0
    assert metrics.latency_p95_ms == 12.5
    assert metrics.average_provider_cost_usd == 0.00001


def test_reviewed_benchmark_contract_rejects_incomplete_dataset() -> None:
    with pytest.raises(ValueError, match="expected 120 questions"):
        validate_reviewed_benchmark(
            [
                EvalQuestion(
                    question="Incomplete benchmark",
                    should_abstain=True,
                    metadata={"reviewed_by": "reviewer"},
                )
            ]
        )
