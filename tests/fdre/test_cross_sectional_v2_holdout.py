from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from scripts.evaluate_cross_sectional import require_sealed_holdout_optin

from fdre.evals.datasets import (
    compute_dataset_sha256,
    load_cross_sectional_benchmark,
    validate_benchmark,
    validate_cross_sectional_condition_grounding,
    validate_cross_sectional_evidence_grounding,
)
from fdre.research.screen import ResearchScreenPlan

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = REPO_ROOT / "data/evals"
DEVELOPMENT = EVAL_DIR / "cross_sectional_benchmark.v2.development.jsonl"
HOLDOUT = EVAL_DIR / "cross_sectional_benchmark.v2.holdout.jsonl"
MANIFEST = EVAL_DIR / "cross_sectional_benchmark.v2.holdout.manifest.json"
RESULTS_DIR = EVAL_DIR / "results/cross-sectional-v2-holdout-first-run"
RESULT_JSON = RESULTS_DIR / "cross_sectional_eval.json"
RESULT_MARKDOWN = RESULTS_DIR / "cross_sectional_eval.md"
RESULT_PER_QUERY = RESULTS_DIR / "cross_sectional_per_query.jsonl"
EXPECTED_TASK_COUNTS = {
    "change_screen": 2,
    "semantic_screen": 5,
    "semantic_structured_screen": 3,
    "structured_screen": 3,
    "temporal_screen": 1,
}
EXPECTED_RESULT_SHA256 = {
    "cross_sectional_eval.json": "4c0073317f8b0d084c96a17fd99f8865d34fc4c7c0bec93b5567e48f8ff12b32",
    "cross_sectional_eval.md": "42b5a92b96c7064a015a73974d2eb0a3de2b27e1894a67ae73484ba4603e8c9c",
    "cross_sectional_per_query.jsonl": "99239b661a6d735609684e539df9bec27bf4fedc80643b884750b65aee779775",
}
FORBIDDEN_EXECUTION_KEYS = {
    "condition_grounding_correct",
    "evaluation_metrics",
    "evidence_recall_at_k",
    "false_positive_tickers",
    "issuer_recall_at_k",
    "latency_ms",
    "missed_tickers",
    "retrieval_results",
    "returned_tickers",
    "screen_response",
    "semantic_score",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _nested_keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in _nested_keys(child)}
    return set()


def test_v2_holdout_is_sealed_grounded_and_disjoint() -> None:
    holdout = load_cross_sectional_benchmark(HOLDOUT)
    development = load_cross_sectional_benchmark(DEVELOPMENT)

    validate_benchmark(
        holdout,
        expected_count=14,
        expected_splits={"holdout": 14},
        required_categories={"cross_sectional"},
    )
    validate_cross_sectional_evidence_grounding(holdout)
    validate_cross_sectional_condition_grounding(holdout)
    assert Counter(q.resolved_task_type for q in holdout) == EXPECTED_TASK_COUNTS
    assert [q.question_id for q in holdout] == [f"holdout-xs-{i:03d}" for i in range(1, 15)]

    development_ids = {q.question_id for q in development}
    holdout_ids = {q.question_id for q in holdout}
    assert development_ids.isdisjoint(holdout_ids)
    development_gold = {ticker for q in development for ticker in q.expected_tickers}
    holdout_gold = {ticker for q in holdout for ticker in q.expected_tickers}
    assert development_gold.isdisjoint(holdout_gold)

    for question in holdout:
        assert question.metadata["review_method"] == "raw_pit_panel_and_selected_filing_review"
        assert question.metadata["reviewed_by"] == "fdre-assisted-holdout-review-2026-08"
        assert "source_question_ids" not in question.metadata
        plan_payload = question.metadata["screen_plan"]
        plan = ResearchScreenPlan.model_validate({"as_of": question.as_of, **plan_payload})
        assert len(plan.tickers) == 5
        assert len(set(plan.tickers)) == 5
        assert question.expected_tickers[0] in plan.tickers
        assert not (FORBIDDEN_EXECUTION_KEYS & _nested_keys(question.metadata))


