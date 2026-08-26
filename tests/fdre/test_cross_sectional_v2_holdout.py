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
EXPECTED_TASK_COUNTS = {
    "change_screen": 2,
    "semantic_screen": 5,
    "semantic_structured_screen": 3,
    "structured_screen": 3,
    "temporal_screen": 1,
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


def test_v2_holdout_manifest_pins_seal_and_content() -> None:
    manifest = json.loads(MANIFEST.read_text())
    holdout = load_cross_sectional_benchmark(HOLDOUT)
    development = load_cross_sectional_benchmark(DEVELOPMENT)

    assert manifest["benchmark_name"] == "FDRE Cross-Sectional v2 Holdout"
    assert manifest["benchmark_version"] == "v2"
    assert manifest["split"] == "holdout"
    assert manifest["status"] == "sealed"
    assert manifest["evaluation_status"] == "never_run"
    assert manifest["first_evaluation_part"] == "7.5"
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


def test_v2_holdout_requires_explicit_first_run_optin() -> None:
    with pytest.raises(ValueError, match="sealed holdout"):
        require_sealed_holdout_optin(str(HOLDOUT), allow=False)
    require_sealed_holdout_optin(str(HOLDOUT), allow=True)
