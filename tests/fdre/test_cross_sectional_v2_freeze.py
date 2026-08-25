from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from fdre.evals.datasets import (
    compute_dataset_sha256,
    load_cross_sectional_benchmark,
    validate_benchmark,
    validate_cross_sectional_condition_grounding,
    validate_cross_sectional_evidence_grounding,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO_ROOT / "data/evals"
SEED = EVAL_DIR / "cross_sectional_benchmark.v2.dev.jsonl"
CONDITIONS = EVAL_DIR / "cross_sectional_benchmark.v2.conditions.dev.jsonl"
FROZEN = EVAL_DIR / "cross_sectional_benchmark.v2.development.jsonl"
MANIFEST = EVAL_DIR / "cross_sectional_benchmark.v2.development.manifest.json"
EXPECTED_TASK_COUNTS = {
    "change_screen": 5,
    "semantic_screen": 10,
    "semantic_structured_screen": 5,
    "structured_screen": 5,
    "temporal_screen": 3,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_v2_development_benchmark_matches_reviewed_components() -> None:
    seed = load_cross_sectional_benchmark(SEED)
    conditions = load_cross_sectional_benchmark(CONDITIONS)
    frozen = load_cross_sectional_benchmark(FROZEN)

    assert frozen == [*seed, *conditions]
    validate_benchmark(
        frozen,
        expected_count=28,
        expected_splits={"development": 28},
        required_categories={"cross_sectional"},
    )
    validate_cross_sectional_evidence_grounding(frozen)
    validate_cross_sectional_condition_grounding(frozen)
    assert Counter(question.resolved_task_type for question in frozen) == EXPECTED_TASK_COUNTS


def test_frozen_v2_manifest_pins_content_and_task_distribution() -> None:
    manifest = json.loads(MANIFEST.read_text())
    frozen = load_cross_sectional_benchmark(FROZEN)

    assert manifest["benchmark_name"] == "FDRE Cross-Sectional v2 Development"
    assert manifest["benchmark_version"] == "v2"
    assert manifest["split"] == "development"
    assert manifest["status"] == "frozen"
    assert manifest["holdout_status"] == "not_created"
    assert manifest["frozen_after_parts"] == ["7.1", "7.2"]
    assert manifest["question_count"] == 28
    assert manifest["task_type_counts"] == EXPECTED_TASK_COUNTS
    assert manifest["dataset_path"] == str(FROZEN.relative_to(REPO_ROOT))
    assert manifest["dataset_sha256"] == compute_dataset_sha256(frozen)
    assert manifest["file_sha256"] == _sha256(FROZEN)

    expected_components = [(SEED, 13), (CONDITIONS, 15)]
    assert len(manifest["components"]) == len(expected_components)
    for component, (path, count) in zip(
        manifest["components"], expected_components, strict=True
    ):
        questions = load_cross_sectional_benchmark(path)
        assert component["path"] == str(path.relative_to(REPO_ROOT))
        assert component["question_count"] == count
        assert component["dataset_sha256"] == compute_dataset_sha256(questions)
        assert component["file_sha256"] == _sha256(path)