def test_v2_holdout_manifest_pins_seal_and_first_run() -> None:
    manifest = json.loads(MANIFEST.read_text())
    holdout = load_cross_sectional_benchmark(HOLDOUT)
    development = load_cross_sectional_benchmark(DEVELOPMENT)

    assert manifest["benchmark_name"] == "FDRE Cross-Sectional v2 Holdout"
    assert manifest["benchmark_version"] == "v2"
    assert manifest["split"] == "holdout"
    assert manifest["status"] == "sealed"
    assert manifest["evaluation_status"] == "first_run_frozen"
    assert manifest["first_evaluation_part"] == "7.5"
    assert manifest["first_evaluated_at"] == "2026-08-26T06:01:59.086448+00:00"
    assert manifest["first_evaluation_git_sha"] == "ee80bae16d5f4d605db7ed15770c5158e79324bc"
    assert manifest["first_evaluation_workflow_run_id"] == 32936267811
    assert manifest["first_evaluation_artifact_id"] == 9594972775
    assert manifest["first_evaluation_artifact_sha256"] == (
        "3c7977a9883ef73e90c9a8cbd13a033f3fff6cc698db5f1dcaad2c81de5ae701"
    )
    assert manifest["first_evaluation_corpus_snapshot_id"] == "388fe80d07d5bd6e"
    assert manifest["first_evaluation_results_dir"] == str(RESULTS_DIR.relative_to(REPO_ROOT))
    assert manifest["first_evaluation_result_sha256"] == EXPECTED_RESULT_SHA256
    assert manifest["question_count"] == 14
    assert manifest["task_type_counts"] == EXPECTED_TASK_COUNTS
    assert manifest["dataset_path"] == str(HOLDOUT.relative_to(REPO_ROOT))
    assert manifest["dataset_sha256"] == compute_dataset_sha256(holdout)
    assert manifest["file_sha256"] == _sha256(HOLDOUT)
    assert manifest["development_dataset_path"] == str(DEVELOPMENT.relative_to(REPO_ROOT))
    assert manifest["development_dataset_sha256"] == compute_dataset_sha256(development)
    assert manifest["development_gold_ticker_overlap"] == []
    assert manifest["construction_constraints"] == {
        "embedding_calls": 0,
        "reranker_calls": 0,
        "retrieval_execution": False,
        "screen_execution": False,
    }


def test_v2_holdout_first_run_artifacts_are_immutable_and_consistent() -> None:
    paths = {
        "cross_sectional_eval.json": RESULT_JSON,
        "cross_sectional_eval.md": RESULT_MARKDOWN,
        "cross_sectional_per_query.jsonl": RESULT_PER_QUERY,
    }
    assert {name: _sha256(path) for name, path in paths.items()} == EXPECTED_RESULT_SHA256

    result = json.loads(RESULT_JSON.read_text())
    metadata = result["metadata"]
    overall = result["overall"]
    assert metadata["dataset_sha256"] == "9bb4736ab5e7373be6edcdac05ac781398b3a77f00b0d2dfdd5be6187d9deccc"
    assert metadata["hydrated_dataset_sha256"] == metadata["dataset_sha256"]
    assert metadata["evaluated_subset_sha256"] == metadata["dataset_sha256"]
    assert metadata["generated_at"] == "2026-08-26T06:01:59.086448+00:00"
    assert metadata["git_sha"] == "ee80bae16d5f4d605db7ed15770c5158e79324bc"
    assert metadata["corpus_snapshot_id"] == "388fe80d07d5bd6e"
    assert metadata["document_count"] == 3204
    assert metadata["chunk_count"] == 3039403
    assert metadata["embedding_count"] == 3039403
    assert metadata["embedding_provider"] == "voyage"
    assert metadata["embedding_model"] == "voyage-4-large"
    assert metadata["embedding_dimensions"] == 512
    assert metadata["reranker_provider"] == "none"
    assert metadata["screen_retrieval_path"] == "hybrid+none"
    assert metadata["question_count"] == 14
    assert metadata["task_type_counts"] == EXPECTED_TASK_COUNTS

    assert overall["question_count"] == 14
    assert overall["issuer_recall_at_k"] == {"1": 1.0, "3": 1.0, "5": 1.0}
    assert overall["evidence_recall_at_k"] == {
        "1": 0.7777777777777778,
        "3": 0.7777777777777778,
        "5": 0.7777777777777778,
    }
    assert overall["condition_grounding_question_count"] == 8
    assert overall["condition_grounding_accuracy"] == 0.0
    assert overall["pit_leakage_rate"] == 0.0
    assert overall["latency_p50_ms"] == 3154.5
    assert overall["latency_p95_ms"] == 6145.099999999999
    assert overall["max_semantic_search_calls"] == 1

    per_query = [json.loads(line) for line in RESULT_PER_QUERY.read_text().splitlines()]
    assert [record["question_id"] for record in per_query] == [
        f"holdout-xs-{i:03d}" for i in range(1, 15)
    ]
    assert all(record["returned_tickers"][0] == record["expected_tickers"][0] for record in per_query)
    assert not any(record["pit_leakage"] for record in per_query)
    assert {
        record["question_id"]
        for record in per_query
        if record["relevant_evidence_count"] and record["evidence_recall_at_k"]["1"] == 0.0
    } == {"holdout-xs-005", "holdout-xs-012"}
    assert sum(record["condition_grounding_correct"] is False for record in per_query) == 8


def test_v2_holdout_requires_explicit_optin_after_first_run() -> None:
    with pytest.raises(ValueError, match="sealed holdout"):
        require_sealed_holdout_optin(str(HOLDOUT), allow=False)
    require_sealed_holdout_optin(str(HOLDOUT), allow=True)
