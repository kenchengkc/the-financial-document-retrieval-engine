from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdre.evals.datasets import EvalQuestion, load_jsonl_dataset, write_jsonl_dataset
from fdre.evals.metrics import (
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from fdre.evals.runner import evaluate_variants, write_eval_report
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
            relevant_chunk_ids=[2],
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
                },
                hybrid_score=1.0,
                rank=1,
            )
        ]

    metrics = evaluate_variants(loaded, {"Hybrid": retrieve}, k=5)
    json_path, markdown_path = write_eval_report(tmp_path, metrics, k=5)

    assert metrics[0].recall_at_k == 1.0
    assert metrics[0].table_recall_at_k == 1.0
    assert json.loads(json_path.read_text())[0]["variant"] == "Hybrid"
    assert "| Hybrid | 1.000" in markdown_path.read_text()
